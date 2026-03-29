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
- `POST /api/missions/whole-home-garbage-scan`
- `POST /api/voice/session`
- `POST /api/voice/tts`
- `GET /api/garbage/detections`
- `POST /api/garbage/detections`: 接收垃圾发现记录，包括 `task_id`, `room_label`, `summary`, `image_url`，供后端触发 OpenClaw 上报。

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

## 垃圾发现与 OpenClaw 上报

### GarbageDetection

- `task_id`: 本次扫描任务的唯一 ID
- `detected_at`: ISO8601 时间戳
- `room_label`: 所属房间或语义区域
- `summary`: 模型给出的垃圾类型/状态描述
- `image_url`: 高质量抓拍图像的可访问地址
- `confidence`: 识别置信度
- `report.status`: `skipped | not_configured | sent | failed`

### 上报链路

1. 语音/AI 桥接将“整屋扫描发现垃圾”的意图拆成结构化任务，并通过 `/api/missions/whole-home-garbage-scan` 或 `/api/voice/command` 入队。
2. ROS2 侧的视觉或语义检测节点通过 `POST /api/garbage/detections` 把检测结果提交到后端。
3. API 层再把该报告转发给 `openclaw` webhook，并由 OpenClaw 里的飞书推送逻辑把图片卡片推到运维群。

此路径的状态更新、图片 URL、飞书卡片模板都应当与 `GarbageDetection` 保持一致，确保后续任务可追踪。

### 视觉检测节点最小约定

- 订阅图像话题：`/camera/image/compressed` 或 `/camera/image_raw`
- 本地抓拍目录：由 ROS2 参数 `capture_dir` 指定
- 支持通过 `label_map_csv` 读取 TACO 风格的 `source_label,target_label` 映射
- 每次抓拍应同时写出 JPEG 和 sidecar JSON
- sidecar JSON 至少包含：`task_id`、`label`、`confidence`、`bbox`、`captured_at`、`image_path`
- 树莓派建议启用：`pi_mode=true`、`frame_stride>=4`、`max_image_dim<=640`
