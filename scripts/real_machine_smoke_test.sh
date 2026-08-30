#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONTAINER="${ROVER_RUNTIME_CONTAINER:-jarvis-rover-runtime}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
configured_evidence="${ROVER_RUNTIME_EVIDENCE_DIR:-$ROOT/data/evidence}"

case "$configured_evidence" in
  /workspace/data/*)
    evidence_root="$ROOT/data/${configured_evidence#/workspace/data/}"
    ;;
  "$ROOT"/data/*)
    evidence_root="$configured_evidence"
    ;;
  /*)
    printf 'ERROR: evidence directory must be under the repository data directory\n' >&2
    exit 1
    ;;
  *)
    evidence_root="$ROOT/$configured_evidence"
    ;;
esac

evidence_dir="$evidence_root/$STAMP"
mkdir -p "$evidence_dir"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  printf 'Evidence directory: %s\n' "$evidence_dir" >&2
  exit 1
}

ros_exec() {
  docker exec "$CONTAINER" bash -lc \
    'source /opt/ros/humble/setup.bash; source /workspace/ros2_ws/install/setup.bash; exec "$@"' \
    -- "$@"
}

running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
[[ "$running" == "true" ]] || fail "runtime container is not running: $CONTAINER"

curl -fsS http://127.0.0.1:8000/health >"$evidence_dir/health.json" \
  || fail "runtime health endpoint is unavailable"
curl -fsS http://127.0.0.1:8000/api/v1/mapping >"$evidence_dir/mapping-status.json" \
  || fail "mapping status endpoint is unavailable"

python3 - "$evidence_dir/mapping-status.json" <<'PY'
import json
import sys
from pathlib import Path

status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if status.get("state") != "idle":
    raise SystemExit(f"initial mapping state is not idle: {status.get('state')!r}")
if status.get("motion_allowed") is not False:
    raise SystemExit("initial mapping motion_allowed must be false")
PY

docker exec "$CONTAINER" bash /workspace/scripts/verify_ros_graph.sh \
  >"$evidence_dir/ros-graph-check.txt" 2>&1 \
  || fail "ROS graph verification failed"

docker exec "$CONTAINER" bash /workspace/scripts/measure_ros_baseline.sh \
  >"$evidence_dir/baseline-command.txt" 2>&1 \
  || fail "ROS baseline probe failed"

baseline_path="$(awk '/Baseline written to / {print $NF; exit}' "$evidence_dir/baseline-command.txt")"
if [[ -n "$baseline_path" ]]; then
  case "$baseline_path" in
    /workspace/data/*)
      host_baseline="$ROOT/data/${baseline_path#/workspace/data/}"
      ;;
    *)
      host_baseline=""
      ;;
  esac
  if [[ -n "$host_baseline" && -f "$host_baseline" ]]; then
    cp -- "$host_baseline" "$evidence_dir/baseline.json"
  fi
fi

for command_name in node-list service-list status-once; do
  case "$command_name" in
    node-list)
      ros_exec ros2 node list >"$evidence_dir/nodes.txt"
      ;;
    service-list)
      ros_exec ros2 service list >"$evidence_dir/services.txt"
      ;;
    status-once)
      ros_exec ros2 topic echo /mapping/status --once >"$evidence_dir/mapping-status-once.txt"
      ;;
  esac
done

ros_exec ros2 topic echo /cmd_vel --once >"$evidence_dir/cmd-vel-once.txt"
python3 - "$evidence_dir/cmd-vel-once.txt" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
values = [float(value) for value in re.findall(r"^\s+[xyz]:\s+([-+0-9.eE]+)\s*$", text, re.MULTILINE)]
if len(values) != 6:
    raise SystemExit(f"could not parse six Twist components from /cmd_vel output (found {len(values)})")
if any(value != 0.0 for value in values):
    raise SystemExit(f"initial /cmd_vel sample was not all zero: {values!r}")
PY

printf 'No-motion runtime smoke test passed.\n'
printf 'Evidence directory: %s\n' "$evidence_dir"
printf 'No mapping start/resume or non-zero motion command was sent.\n'
