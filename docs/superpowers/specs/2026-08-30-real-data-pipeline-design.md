# 真实数据管线与小车控制台设计

- 日期：2026-08-30
- 状态：待用户审阅
- 范围：阶段 A——ROS 2 到 FastAPI 到 Vue 的真实数据管线
- 相关运行时：ROS 2 Humble、Yahboom 硬件容器、`rover-runtime`、FastAPI、Vue

## 1. 背景与问题

当前控制台的运行时状态由 `apps/web/src/data/mockWorld.ts` 生成，包含模拟地图、模拟雷达点、模拟相机 SVG、硬编码任务、路径和遥测。`App.vue` 通过定时器推进这些状态，因此即使 ROS 数据不可用，页面也会显示看似在线的机器人。

这会导致以下问题：

- 用户无法判断建图、雷达、位姿和摄像头是否真的工作。
- 建图按钮和页面状态没有连接到真实 `/mapping/status`。
- 页面无法区分 WebSocket 在线与 ROS 数据源在线。
- 未接入摄像头时仍显示伪造图像。
- 后续路径规划、标签、云台和 AI 功能没有可靠的地图坐标和实时状态基础。

本设计先交付真实数据管线和一屏控制台。数据不可用时必须显示明确的 `unavailable`、`stale` 或 `error`，不得使用 mock 数据、演示数据或硬编码真实状态伪装可用。

## 2. 目标

阶段 A 完成后，系统应能够：

1. 由 FastAPI 统一订阅并读取 ROS 2 实时数据。
2. 通过 REST bootstrap 和版本化 WebSocket 向浏览器提供真实数据。
3. 在浏览器真实渲染 `/map`、`/scan`、真实位姿、建图状态和运动权限。
4. 通过真实 mapping API 启动、暂停、恢复、保存和停止建图。
5. 在无相机话题、话题断流、TF 缺失、消息过期或编码失败时明确报告状态。
6. 在 `1280×720` 基准视口内无需滚动查看地图、建图控制、数据源状态、相机状态和安全状态。
7. 保持现有安全拓扑：前端不直接发布 `/cmd_vel`，不绕过 `rover_safety`，不改变 systemd 只托管 `rover-runtime` 的约束。
8. 为后续路径、标签、云台和 AI 配置提供稳定的版本化扩展边界。

## 3. 非目标与明确边界

本阶段不实现以下能力：

- 完整路径规划、导航 action、路径执行或自动驾驶策略。
- 标签 CRUD、虚拟墙持久化或区域编辑后端。
- 云台/摄像头运动控制和具体硬件驱动。
- AI 模型调用、模型凭据管理、任务编排或语音控制。
- 浏览器直接连接 rosbridge、ROS Domain 或 ROS service。
- 用 mock 数据作为生产 fallback。
- 通过前端直接向 `/cmd_vel` 发布速度。

路径、标签、云台和 AI 只在本阶段定义能力声明和 UI 入口的未接入状态。后续阶段必须复用本阶段的地图坐标、数据源健康和能力模型，不得重新引入静态演示数据。

## 4. 现有真实 ROS 输入

第一阶段优先接入当前运行时已经定义或真机已发现的接口：

| 数据 | ROS 接口 | 消息类型 | 用途 |
| --- | --- | --- | --- |
| 地图 | `/map` | `nav_msgs/msg/OccupancyGrid` | 实时 OccupancyGrid 底图 |
| 雷达 | `/scan` | `sensor_msgs/msg/LaserScan` | 有效量程点和扫描健康 |
| 原始里程计 | `/odom_raw` | `nav_msgs/msg/Odometry` | 诊断和输入健康 |
| 滤波里程计 | `/odometry/filtered` | `nav_msgs/msg/Odometry` | 机器人速度和 odom 位姿 |
| IMU | `/imu/data` | `sensor_msgs/msg/Imu` | 姿态和传感器诊断 |
| 建图状态 | `/mapping/status` | `rover_interfaces/msg/MappingSession` | 建图状态机和按钮 |
| 运动权限 | `/mapping/motion_allowed` | `std_msgs/msg/Bool` | 运动锁状态 |
| 实际安全输出 | `/cmd_vel` | `geometry_msgs/msg/Twist` | 只读显示最终安全速度 |
| 手柄输入 | `/cmd_vel_teleop` | `geometry_msgs/msg/Twist` | 只读诊断输入是否存在 |
| 摄像头 | 配置指定 | `sensor_msgs/msg/Image` 或 `sensor_msgs/msg/CompressedImage` | 真实相机帧 |

电量、温度和电机电流的真实 ROS 来源在阶段 A 中不得假定。只有配置了并验证了真实 topic 后才能显示数值；否则对应字段为 `null`，健康状态为 `unavailable`，不得使用 `84%`、`47℃` 等演示值。

### 4.1 摄像头配置

摄像头来源固定为 ROS 图像话题。运行时配置至少包括：

```text
ROVER_CAMERA_IMAGE_TOPIC
ROVER_CAMERA_IMAGE_TYPE=sensor_msgs/msg/Image
ROVER_CAMERA_MAX_WIDTH
ROVER_CAMERA_JPEG_QUALITY
```

`ROVER_CAMERA_IMAGE_TYPE` 只允许支持的两种消息类型。话题未配置、话题不存在、发布者类型不匹配、没有有效帧或转换失败时，相机源分别报告明确的 `unavailable` 或 `error`。不得生成 data URI、静态图、SVG 或其他占位帧。

当前真机尚未确认存在稳定的 `/camera/*` 或图像消息源，因此在未接入驱动前，摄像头验收的正确结果是“不可用并说明原因”。

## 5. 总体架构

```text
ROS 2 topics/services
        │
        ▼
FastAPI ROS bridge
  ├─ ROS context/node/executor
  ├─ subscriptions and QoS handling
  ├─ timestamp and freshness tracking
  ├─ TF lookup and coordinate conversion
  ├─ map/scan normalization and encoding
  ├─ optional image conversion
  └─ immutable current-state cache
        │
        ├─ REST: bootstrap, sources, capabilities, mapping commands
        └─ WebSocket: telemetry events and camera binary frames
        │
        ▼
Vue console
  ├─ schema validation and reconnect
  ├─ real-data state reducer
  ├─ map/scan/camera rendering
  └─ live/stale/unavailable/error presentation
```

### 5.1 后端组件边界

#### `RosMappingBackend`

保留现有 mapping 命令职责，负责将 REST 命令映射为 `/mapping/command` service 调用，并返回真实 accepted/state/message。它不生成实时传感器数据。

#### `RosTelemetryBridge`

新增或等价拆分的实时桥接组件，职责为：

- 创建独立的 ROS context、node、executor 和订阅。
- 订阅配置启用的实时 topic。
- 记录每个源的最后有效消息、ROS 时间戳、接收时间、消息类型和错误。
- 将 ROS 消息转成 API 领域模型。
- 使用 TF 将雷达和位姿转换到声明的目标 frame。
- 将最新状态提交给广播层。
- 在单个订阅解析异常时记录该源错误并继续服务其他源。

它不负责 mapping 命令、WebSocket 连接管理或 safety gate 控制。

#### `RealtimeHub`

负责客户端连接、事件广播和慢客户端隔离：

- 每个客户端使用有界发送队列。
- `mapping_status`、`motion_allowed` 和关键 `source_health` 事件不可丢弃。
- 旧的 `scan` 和相机帧可被新帧替换或丢弃。
- 新连接先收到可用的完整快照，再收到增量事件。
- 每个事件使用服务端单调递增 sequence。
- 客户端断开后释放队列和连接资源。

#### API 领域模型

实时模型与命令模型分离。所有实时事件都使用统一 envelope；可选值必须显式为 `null`，不使用业务假值：

```text
RealtimeEnvelope
  schema_version: integer
  type: string
  sequence: integer
  ros_stamp: ISO-8601 datetime|null
  received_at: ISO-8601 datetime
  source: string
  payload: object
  health: SourceHealth|null
```

核心 payload：

```text
MapSnapshot
  frame_id
  width
  height
  resolution_m
  origin: {x, y, yaw_rad}
  encoding: "png"
  image_base64
  content_hash
  occupied_thresh
  free_thresh
  negate

ScanSnapshot
  source_frame
  target_frame
  points: [[x, y], ...]
  valid_count
  range_min_m
  range_max_m
  transform_applied
  transform_error: string|null

RobotSnapshot
  frame_id
  x
  y
  yaw_rad
  linear_velocity_mps
  angular_velocity_rps

SourceHealth
  source_id
  state: "live"|"stale"|"unavailable"|"error"
  last_ros_stamp: ISO-8601 datetime|null
  last_received_at: ISO-8601 datetime|null
  age_ms: integer|null
  stale_after_ms: integer
  reason: string|null
```

## 6. 坐标和数据处理契约

### 6.1 地图

后端保留 `/map` 的真实元数据：`frame_id`、`width`、`height`、`resolution`、带 yaw 的 origin、阈值和 negate。地图栅格的像素语义为：

- 黑色：占用（原始值达到占用阈值）。
- 白色：空闲（原始值达到空闲阈值）。
- 灰色：未知（原始值为 `-1` 或不属于已定义区间）。

后端将当前真实 OccupancyGrid 编码为 PNG，并在事件中保留元数据和 `content_hash`。只有地图内容或元数据变化时才发送 `map` 事件；相同 hash 不重复发送。前端把 PNG 作为真实栅格纹理，不从 zone、route 或默认 bounds 构造地图。

地图坐标转换必须遵循 OccupancyGrid origin 的平移和 yaw。前端绘制时使用 `frame_id` 和 origin，不假设地图原点为零或 yaw 为零。

### 6.2 位姿

后端优先使用 `/odometry/filtered` 的 odom 位姿和速度，并通过 TF 取得 `map → odom → base_footprint` 的关系。当 `map → odom` 尚未建立（例如 mapping 处于 `IDLE`）时，位姿必须声明真实 frame 为 `odom`，不能标记为 `map`。TF 查询失败时，保留可验证的原始 odom 位姿并把转换健康标记为 `error` 或 `unavailable`。

前端只显示最后收到的真实 pose。位姿过期后可保留最后位置作为“最后数据”，但必须停止实时视觉效果并显示 stale 遮罩。

### 6.3 雷达

`LaserScan` 处理步骤：

1. 按 `range_min`、`range_max`、有限数值和配置上限过滤 ranges。
2. 根据 `angle_min + index * angle_increment` 计算局部坐标。
3. 查询 source frame 到目标显示 frame 的 TF。
4. TF 成功时输出目标 frame 下的点；TF 失败时输出 source frame 下的点，并设置 `transform_applied=false`，禁止前端把局部点误画为地图坐标。
5. 按配置的最大点数和采样策略降采样，同时保留真实 `valid_count`。
6. 按配置的最大频率广播；不修改原始 ROS 消息或 safety 行为。

雷达数据过期时保留最后一帧但显示 stale，且不得继续制造或平滑生成新点。

### 6.4 图像

ROS `Image` 通过受支持的编码转换为 JPEG；`CompressedImage` 在编码已是 JPEG 时可直接转发，否则解码后按配置重新编码。每个相机帧包含宽、高、原始 ROS 时间戳、接收时间、序号和编码元数据。视频帧不塞入 telemetry JSON，以免阻塞 mapping 状态和安全事件。

## 7. REST API 契约

保留现有 mapping 路由：

```text
POST /api/v1/mapping/start
POST /api/v1/mapping/pause
POST /api/v1/mapping/resume
POST /api/v1/mapping/save
POST /api/v1/mapping/stop
POST /api/v1/mapping/load
```

mapping 命令的状态来源仍是 ROS `/mapping/status`。前端不能因为 HTTP 请求成功就本地假设状态转移；必须等待 API 响应和后续真实状态事件。

新增只读控制台路由：

```text
GET /api/v1/console/bootstrap
GET /api/v1/console/sources
GET /api/v1/console/capabilities
```

`bootstrap` 返回：

- `schema_version`。
- 当前可用的 mapping status、motion permission 和实际安全速度。
- 最近的 map、scan、robot 数据（没有则为 `null`）。
- 所有启用或配置源的 `SourceHealth`。
- 可用相机列表及相机能力。
- 后端实际 freshness、限频和编码配置。
- 路径、标签、云台、AI 的能力状态；未实现能力必须是 `unavailable` 或 `not_implemented`，不能返回演示配置。

ROS bridge 初始化失败且 `ROVER_ROS_BRIDGE_REQUIRED=true` 时，服务启动失败或返回明确 bridge error；生产路径不得静默切换为 `InMemoryMappingBackend`。

## 8. WebSocket 契约

### 8.1 Telemetry 通道

复用现有路径：

```text
WS /ws/telemetry
```

连接后先发送一次 `snapshot`，之后发送增量事件。事件类型包括：

```text
snapshot
mapping_status
robot_state
map
scan
source_health
command_result
```

事件示例：

```json
{
  "schema_version": 1,
  "type": "scan",
  "sequence": 1043,
  "ros_stamp": "2026-08-30T04:30:00.123Z",
  "received_at": "2026-08-30T04:30:00.145Z",
  "source": "ros:/scan",
  "payload": {
    "source_frame": "laser_frame",
    "target_frame": "map",
    "points": [[1.2, 0.4], [1.24, 0.47]],
    "valid_count": 182,
    "range_min_m": 0.05,
    "range_max_m": 12.0,
    "transform_applied": true,
    "transform_error": null
  },
  "health": {
    "source_id": "scan",
    "state": "live",
    "last_ros_stamp": "2026-08-30T04:30:00.123Z",
    "last_received_at": "2026-08-30T04:30:00.145Z",
    "age_ms": 22,
    "stale_after_ms": 1000,
    "reason": null
  }
}
```

地图事件的 payload 使用 `encoding: "png"`、`image_base64` 和 `content_hash`。地图变更不应导致每条 scan 重复发送完整栅格。

服务端 sequence 单调递增。客户端发现 sequence 不连续时不自行补帧或拼接错误状态，而是请求 bootstrap 并等待新的 snapshot。

### 8.2 Camera 通道

相机使用独立路径：

```text
WS /ws/camera/{camera_id}
```

每帧先发送 JSON metadata，再发送对应的 JPEG 二进制帧：

```json
{
  "schema_version": 1,
  "type": "camera_frame",
  "camera_id": "front",
  "width": 640,
  "height": 480,
  "encoding": "jpeg",
  "ros_stamp": "2026-08-30T04:30:00.123Z",
  "received_at": "2026-08-30T04:30:00.145Z",
  "sequence": 81
}
```

相机连接建立但没有有效图像帧时仍报告源不可用或过期；浏览器不得用默认图片填充。

### 8.3 慢客户端和断线

每个客户端队列有界。`mapping_status`、`motion_allowed`、`source_health` 和最新 snapshot 优先；旧 scan/camera 帧可丢弃。慢客户端不得阻塞 ROS executor、其他客户端或 mapping 命令。

前端重连退避为 `0.5s → 1s → 2s → 4s → 8s → 15s`，上限 15 秒。重连成功后先请求 bootstrap、覆盖旧缓存，再等待新的近期事件，不能把旧缓存继续标为 live。

## 9. 数据健康与错误语义

每个数据源独立使用以下状态：

- `live`：已收到近期且可解析的数据。
- `stale`：曾收到有效数据，但超过后端声明的 freshness 阈值。
- `unavailable`：未配置、未发现话题、没有发布者或从未收到有效数据。
- `error`：收到数据但解析、编码或 TF 转换失败。

标准错误码包括：

```text
source_unavailable
source_stale
transform_error
decode_error
transport_error
command_rejected
bridge_error
schema_error
```

错误对象至少包含 `code`、`message`、`source`、`occurred_at` 和 `recoverable`。前端同时显示文字、颜色和最后接收时间，颜色不是唯一状态表达方式。

建议默认 freshness 阈值（实际值通过 bootstrap 返回并可配置）：

- mapping status：2 秒。
- scan：1 秒。
- filtered odometry：1 秒。
- IMU：1 秒。
- map：5 秒，建图期间仍以实际更新和后端阈值为准。
- camera：2 秒。
- cmd_vel：1 秒。

ROS 时间戳未来、倒退或异常时，可写入诊断，但不能把消息直接标记为正常 live。数据过期不会触发前端速度命令；最终速度仍由 safety gate 控制。

## 10. 前端控制台设计

### 10.1 状态来源

`App.vue` 只消费真实 API/socket 状态，不创建或推进运行时状态。启动顺序为：

1. 请求 `/api/v1/console/bootstrap`。
2. 建立 `/ws/telemetry`。
3. 按 schema 校验并归并事件。
4. 等待真实数据后渲染 live 内容。
5. 断线期间保留最后真实画面，但显示断线和 stale 遮罩。

必须删除生产运行路径对 `createMockSnapshot` 和 `advanceMockRuntime` 的依赖。`mockWorld.ts` 如保留，只能作为测试夹具，不能被生产组件导入。

建议拆分为：

```text
API client
  ├─ bootstrap
  ├─ mapping commands
  └─ capability/source queries

Telemetry socket
  ├─ envelope validation
  ├─ sequence tracking
  ├─ reconnect/backoff
  └─ event dispatch

Console state
  ├─ latestMap
  ├─ latestScan
  ├─ latestRobotState
  ├─ latestMappingStatus
  ├─ sourceHealth
  └─ cameraStreamState
```

### 10.2 一屏布局

桌面基准视口为 `1280×720`，页面不滚动展示核心信息：

```text
┌──────────────────────────────────────────────────────────────┐
│ API/ROS｜建图｜运动锁｜急停｜数据源健康摘要                   │
├───────────────┬──────────────────────────────┬───────────────┤
│ 建图控制       │                              │ 摄像头         │
│ 会话/地图版本  │       真实地图 + 雷达         │ 真实图像/离线  │
│ 传感器状态     │       机器人位姿             │ 云台能力状态   │
│               │                              ├───────────────┤
│               │                              │ 实时遥测       │
├───────────────┴──────────────────────────────┴───────────────┤
│ 手动控制｜路径｜标签｜AI 配置｜事件/错误                      │
└──────────────────────────────────────────────────────────────┘
```

顶栏约 `44px`，底栏约 `48px`，左栏约 `220px`，右栏约 `280px`，地图占剩余空间且不低于宽度的一半。按钮紧凑但不低于 `32px`，所有图标有可访问名称。

地图使用真实 OccupancyGrid 栅格；青色点为真实 scan，机器人图标为真实 pose，黄色线仅在收到真实路径时显示。没有地图、scan 或 pose 时显示等待原因，不显示示例建筑、区域、routeLoop 或随机点。

### 10.3 建图交互

按钮由真实 `MappingSession` 驱动：

| 状态 | 操作 |
| --- | --- |
| `IDLE` | 开始建图 |
| `STARTING` | 启动中，禁止重复提交 |
| `MAPPING` | 暂停、保存、停止 |
| `PAUSED` | 继续、保存、停止 |
| `SAVING` | 保存中，禁止冲突操作 |
| `ERROR_RECOVERABLE` | 显示真实错误和可恢复操作 |

点击后前端进入请求中，等待 API 响应和状态事件。`409`、`503` 或 ROS 错误直接显示后端消息，不修改当前状态。保存需要用户提供地图名称，revision 和时间只显示真实响应。

### 10.4 数据源卡片

每个源显示状态、年龄、关键元数据和原因，例如：

```text
地图       LIVE       0.2 s
雷达       LIVE       0.1 s · 182 点
滤波里程计 LIVE      0.1 s
IMU        STALE      2.4 s
摄像头     UNAVAILABLE 未发现 ROS 图像发布者
电池       UNAVAILABLE 未配置真实来源
```

相机 `LIVE` 时显示后端 JPEG；`STALE` 保留最后真实帧并覆盖过期提示；`UNAVAILABLE/ERROR` 只显示文字原因。当前没有真实云台接口时，方向按钮必须禁用并说明“云台控制未接入”，不能只修改前端角度。

底部路径、标签、AI 入口可以打开面板，但阶段 A 中若能力未实现，面板只显示后端能力状态和未接入原因，不显示 seed task、seed label、假路径或假模型。

## 11. 配置

所有传输和源配置在后端/runtime 环境中管理，前端不硬编码：

```text
ROVER_CAMERA_IMAGE_TOPIC
ROVER_CAMERA_IMAGE_TYPE
ROVER_CAMERA_MAX_WIDTH
ROVER_CAMERA_JPEG_QUALITY
ROVER_TELEMETRY_SCAN_MAX_POINTS
ROVER_TELEMETRY_SCAN_MAX_HZ
ROVER_TELEMETRY_MAP_MAX_HZ
ROVER_TELEMETRY_STALE_AFTER_SECONDS
ROVER_TELEMETRY_TF_TIMEOUT_SECONDS
```

配置只控制真实来源、限频、编码和超时，不能声明不存在的 topic 为可用，也不能生成默认业务值。无认证部署至少限制监听地址和允许来源；控制命令继续走明确的 REST 路由，telemetry WebSocket 为只读。

## 12. 测试策略

### 12.1 后端单元测试

覆盖：

- `OccupancyGrid → MapSnapshot`，包括 origin yaw、未知值、阈值和 PNG 编码。
- `LaserScan → ScanSnapshot`，包括无效量程、角度、限点数和 TF 成功/失败。
- Odometry/TF → RobotSnapshot，确保 frame 不被伪装。
- Image/CompressedImage → JPEG 帧和不支持编码错误。
- source health 的 live/stale/unavailable/error 转换。
- ROS 时间戳未来、倒退和接收时间。
- map hash 去重、sequence 分配和 bootstrap 快照。
- 有界队列优先级与可丢弃事件。
- 配置校验、未配置相机和 bridge fail-fast。

### 12.2 API/集成测试

覆盖：

- bootstrap、sources、capabilities 路由。
- telemetry WebSocket 首次 snapshot、增量事件和 sequence。
- camera metadata + binary JPEG 帧。
- mapping 命令真实响应映射和失败状态。
- ROS bridge 不可用时返回 503 或 fail-fast。
- 不会静默退回 `InMemoryMappingBackend`。
- 相机 topic 未配置或类型不匹配时返回 unavailable。
- 慢客户端不阻塞关键事件和 mapping 命令。

### 12.3 前端测试

覆盖：

- 生产入口不导入 mockWorld。
- 空 bootstrap 显示 unavailable，不显示默认数值或图片。
- map/scan/pose 事件更新真实渲染状态。
- scan 坐标未转换时显示警告，不当作 map 坐标。
- mapping 状态驱动按钮，命令失败不篡改状态。
- WebSocket 断线、重连、sequence 缺口和 bootstrap resync。
- live/stale/error/unavailable 的文字和遮罩。
- 相机不可用时不创建 data URI。
- `1280×720` 下核心内容无需滚动。

## 13. 真机验收

离线测试通过后，在当前真机执行只读或低风险验证：

1. 验证 ROS graph、topic 类型和发布者数量。
2. 确认 `/map`、`/scan`、`/odometry/filtered`、`/imu/data` 的时间戳持续更新。
3. 确认 `/mapping/status` 和 `/mapping/motion_allowed` 可读取。
4. 探测配置相机 topic；没有真实 topic 时记录 unavailable 证据。
5. 启动 runtime，访问 bootstrap 和 telemetry WebSocket。
6. 打开控制台，确认地图、雷达、pose、mapping 状态来自真实 ROS。
7. 在不触碰 safety 输出的前提下停止一个非安全源，验证 stale/unavailable；恢复后验证 live。
8. 断开浏览器连接，确认 runtime、mapping 和 safety 不受影响。
9. 检查日志和构建产物，确认没有 mockWorld 生产运行时依赖。
10. 确认 systemd、官方硬件容器、micro-ROS agent 和安全速度拓扑未被本阶段改变。

阶段 A 不因“尚未接入相机”而伪报相机通过；验收报告应明确记录其真实状态。

## 14. 阶段 A 完成定义

只有全部条件满足才算阶段 A 完成：

- 后端、API、前端单元和集成测试通过。
- `App.vue` 运行路径不再导入或调用 `mockWorld.ts`。
- 没有 ROS 数据时相关区域显示真实 unavailable/stale/error。
- 真机 `/map` 能改变地图栅格画面。
- 真机 `/scan` 能改变雷达画面，并显示坐标转换状态。
- pose、mapping status、motion permission 和 `/cmd_vel` 展示来自真实 ROS。
- 建图按钮调用现有真实 mapping API 并反映真实状态机。
- WebSocket 断线、sequence 缺口和源过期均有可见反馈。
- 无相机 topic 时显示未接入原因，不伪造图像。
- 不影响现有 safety gate、systemd 和 runtime 启动拓扑。

## 15. 后续阶段接口边界

### 阶段 B：相机与云台

在本阶段 camera source health 和独立 camera WebSocket 基础上增加真实 camera inventory、云台命令/反馈 ROS action 或 service、方向状态和失败处理。云台按钮只有在 capabilities 声明真实命令接口后才启用。

### 阶段 C：路径与标签

在本阶段 map frame、origin、resolution 和 robot pose 基础上增加地图坐标编辑、路径校验/保存/取消/执行以及标签 CRUD。所有数据必须后端持久化并使用真实地图版本；没有导航接口时显示未接入。

### 阶段 D：AI 模型配置

增加 provider、endpoint、model、能力和凭据引用配置；密钥不得回传浏览器明文。AI 输出只能成为用户确认后的路径或任务建议，不能绕过 mapping state、navigation action 或 safety gate 直接控制底盘。
