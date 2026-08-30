#!/usr/bin/env sh
set -eu

exec /bin/bash -lc 'source /opt/ros/humble/setup.bash; source /root/yahboomcar_ws/install/setup.bash; exec ros2 launch /root/joy_remapped.launch.py'
