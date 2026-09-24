#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
API_CONTAINER="${ROVER_API_CONTAINER:-jarvis-rover-runtime}"
HARDWARE_IMAGE="${YAHBOOM_ROS_IMAGE:-yahboomtechnology/ros-humble:4.1.2}"
ROS_DOMAIN="${ROVER_ROS_DOMAIN_ID:-20}"
MODE="check"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

usage() {
  printf 'Usage: %s [--check|--apply]\n' "${0##*/}"
  printf '  --check  Verify joystick routing and /cmd_vel publishers without changing the robot (default).\n'
  printf '  --apply  Install the remapped joystick launcher, restart ChassisServer, then verify both ROS graphs.\n'
}

while (($# > 0)); do
  case "$1" in
    --check) MODE="check"; shift ;;
    --apply) MODE="apply"; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; fail "unknown argument: $1" ;;
  esac
done

[[ "$ROS_DOMAIN" =~ ^[0-9]+$ ]] || fail "ROVER_ROS_DOMAIN_ID must be numeric"
command -v docker >/dev/null 2>&1 || fail "docker is not available"

LAUNCH_FILE="$ROOT/deploy/yahboom_joy_remapped.launch.py"
[[ -f "$LAUNCH_FILE" ]] || fail "remapped launch file is missing: $LAUNCH_FILE"
grep -Fq 'remappings=[("cmd_vel", "/cmd_vel_teleop")]' "$LAUNCH_FILE" \
  || fail "joystick launch must remap cmd_vel to /cmd_vel_teleop"

if [[ -z "${YAHBOOM_CONTAINER:-}" ]]; then
  mapfile -t hardware_containers < <(docker ps --filter "ancestor=$HARDWARE_IMAGE" --format '{{.Names}}')
  ((${#hardware_containers[@]} == 1)) \
    || fail "expected one running Yahboom ROS container for $HARDWARE_IMAGE; found ${#hardware_containers[@]}"
  HARDWARE_CONTAINER="${hardware_containers[0]}"
else
  HARDWARE_CONTAINER="$YAHBOOM_CONTAINER"
fi

for container in "$API_CONTAINER" "$HARDWARE_CONTAINER"; do
  [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" == "true" ]] \
    || fail "required container is not running: $container"
done

hardware_ready() {
  docker exec "$HARDWARE_CONTAINER" supervisorctl status ChassisServer 2>/dev/null \
    | grep -q 'RUNNING' \
    && docker exec "$HARDWARE_CONTAINER" sh -lc \
      'grep -Fq "exec ros2 launch /root/jarvis_rover_joy_remapped.launch.py" /root/run_handle.sh' \
    && docker exec "$HARDWARE_CONTAINER" grep -Fq \
      'remappings=[("cmd_vel", "/cmd_vel_teleop")]' /root/jarvis_rover_joy_remapped.launch.py
}

topic_info() {
  local container="$1" setup_file="$2" topic="$3"
  docker exec "$container" bash -lc '
    set +u
    source /opt/ros/humble/setup.bash
    source "$1"
    set -u
    export ROS_DOMAIN_ID="$2"
    ros2 topic info "$3"
  ' _ "$setup_file" "$ROS_DOMAIN" "$topic"
}

publisher_count() {
  awk -F: '/Publisher count:/ {gsub(/[[:space:]]/, "", $2); print $2; exit}'
}

verify_graph() {
  local label="$1" container="$2" setup_file="$3" cmd_info teleop_info cmd_count teleop_count
  cmd_info="$(topic_info "$container" "$setup_file" /cmd_vel)" \
    || fail "$label ROS graph cannot inspect /cmd_vel"
  teleop_info="$(topic_info "$container" "$setup_file" /cmd_vel_teleop)" \
    || fail "$label ROS graph cannot inspect /cmd_vel_teleop"
  cmd_count="$(publisher_count <<<"$cmd_info")"
  teleop_count="$(publisher_count <<<"$teleop_info")"
  [[ "$cmd_count" == 0 ]] \
    || fail "$label ROS graph has $cmd_count /cmd_vel publisher(s); refusing to permit an unsafe setup"
  [[ "$teleop_count" == 1 ]] \
    || fail "$label ROS graph has $teleop_count /cmd_vel_teleop publishers; expected exactly one"
  printf '%s ROS graph: /cmd_vel publishers=%s, /cmd_vel_teleop publishers=%s\n' \
    "$label" "$cmd_count" "$teleop_count"
}

if [[ "$MODE" == apply ]]; then
  docker cp "$LAUNCH_FILE" "$HARDWARE_CONTAINER:/root/jarvis_rover_joy_remapped.launch.py" \
    || fail "could not install remapped Yahboom launch file"
  if ! docker exec -i "$HARDWARE_CONTAINER" bash -s <<'HARDWARE_APPLY'
set -euo pipefail
supervisorctl stop ChassisServer >/dev/null 2>&1 || true

# Remove any joystick child left behind by an older Supervisor launch. Never
# bring back the vendor's direct /cmd_vel mapping if this setup fails.
pkill -INT -f '^/usr/bin/python3 /root/yahboomcar_ws/install/yahboomcar_ctrl/lib/yahboomcar_ctrl/yahboom_joy([[:space:]]|$)' || true
pkill -INT -f '^/opt/ros/humble/lib/joy/joy_node([[:space:]]|$)' || true
for _attempt in {1..20}; do
  if ! pgrep -f '^/usr/bin/python3 /root/yahboomcar_ws/install/yahboomcar_ctrl/lib/yahboomcar_ctrl/yahboom_joy([[:space:]]|$)' >/dev/null \
      && ! pgrep -f '^/opt/ros/humble/lib/joy/joy_node([[:space:]]|$)' >/dev/null; then
    break
  fi
  sleep 0.25
done
if pgrep -f '^/usr/bin/python3 /root/yahboomcar_ws/install/yahboomcar_ctrl/lib/yahboomcar_ctrl/yahboom_joy([[:space:]]|$)' >/dev/null \
    || pgrep -f '^/opt/ros/humble/lib/joy/joy_node([[:space:]]|$)' >/dev/null; then
  echo 'ERROR: stale joystick process did not stop; ChassisServer remains stopped.' >&2
  exit 1
fi

cat >/root/run_handle.sh <<'RUN_HANDLE'
#!/bin/sh
exec bash -lc 'source /opt/ros/humble/setup.bash && source /root/yahboomcar_ws/install/setup.bash && export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-20}" && exec ros2 launch /root/jarvis_rover_joy_remapped.launch.py'
RUN_HANDLE
chmod 0755 /root/run_handle.sh
supervisorctl start ChassisServer
HARDWARE_APPLY
  then
    docker exec "$HARDWARE_CONTAINER" supervisorctl stop ChassisServer >/dev/null 2>&1 || true
    fail "joystick setup failed; ChassisServer was left stopped and no direct /cmd_vel fallback was restored"
  fi
fi

hardware_ready || fail "Yahboom Supervisor is not running the remapped joystick launcher"
verify_graph "hardware" "$HARDWARE_CONTAINER" /root/yahboomcar_ws/install/setup.bash
verify_graph "API" "$API_CONTAINER" /workspace/ros2_ws/install/setup.bash
printf 'Safe joystick routing verified. No exploration or movement command was sent.\n'
