# Rover ROS2 Workspace (Scaffold)

Target: Raspberry Pi 5, Ubuntu 22.04, ROS2 Humble.

## Package layout

- `rover_interfaces`: custom messages/services
- `rover_bringup`: launch orchestration and shared params
- `rover_mapping`: MS200 TOF lidar 2D occupancy mapping hooks
- `rover_navigation`: Nav2 integration + keepout/virtual-wall placeholders
- `rover_safety`: safety monitor skeleton
- `rover_ai_bridge`: API/AI bridge skeleton
- `rover_voice_bridge`: voice adapter skeleton (mock + optional sherpa-onnx path)

## Mapping assumption

MS200 TOF lidar is treated as a 2D source. Any 3D scene view is reconstructed from:

- occupancy grid geometry
- semantic zones (keepout, virtual walls, semantic labels)

No true volumetric reconstruction is assumed in this scaffold.

## Build

```bash
source /opt/ros/humble/setup.bash
cd /workspace/ros2_ws
colcon build --symlink-install
source install/setup.bash
```

## Optional sherpa-onnx voice adapter

`rover_voice_bridge` supports an adapter switch in `params/voice_bridge.yaml`:

- `adapter: mock` (default)
- `adapter: sherpa_onnx` (optional, Pi-friendly)

When enabling `sherpa_onnx`, mount model files and set:

- `sherpa.model_dir`
- `sherpa.tokens_path`
- `sherpa.provider` (cpu)

