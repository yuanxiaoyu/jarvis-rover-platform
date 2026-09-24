#!/usr/bin/env bash
set -euo pipefail

# ROS 2 setup scripts read optional environment variables while sourcing.  The
# entrypoint intentionally uses nounset, so temporarily relax it for setup and
# restore strict mode before launching any runtime command.
set +u
source /opt/ros/humble/setup.bash

if [[ -f /workspace/ros2_ws/install/setup.bash ]]; then
  source /workspace/ros2_ws/install/setup.bash
fi
set -u

case "${1:-api}" in
  api)
    cd /workspace/services/api
    exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${ROVER_API_PORT:-8001}"
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
