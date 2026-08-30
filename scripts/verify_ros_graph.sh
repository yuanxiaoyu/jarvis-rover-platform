#!/usr/bin/env bash
set -euo pipefail

# ROS 2 setup scripts use optional variables without nounset guards.
set +u
source /opt/ros/humble/setup.bash
set -u
if [[ -f /workspace/ros2_ws/install/setup.bash ]]; then
  set +u
  source /workspace/ros2_ws/install/setup.bash
  set -u
fi

EXPECTED_ROS_DOMAIN_ID="${EXPECTED_ROS_DOMAIN_ID:-20}"
errors=0

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  errors=$((errors + 1))
}

if [[ "${ROS_DOMAIN_ID:-}" != "$EXPECTED_ROS_DOMAIN_ID" ]]; then
  fail "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}; expected $EXPECTED_ROS_DOMAIN_ID"
fi

TOPICS="$(ros2 topic list 2>/dev/null)"
require_topic() {
  local topic="$1"
  if ! grep -Fxq "$topic" <<<"$TOPICS"; then
    fail "required topic is missing: $topic"
  fi
}

for topic in /scan /odom_raw /imu /mapping/status /mapping/motion_allowed /cmd_vel /cmd_vel_teleop; do
  require_topic "$topic"
done

publisher_count() {
  local topic="$1" info rc count
  set +e
  info="$(ros2 topic info "$topic" 2>/dev/null)"
  rc=$?
  set -e
  if ((rc != 0)); then
    printf '%s\n' -1
    return 0
  fi
  count="$(awk -F: '/Publisher count/ {gsub(/[[:space:]]/, "", $2); print $2; exit}' <<<"$info")"
  printf '%s\n' "${count:-0}"
}

final_publishers="$(publisher_count /cmd_vel)"
input_publishers="$(publisher_count /cmd_vel_teleop)"
if [[ "$final_publishers" != 1 ]]; then
  fail "/cmd_vel has $final_publishers publishers; expected exactly 1"
fi
if ((input_publishers < 1)); then
  fail "/cmd_vel_teleop has $input_publishers publishers; expected at least 1"
fi

NODES=""
for _attempt in {1..5}; do
  NODES="$(ros2 node list --no-daemon --spin-time 2 2>/dev/null || true)"
  if grep -Eiq 'ekf' <<<"$NODES" && grep -Eiq 'slam_toolbox' <<<"$NODES"; then
    break
  fi
  sleep 1
done
ekf_count="$(awk 'tolower($0) ~ /ekf/ {n++} END {print n+0}' <<<"$NODES")"
slam_count="$(awk 'tolower($0) ~ /slam_toolbox/ {n++} END {print n+0}' <<<"$NODES")"
if [[ "$ekf_count" != 1 ]]; then
  fail "found $ekf_count EKF node(s); expected exactly 1"
fi
if [[ "$slam_count" != 1 ]]; then
  fail "found $slam_count slam_toolbox node(s); expected exactly 1"
fi

check_tf() {
  local target="$1" source="$2" output rc
  for _attempt in {1..3}; do
    set +e
    output="$(timeout 4 ros2 run tf2_ros tf2_echo "$target" "$source" 2>&1)"
    rc=$?
    set -e
    if grep -q "At time" <<<"$output"; then
      return 0
    fi
  done
  return 1
}

mapping_status="$(ros2 topic echo /mapping/status --once 2>/dev/null || true)"
mapping_state="$(awk '/^state:/ {print $2; exit}' <<<"$mapping_status")"
if [[ "$mapping_state" == "0" ]]; then
  if ! check_tf map odom; then
    printf '%s\n' "WARN: map -> odom is expected after mapping starts; current mapping state is IDLE" >&2
  fi
else
  if ! check_tf map odom; then
    fail "TF unavailable: map -> odom"
  fi
fi
if ! check_tf odom base_footprint; then
  fail "TF unavailable: odom -> base_footprint"
fi
if ! check_tf base_footprint laser_frame; then
  fail "TF unavailable: base_footprint -> laser_frame"
fi

SERVICES="$(ros2 service list 2>/dev/null)"
for service in \
  /mapping/command \
  /slam_toolbox/pause_new_measurements \
  /slam_toolbox/save_map \
  /slam_toolbox/serialize_map \
  /slam_toolbox/deserialize_map; do
  if ! grep -Fxq "$service" <<<"$SERVICES"; then
    fail "required service is missing: $service"
  fi
done

# Humble's async node may not expose ClearQueue; pause itself stops delivery
# and the gateway treats this endpoint as an optional optimization.
if ! grep -Fxq "/slam_toolbox/clear_queue" <<<"$SERVICES"; then
  printf '%s\n' "WARN: /slam_toolbox/clear_queue is absent; pause will rely on its internal queue handling" >&2
fi

if ((errors > 0)); then
  printf '%d ROS graph check(s) failed.\n' "$errors" >&2
  exit 1
fi
printf '%s\n' "ROS graph checks passed."
