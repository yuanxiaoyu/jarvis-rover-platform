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
- `rover_vision`: YOLO-style garbage detection, capture persistence, and API reporting

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

## Whole-home garbage scan flow

For the command "贾维斯，请帮我扫描整个房屋，发现有垃圾请拍照告诉我", the scaffold now reserves these bridge parameters:

- `rover_voice_bridge.params.voice_bridge.yaml`
  - `whole_home_scan_intent`
  - `whole_home_scan_phrase_hint`
  - `forward_command_api_path`
- `rover_ai_bridge.params.ai_bridge.yaml`
  - `whole_home_garbage_scan_path`
  - `garbage_detection_report_path`
  - `report_channel`
  - `report_target`
  - `require_photo`

Recommended runtime flow:

1. `rover_voice_bridge` recognizes the wake word plus whole-home garbage scan phrase and forwards the transcript to `/api/v1/voice/command`.
2. `rover_ai_bridge` can also create the same task directly through `/api/v1/missions/whole-home-garbage-scan`.
3. Vision or semantic detection nodes post snapshot results to `/api/v1/garbage/detections`.
4. The API then forwards the detection payload to OpenClaw, which relays the image into the bound Feishu channel.

## YOLO-style garbage detector

`rover_vision` adds a `garbage_detection_node` with these expectations:

- Runtime Python deps: `ultralytics`, `pillow`, `numpy`
- Model file: configured by `params/vision.yaml` via `model_path`, defaulting to `/workspace/models/yolo/dllg_best.pt`
- Camera topic: defaults to `/camera/image/compressed`
- Capture directory: defaults to `/tmp/rover_captures`

The default profile is now tuned for TACO-style detection:

- default model path: `/workspace/models/yolo/taco_pi_best.pt`
- optional class map CSV: `/workspace/models/yolo/taco_map_10.csv`
- supports official TACO-style `source_label,target_label` remapping

This lets you run either:

- a fine-grained TACO model with many original classes
- a grouped TACO model using class maps such as `map_10.csv` or `map_17.csv`

The node only reports when it sees an active `whole_home_scan` task from the API. When a garbage-class label is detected, it:

1. Saves an annotated JPEG snapshot to the capture directory.
2. Saves a sidecar JSON file with label/confidence/bbox metadata.
3. Calls `/api/v1/garbage/detections` so the API can trigger OpenClaw -> Feishu reporting.

Bringup integration is present but disabled by default. Enable it with:

```bash
ros2 launch rover_bringup bringup.launch.py use_garbage_detection:=true
```

For Raspberry Pi, start with the defaults in `params/vision.yaml`:

- `pi_mode: true`
- `frame_stride: 6`
- `max_image_dim: 640`
- `model_input_size: 640`

These reduce inference load by skipping frames and resizing long edges before prediction.
