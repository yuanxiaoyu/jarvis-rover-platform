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

mapping_launch_args() {
  local session_dir="${ROVER_MAPPING_SESSION_DIR:-/workspace/data/maps}"
  local params_file="${ROVER_SLAM_PARAMS_FILE:-}"
  if [[ -z "$params_file" ]]; then
    params_file="$(ros2 pkg prefix rover_mapping)/share/rover_mapping/params/slam_toolbox_online_async.yaml"
  fi
  printf '%s\n' "session_dir:=$session_dir" "slam_params_file:=$params_file"
}

case "${1:-api}" in
  api)
    cd /workspace/services/api
    exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  mapping)
    mapfile -t args < <(mapping_launch_args)
    exec ros2 launch rover_bringup mapping.launch.py "${args[@]}"
    ;;
  runtime)
    mapfile -t args < <(mapping_launch_args)
    mapping_pid=0
    api_pid=0
    stopping=0
    cleanup() {
      if ((stopping)); then
        return
      fi
      stopping=1
      trap - TERM INT EXIT
      if ((mapping_pid > 0)); then
        kill "$mapping_pid" 2>/dev/null || true
      fi
      if ((api_pid > 0)); then
        kill "$api_pid" 2>/dev/null || true
      fi
      if ((mapping_pid > 0)); then
        wait "$mapping_pid" 2>/dev/null || true
      fi
      if ((api_pid > 0)); then
        wait "$api_pid" 2>/dev/null || true
      fi
    }
    trap cleanup TERM INT EXIT

    ros2 launch rover_bringup mapping.launch.py "${args[@]}" &
    mapping_pid=$!
    startup_timeout="${ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS:-60}"
    if ! [[ "$startup_timeout" =~ ^[0-9]+$ ]] || ((startup_timeout < 1)); then
      printf '%s\n' "mapping service startup timeout must be a positive integer" >&2
      cleanup
      trap - EXIT
      exit 1
    fi

    mapping_ready=0
    startup_deadline=$((SECONDS + startup_timeout))
    while ((SECONDS < startup_deadline)); do
      if ! kill -0 "$mapping_pid" 2>/dev/null; then
        printf '%s\n' "mapping launch failed before API startup" >&2
        cleanup
        trap - EXIT
        exit 1
      fi
      if ros2 service list 2>/dev/null | grep -Fxq "/mapping/command"; then
        mapping_ready=1
        break
      fi
      sleep 1
    done
    if ((mapping_ready == 0)); then
      printf 'mapping service did not become ready within %ss\n' "$startup_timeout" >&2
      cleanup
      trap - EXIT
      exit 1
    fi

    cd /workspace/services/api
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
    api_pid=$!
    cd /workspace

    exit_status=0
    while true; do
      if ! kill -0 "$mapping_pid" 2>/dev/null; then
        exit_status=1
        break
      fi
      if ! kill -0 "$api_pid" 2>/dev/null; then
        exit_status=1
        break
      fi
      sleep 1
    done
    cleanup
    trap - EXIT
    exit "$exit_status"
    ;;
  bringup)
    exec ros2 launch rover_bringup bringup.launch.py
    ;;
  probe)
    exec bash /workspace/scripts/verify_ros_graph.sh
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
