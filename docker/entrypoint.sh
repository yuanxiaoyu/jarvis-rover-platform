#!/usr/bin/env bash
set -euo pipefail

source /opt/ros/humble/setup.bash

if [[ -f /workspace/ros2_ws/install/setup.bash ]]; then
  source /workspace/ros2_ws/install/setup.bash
fi

case "${1:-api}" in
  api)
    cd /workspace/services/api
    exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  bringup)
    exec ros2 launch rover_bringup bringup.launch.py
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    exec "$@"
    ;;
esac
