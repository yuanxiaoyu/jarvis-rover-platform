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

if ! command -v ros2 >/dev/null 2>&1; then
  printf '%s\n' "ros2 is not available; run this script in the ROS 2 runtime container." >&2
  exit 1
fi

output_dir="/workspace/data/baselines"
mkdir -p "$output_dir"
output_path="$output_dir/$(date -u +%Y%m%dT%H%M%SZ).json"
python3 /workspace/scripts/ros_graph_probe.py \
  --duration "${ROVER_BASELINE_DURATION_SECONDS:-10}" \
  --domain-id "${ROS_DOMAIN_ID:-20}" \
  --output "$output_path"
printf 'Baseline written to %s\n' "$output_path"
