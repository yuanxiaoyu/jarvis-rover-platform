# 集成接口约定

## WebSocket 事件类型

前端预期从单一遥测流中接收带类型的事件。

核心事件包括：

- `system.snapshot`
- `robot.pose`
- `robot.telemetry`
- `map.snapshot`
- `lidar.scan`
- `camera.frame`
- `mission.state`
- `voice.state`
- `alerts.active`

## REST 接口

规划中的接口如下：

- `GET /api/health`
- `GET /api/system/snapshot`
- `GET /api/map`
- `POST /api/map/build/start`
- `POST /api/map/build/stop`
- `POST /api/zones`
- `PUT /api/zones/{zone_id}`
- `POST /api/virtual-walls`
- `DELETE /api/virtual-walls/{wall_id}`
- `POST /api/missions/navigate`
- `POST /api/missions/ai-command`
- `POST /api/voice/session`
- `POST /api/voice/tts`

当前 Web 控制台使用的真实硬件接口：

- `GET /api/v1/camera/status`
- `GET /api/v1/camera/mjpeg`（V4L2 摄像头的 MJPEG 流）
- `GET /api/v1/radar`（MS200 `/scan` 归一化后的 2D 点）
- `GET /api/v1/gimbal`、`POST /api/v1/gimbal`（白名单 `/servo_s1`、`/servo_s2`）
- `POST /api/v1/assistant/chat`（后端 AI gateway，浏览器不携带模型密钥）

ROS、摄像头或语音依赖缺失时，接口返回 `unavailable`/`stale`/`503`，前端必须显示该状态，不得用 mock 数据替代。

## 共享数据结构

### Zone

- `id`
- `name`
- `kind`
- `polygon`
- `priority`

### VirtualWall

- `id`
- `name`
- `points`
- `enabled`

### MapSnapshot

- `id`
- `name`
- `resolution`
- `origin`
- `size`
- `occupancy`
- `zones`
- `virtual_walls`
- `mesh`

### MissionCommand

- `type`
- `target_zone_id`
- `waypoints`
- `command_text`
- `voice_session_id`

## ROS2 到 API 的归一化

API 层应该先把 ROS 原始结构整理成浏览器适合消费的格式，再向前端广播。

例如：

- `sensor_msgs/LaserScan` -> UI 使用的极坐标或笛卡尔采样点
- `nav_msgs/OccupancyGrid` -> 带世界坐标元数据的标准化占据栅格
- `geometry_msgs/PoseStamped` -> 轻量位姿对象
- 图像话题 -> MJPEG / WebRTC / WebSocket 图像传输元数据

## 摄像头传输策略

优先级建议如下：

1. 如果硬件和网络允许，优先使用 MJPEG 或 WebRTC
2. 其次由 API 转发压缩图像话题
3. 在离线或 mock 开发阶段，使用静态占位图

## AI 安全约束

在 AI 指令真正转成任务之前，后端至少要检查：

- 目标区域是否存在
- 指令是否穿越了禁行区或未启用区域
- 当前电量与通信状态是否允许执行
- 是否存在未解除的安全急停
