# 集成接口约定

本文件是浏览器/API、ROS 2 runtime 和 Yahboom 硬件层之间的阶段 0～1 契约。真实硬件当前使用 `ROS_DOMAIN_ID=20`。

## 支持的 ROS 图

Yahboom 硬件层提供：

- `/scan`：`sensor_msgs/msg/LaserScan`
- `/odom_raw`：`nav_msgs/msg/Odometry`
- `/imu`：`sensor_msgs/msg/Imu`
- `/battery`
- `/cmd_vel` 的底盘订阅

项目 runtime 提供：

- `/imu/data`：互补滤波后的 IMU
- `/odom`：唯一 `robot_localization` EKF 输出
- `/map`：唯一 `slam_toolbox` 输出
- `/mapping/status`：`rover_interfaces/msg/MappingSession`
- `/mapping/motion_allowed`：`std_msgs/msg/Bool`
- `/mapping/diagnostics`：`diagnostic_msgs/msg/DiagnosticArray`
- `/mapping/command`：`rover_interfaces/srv/MappingCommand`
- 最终 `/cmd_vel`：安全层唯一 publisher

生产中同时只能有一个 EKF、一个 `map -> odom` publisher、一个最终 `/cmd_vel` publisher 和一个 SLAM backend。所有容器使用 Domain 20。

## WebSocket 事件类型

前端预期从单一遥测流中接收带类型的事件：

- `system.snapshot`
- `robot.pose`
- `robot.telemetry`
- `map.snapshot`
- `lidar.scan`
- `camera.frame`
- `mission.state`
- `voice.state`
- `alerts.active`

当前 `WS /ws/telemetry` 仍是 API 的 mock/遥测流；它不应被描述成已经完成的原始 ROS 地图流。真正的地图会话状态通过下面的 REST endpoint 和 `/mapping/status` 提供。客户端必须使用有界缓存，落后时丢弃旧快照而不是反压 ROS。

## Mapping REST API

API prefix 为 `/api/v1`：

- `GET /api/v1/mapping`
- `POST /api/v1/mapping/start`
- `POST /api/v1/mapping/pause`
- `POST /api/v1/mapping/resume`
- `POST /api/v1/mapping/stop`
- `POST /api/v1/mapping/save`
- `POST /api/v1/mapping/load`

请求/响应：

```json
POST /api/v1/mapping/start
{"session_id":"bench-room"}

202
{"accepted":true,"state":"starting","message":"mapping start queued"}
```

`load` 必须显式包含 session、地图位姿和匹配模式：

```json
POST /api/v1/mapping/load
{"session_id":"bench-room","x":1.0,"y":1.0,"yaw":0.0,"match_type":2}
```

`match_type=2` 是 SLAM Toolbox `START_AT_GIVEN_POSE`；`match_type=3` 是 `LOCALIZE_AT_POSE`。服务端模型和 ROS mapping node 双重校验这些字段。

HTTP 语义：

- `202`：命令已排队；不代表执行已经完成，客户端应持续读取 mapping status。
- `409`：当前状态不允许该命令。
- `422`：请求结构、session ID、地图名或 load 位姿不合法。
- `503`：ROS bridge 或 mapping service 不可用。

### Mapping state

`state` 只能是：

- `idle`
- `starting`
- `mapping`
- `paused`
- `saving`
- `error_recoverable`

`motion_allowed=true` 仅能出现在已经完成 start/resume 且没有急停的 `mapping` 状态。加载 pose graph 成功后必须保持 `paused`，等待显式 resume。

## ROS MappingSession.msg

```text
std_msgs/Header header
uint8 IDLE=0
uint8 STARTING=1
uint8 MAPPING=2
uint8 PAUSED=3
uint8 SAVING=4
uint8 ERROR_RECOVERABLE=5
string session_id
uint8 state
bool ready
bool motion_allowed
float32 map_update_age_s
string current_revision
string last_error
```

没有地图时 `map_update_age_s` 使用负值 sentinel；API 将其转换为 `null`。

## ROS MappingCommand.srv

```text
uint8 START=0
uint8 PAUSE=1
uint8 RESUME=2
uint8 STOP=3
uint8 SAVE=4
uint8 LOAD=5
uint8 command
string session_id
string map_name
int8 match_type
bool has_initial_pose
geometry_msgs/Pose2D initial_pose
---
bool accepted
uint8 state
string message
```

service callback 只做校验、状态预留和入队；阻塞的 SLAM service、TF 等待和文件写入在单线程 worker 中执行。

## 建图会话持久化

```text
/workspace/data/maps/sessions/<session_id>/
├── current.json
└── revisions/<revision_id>/
    ├── map.pgm
    ├── map.yaml
    ├── posegraph
    ├── posegraph.data        # SLAM Toolbox companion; optional for backends without a sidecar
    └── manifest.json
```

manifest 的 schema version 为 1，包含 identity、文件大小/SHA-256、创建时间和元数据。revision 先写 staging 目录，完成 fsync 和校验后才原子替换 current 指针。加载时每个文件都必须通过 hash 校验。

## ROS2 到 API 的归一化

API 层先把 ROS 原始结构整理成浏览器适合消费的格式，再向前端广播：

- `sensor_msgs/LaserScan` -> UI 使用的极坐标或笛卡尔采样点；
- `nav_msgs/OccupancyGrid` -> 带世界坐标元数据的标准化占据栅格；
- `geometry_msgs/PoseStamped` -> 轻量位姿对象；
- 图像话题 -> MJPEG / WebRTC / WebSocket 图像传输元数据。

## 摄像头传输策略

优先级建议如下：

1. 硬件和网络允许时使用 MJPEG 或 WebRTC；
2. 其次由 API 转发压缩图像话题；
3. 离线或 mock 开发阶段使用静态占位图。

摄像头拥塞时先丢媒体帧，不能阻塞控制、急停或 mapping worker。

## AI 安全约束

在 AI 指令真正转成任务之前，后端至少要检查：

- 目标区域是否存在；
- 指令是否穿越禁行区或未启用区域；
- 当前电量与通信状态是否允许执行；
- 是否存在未解除的安全急停；
- mapping/safety status 是否允许下发运动。

自然语言和后续语音不允许直接生成未经校验的 ROS 命令。
