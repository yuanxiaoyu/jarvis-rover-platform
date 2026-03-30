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

## 真实小车接入实施协议

下面这部分约定，用来指导后续把真实 ROS2 小车能力接到当前 Web 控制台中。

### 1. SLAM 建图与 Web 挂钩

ROS2 侧最少要持续提供：

- `nav_msgs/OccupancyGrid`
- `map_metadata`
- 当前定位位姿
- 建图状态：`idle | running | completed | failed`

API 侧需要把这些信息整理成前端可以直接消费的 `map.snapshot`：

- 地图边界
- 占据栅格
- 房间 / 区域多边形
- 墙体线段
- keepout / 虚拟墙
- 建图进度与状态

Web 侧只通过 `GET /api/map` 和 `system.snapshot` / `map.snapshot` 了解建图结果，不直接订阅 ROS2 话题。

### 2. 实时轨迹展示协议

真实小车运行时，轨迹不应由浏览器本地模拟，而应由后端统一下发。

ROS2 -> API:

- 当前位姿
- 历史轨迹点序列或最近轨迹窗口
- 当前规划路径
- 当前导航目标

API -> Web:

- `robot.pose`
- `mission.state`
- `map.snapshot` 中的当前路径 / 历史轨迹

Web 展示规则：

- 当前小车位置与朝向，始终以最新位姿为准
- 当前待执行路径与历史轨迹分层展示
- 当后端返回新的规划结果时，前端应覆盖本地预览路径

### 3. Web 路径规划协议

Web 中的右击目标点、自定义节点、返航等操作统一通过后端入队，不直接驱动底盘。

浏览器发起：

- 单目标导航：`POST /api/missions/navigate`
- 多节点导航：`POST /api/missions/navigate`，载荷中补 `waypoints`
- 返航：`POST /api/missions/navigate` 或专用 `return_home`

后端校验：

- 目标点是否位于可通行区域
- 路径是否穿越禁行区 / 虚拟墙
- 当前电量、定位状态、急停状态是否允许执行

后端执行：

- 单目标映射到 Nav2 `NavigateToPose`
- 多节点映射到 Nav2 `NavigateThroughPoses`

后端回流：

- 规划成功 / 失败
- 实际规划路径
- 任务状态：`queued | planned | executing | paused | completed | aborted`

### 4. Web 建模场景协议

Web 中的地图场景应明确区分三种状态：

- 未建图：只展示空态和建图入口
- 建图中：展示建图进度、当前扫描状态
- 建图完成：开放区域标签、虚拟墙、路径规划、轨迹展示

建图完成后，后端至少需要提供以下场景元素：

- 区域多边形
- 区域标签
- 墙体线段
- 虚拟墙
- 当前规划路径
- 历史轨迹
- 小车当前位置

这意味着后续无论前端使用 2D、2.5D 还是 three 场景，本质上都要消费同一份地图快照协议，而不是自己拼装一套局部状态。

## Payload 示例

下面给出几组建议直接采用的 payload 示例，方便后续接车时统一前后端字段命名。

### `system.snapshot`

```json
{
  "map": {
    "map_id": "house-floor-01",
    "name": "一层工作区",
    "mapping_status": "completed",
    "mapping_progress_pct": 100,
    "bounds": {
      "min": [0.0, 0.0],
      "max": [16.0, 13.2]
    },
    "zones": [
      {
        "id": "inspection-east",
        "name": "东侧巡检区",
        "category": "inspection",
        "polygon": [[8.6, 2.4], [16.0, 2.4], [16.0, 8.5], [8.6, 8.5]]
      }
    ],
    "region_labels": [
      {
        "id": "label-01",
        "name": "新增标签1",
        "zone_id": "inspection-east",
        "position": [12.4, 5.5]
      }
    ],
    "virtual_walls": [
      {
        "id": "wall-01",
        "name": "维护围栏",
        "start": [10.6, 9.2],
        "end": [14.8, 9.2],
        "enabled": true
      }
    ]
  },
  "runtime": {
    "robot_pose": {
      "x": 5.8,
      "y": 6.1,
      "yaw_rad": 1.57,
      "linear_velocity": 0.22,
      "angular_velocity": 0.03,
      "frame_id": "map",
      "stamp_ms": 1770000000000
    },
    "path": {
      "id": "path-01",
      "status": "executing",
      "destination": [12.4, 5.5],
      "algorithm": "nav2",
      "waypoints": [[5.8, 6.1], [8.2, 6.1], [12.4, 5.5]]
    },
    "mission": {
      "mode": "autonomy",
      "objective": "导航至东侧巡检区",
      "status_line": "正在执行路径"
    }
  }
}
```

### `map.snapshot`

```json
{
  "type": "map.snapshot",
  "payload": {
    "map_id": "house-floor-01",
    "mapping_status": "running",
    "mapping_progress_pct": 48,
    "bounds": {
      "min": [0.0, 0.0],
      "max": [16.0, 13.2]
    },
    "zones": [],
    "region_labels": [],
    "virtual_walls": []
  }
}
```

### `robot.pose`

```json
{
  "type": "robot.pose",
  "payload": {
    "x": 6.2,
    "y": 6.0,
    "yaw_rad": 1.41,
    "linear_velocity": 0.18,
    "angular_velocity": 0.02,
    "frame_id": "map",
    "stamp_ms": 1770000000123
  }
}
```

### `POST /api/missions/navigate`

单目标导航：

```json
{
  "type": "navigate_to_pose",
  "target_point": [12.4, 5.5],
  "frame_id": "map"
}
```

多节点导航：

```json
{
  "type": "navigate_through_poses",
  "frame_id": "map",
  "waypoints": [[6.0, 5.2], [7.8, 6.8]],
  "target_point": [12.4, 5.5]
}
```

建议响应：

```json
{
  "accepted": true,
  "mission_id": "mission-20260330-001",
  "path_id": "path-01",
  "status": "planned"
}
```

### `mission.state`

```json
{
  "type": "mission.state",
  "payload": {
    "mission_id": "mission-20260330-001",
    "status": "executing",
    "objective": "导航至东侧巡检区",
    "path_id": "path-01",
    "task_queue": [
      {
        "id": "task-navigation",
        "title": "导航至东侧巡检区",
        "status": "running",
        "progress_pct": 46
      }
    ]
  }
}
```

## 前后端字段对照表

下面这张表的目的，是减少后续接车时“前端叫一个名字，API 叫另一个名字，ROS2/后端模型又叫第三个名字”的对齐成本。

### 地图与区域字段

| 前端 TypeScript | API JSON 推荐字段 | 后端当前/建议模型 | 说明 |
|----------------|-------------------|------------------|------|
| `world.mapId` | `map_id` | `MapModel.map_id` | 地图唯一 ID |
| `world.mapName` | `name` | `MapModel.name` | 地图名称 |
| `world.bounds.min/max` | `bounds.min/max` | 建议新增到 `MapModel` | 地图世界坐标边界 |
| `world.zones[].id` | `zones[].id` | 当前 `Zone.zone_id`，建议统一成 `id` 对外输出 | 区域 ID |
| `world.zones[].name` | `zones[].name` | `Zone.name` | 区域名称 |
| `world.zones[].category` | `zones[].category` | 当前 `Zone.type`，建议 API 层做映射 | 区域类别 |
| `world.zones[].polygon` | `zones[].polygon` | 当前 `Zone.points`，建议 API 层转换成二维数组 | 区域多边形 |
| `world.regionLabels[]` | `region_labels[]` | 建议新增独立标签模型 | 区域标签集合 |
| `world.virtualWalls[]` | `virtual_walls[]` | 当前 `ZoneType.VIRTUAL_WALL` 或独立模型 | 虚拟墙集合 |
| `world.mapping.status` | `mapping_status` | 建议新增到 `MapModel` | 建图状态 |
| `world.mapping.progressPct` | `mapping_progress_pct` | 建议新增到 `MapModel` | 建图进度 |

### 运行时字段

| 前端 TypeScript | API JSON 推荐字段 | 后端当前/建议模型 | 说明 |
|----------------|-------------------|------------------|------|
| `runtime.robotPose.x/y` | `robot_pose.x/y` | 当前 `TelemetryPacket.pose`，建议扩展 yaw 和速度 | 小车位置 |
| `runtime.robotPose.yawRad` | `robot_pose.yaw_rad` | 建议新增到 `TelemetryPacket` | 小车朝向 |
| `runtime.robotPose.linearVelocity` | `robot_pose.linear_velocity` | 建议新增到 `TelemetryPacket` | 线速度 |
| `runtime.robotPose.angularVelocity` | `robot_pose.angular_velocity` | 建议新增到 `TelemetryPacket` | 角速度 |
| `runtime.path.id` | `path.id` | 建议由导航层生成 | 路径唯一 ID |
| `runtime.path.status` | `path.status` | 建议由导航层维护 | `idle/planned/executing/...` |
| `runtime.path.destination` | `path.destination` | 建议新增 | 当前导航终点 |
| `runtime.path.waypoints` | `path.waypoints` | 建议新增 | 当前路径点序列 |
| `runtime.path.algorithm` | `path.algorithm` | 建议新增 | 规划来源，如 `nav2` |
| `runtime.mission.mode` | `mission.mode` | `MissionState.mode` | 运行模式 |
| `runtime.mission.objective` | `mission.objective` | `MissionState.objective` | 当前任务目标 |
| `runtime.mission.statusLine` | `mission.status_line` | `MissionState.status_line` | 状态行文案 |
| `runtime.tasks[]` | `tasks[]` | 当前 `Task`，建议 API 层补前端友好字段 | 任务队列 |
| `runtime.voice.*` | `voice.*` | `VoiceSessionState` | 语音状态 |

### 遥测与感知字段

| 前端 TypeScript | API JSON 推荐字段 | 后端当前/建议模型 | 说明 |
|----------------|-------------------|------------------|------|
| `runtime.telemetry.batteryPercent` | `telemetry.battery_percent` | 当前 `SensorSnapshot.battery.percent`，建议 API 层归一化 | 电量 |
| `runtime.telemetry.cpuPercent` | `telemetry.cpu_percent` | 建议新增系统遥测模型 | CPU 占用 |
| `runtime.telemetry.temperatureC` | `telemetry.temperature_c` | 当前 `SensorSnapshot.temperature.board_c` / `motor_c`，建议归一化 | 温度 |
| `runtime.telemetry.networkRttMs` | `telemetry.network_rtt_ms` | 建议新增 API 层观测字段 | 网络时延 |
| `runtime.telemetry.localizationConfidence` | `telemetry.localization_confidence` | 建议新增定位质量字段 | 定位置信度 |
| `runtime.telemetry.motorCurrentA` | `telemetry.motor_current_a` | 建议新增底盘遥测字段 | 电机电流 |
| `runtime.lidar.points[]` | `lidar.points[]` | 当前 `LaserScan` 归一化结果 | 点云/雷达点 |
| `runtime.camera.frameUrl` | `camera.frame_url` | API 转发图像流地址 | 相机帧地址 |
| `runtime.camera.fps` | `camera.fps` | API 图像通道状态 | 相机帧率 |
| `runtime.camera.latencyMs` | `camera.latency_ms` | API 图像通道状态 | 相机时延 |

### 命名约束建议

为了减少前后端来回转换，建议统一遵守两条规则：

1. API 对外 JSON 一律使用 `snake_case`

- `map_id`
- `mapping_status`
- `robot_pose`
- `linear_velocity`

2. Web 内部 TypeScript 一律使用 `camelCase`

- `mapId`
- `mappingStatus`
- `robotPose`
- `linearVelocity`

后端模型可以保留现有 Python / Pydantic 风格，但对外返回给 Web 时，应在 API 层完成一次统一命名映射。

## 模型级对齐草案

下面给出一份推荐的“后端模型 -> 前端接口”对齐草案。目的不是要求当前仓库一次性重构完成，而是给后续接车时的模型演进提供目标形态。

### 1. 地图快照

后端建议模型：

```python
class MapSnapshotOut(BaseModel):
    map_id: str
    name: str
    mapping_status: Literal["unmapped", "scanning", "ready"]
    mapping_progress_pct: int
    bounds: dict[str, list[float]]
    zones: list[ZoneOut]
    region_labels: list[RegionLabelOut]
    virtual_walls: list[VirtualWallOut]
```

前端对应接口：

```ts
interface WorldModel {
  mapId: string
  mapName: string
  bounds: MapBounds
  zones: MapZone[]
  regionLabels: RegionLabel[]
  virtualWalls: VirtualWall[]
  mapping: MappingState
}
```

对齐建议：

- `map_id -> mapId`
- `name -> mapName`
- `mapping_status + mapping_progress_pct -> mapping`
- `region_labels -> regionLabels`
- `virtual_walls -> virtualWalls`

### 2. 区域

后端建议模型：

```python
class ZoneOut(BaseModel):
    id: str
    name: str
    category: Literal["lane", "room", "dock", "charging", "inspection", "restricted"]
    polygon: list[list[float]]
    label_anchor: list[float] | None = None
    selectable: bool = True
```

前端对应接口：

```ts
interface MapZone {
  id: string
  name: string
  category: 'lane' | 'room' | 'dock' | 'charging' | 'inspection' | 'restricted'
  polygon: Vec2[]
  labelAnchor?: Vec2
  selectable: boolean
}
```

当前后端已有 `Zone` 模型，但字段更偏底层 keepout / virtual wall 语义。建议后续由 API 层额外提供一个专门给 Web 用的 `ZoneOut` 结构，而不是直接把底层模型暴露给前端。

### 3. 区域标签

后端建议模型：

```python
class RegionLabelOut(BaseModel):
    id: str
    name: str
    zone_id: str | None = None
    position: list[float]
```

前端对应接口：

```ts
interface RegionLabel {
  id: string
  name: string
  position: Vec2
  zoneId: string | null
}
```

后续如果要支持多个标签、自由放置、重定位、删除，建议把它作为独立实体存储，而不是塞进 `Zone` 模型里。

### 4. 虚拟墙

后端建议模型：

```python
class VirtualWallOut(BaseModel):
    id: str
    name: str
    start: list[float]
    end: list[float]
    height: float
    enabled: bool
```

前端对应接口：

```ts
interface VirtualWall {
  id: string
  name: string
  start: Vec2
  end: Vec2
  height: number
  enabled: boolean
}
```

如果后端内部仍然把虚拟墙表示成 `ZoneType.VIRTUAL_WALL`，建议在 API 输出层再转换成上面的 Web 友好结构。

### 5. 小车位姿与路径

后端建议模型：

```python
class RobotPoseOut(BaseModel):
    x: float
    y: float
    yaw_rad: float
    linear_velocity: float
    angular_velocity: float
    frame_id: str
    stamp_ms: int

class PathStateOut(BaseModel):
    id: str
    status: Literal["idle", "planned", "executing", "paused", "completed", "aborted"]
    destination: list[float] | None = None
    algorithm: str
    last_updated_ms: int
    waypoints: list[list[float]]
```

前端对应接口：

```ts
interface RobotPose {
  x: number
  y: number
  yawRad: number
  linearVelocity: number
  angularVelocity: number
  frameId: string
  stampMs: number
}

interface PathState {
  id: string
  status: 'idle' | 'planned' | 'executing' | 'paused' | 'completed' | 'aborted'
  waypoints: Vec2[]
  destination: Vec2 | null
  algorithm: string
  lastUpdatedMs: number
}
```

### 6. 任务与任务状态

后端当前已有 `Task` 模型，建议后续对 Web 输出时补一层任务摘要：

```python
class TaskSummaryOut(BaseModel):
    id: str
    title: str
    status: Literal["queued", "running", "blocked", "done"]
    progress_pct: int
    eta_sec: int
```

前端对应接口：

```ts
interface TaskItem {
  id: string
  title: string
  status: 'queued' | 'running' | 'blocked' | 'done'
  progressPct: number
  etaSec: number
}
```

注意这里的状态值和当前后端 `TaskStatus` 枚举并不完全相同，API 层需要做一次映射，而不是直接把底层 `pending/completed/failed` 原样推给前端。

### 7. 总快照

后端建议模型：

```python
class RoverSnapshotOut(BaseModel):
    world: MapSnapshotOut
    runtime: RuntimeSnapshotOut
```

前端对应接口：

```ts
interface RoverSnapshot {
  world: WorldModel
  runtime: RuntimeState
}
```

这会让 Web 初始化和 WebSocket 增量更新都围绕同一份结构展开，后续 mock 数据替换成真实快照时成本最低。

## 当前仓库差距清单

下面这部分不是“理想设计”，而是基于当前仓库现状整理出的差距清单。后续真机接入时，可以直接按这张表逐项补齐。

### 1. 前端已经具备的结构

当前 `apps/web/src/types/contract.ts` 已经具备一套相对完整的前端目标结构，包括：

- `WorldModel`
- `MapZone`
- `RegionLabel`
- `VirtualWall`
- `RobotPose`
- `PathState`
- `TaskItem`
- `RuntimeState`
- `RoverSnapshot`

这意味着前端协议目标已经基本成形，后续主要工作并不是重新设计前端字段，而是让后端真实输出与它对齐。

### 2. 后端当前已经具备的基础

当前 `services/api/app/models` 中已经有这些基础模型：

- `MapModel`
- `MissionState`
- `Task`
- `TelemetryPacket`
- `SensorSnapshot`
- `VoiceSessionState`
- `Zone`
- `SystemSnapshot`

这些模型足够支撑最小控制链路，但它们目前更偏“后端内部状态”或“底层桥接语义”，还不是直接给 Web 用的最终输出模型。

### 3. 主要字段差距

#### 地图层

当前缺失或不完整的字段包括：

- `MapModel` 没有 `bounds`
- `MapModel` 没有 `mapping_status`
- `MapModel` 没有 `mapping_progress_pct`
- `MapModel` 没有 `zones`
- `MapModel` 没有 `region_labels`
- `MapModel` 没有 `virtual_walls`

结论：

后端需要新增一个专门面向 Web 的 `MapSnapshotOut` 或等效输出层，不能只直接返回当前 `MapModel`。

#### 区域层

当前后端 `Zone` 模型字段是：

- `zone_id`
- `name`
- `type`
- `points`
- `nav2_keepout_enabled`
- `nav2_virtual_wall_enabled`

而前端需要的是：

- `id`
- `name`
- `category`
- `polygon`
- `labelAnchor`
- `selectable`

结论：

API 层至少需要做一次“区域语义映射”，把底层 keepout / virtual wall 模型输出成浏览器可视化区域模型。

#### 标签层

当前后端没有独立的 `RegionLabel` 模型。

这意味着下面这些能力目前都缺：

- 多标签保存
- 标签独立增删改
- 标签自由放置
- 标签与区域的弱关联

结论：

后续如果要支持真实的标签编辑，不建议把标签塞进 `Zone`，而应该新增独立持久化模型。

#### 路径与轨迹层

当前后端模型里没有前端所需的 `PathStateOut` 或等价结构，缺少：

- 路径 ID
- 规划状态 `planned/executing/...`
- `destination`
- `algorithm`
- `waypoints`
- 历史轨迹点

结论：

后端需要补一层“导航状态输出模型”，把 Nav2 的 action 状态、当前路径和历史轨迹收敛成 Web 可用结构。

#### 遥测层

当前 `TelemetryPacket` 只有：

- `pose`
- `speed_mps`
- `active_task_id`
- `sensor`

而前端还需要：

- `yaw_rad`
- `linear_velocity`
- `angular_velocity`
- `battery_percent`
- `cpu_percent`
- `temperature_c`
- `network_rtt_ms`
- `localization_confidence`
- `motor_current_a`

结论：

后端需要补一层统一遥测聚合，而不是只把现有 `SensorSnapshot` 原样回传。

### 4. 交互能力差距

当前前端已经做了这些交互原型：

- 右击规划目标点
- 自定义节点规划
- 虚拟墙绘制
- 区域标签放置 / 删除 / 改名
- 轨迹与当前路径展示

但后端目前还没有对应的真实保存和执行闭环：

- 标签保存接口缺失
- 虚拟墙保存接口还只是规划态定义
- 多节点路径接口缺少明确 payload
- 真实轨迹回流缺失
- 真实 Nav2 路径覆盖前端预演路径的机制缺失

### 5. 推荐的补齐顺序

建议按下面顺序补齐，而不是并行改所有层：

1. 补 `MapSnapshotOut`

- 先把地图边界、区域、多边形、虚拟墙、建图状态统一输出

2. 补 `RobotPoseOut + PathStateOut`

- 先把当前位置、当前路径、规划状态统一输出

3. 补 `TaskSummaryOut`

- 让任务队列和导航状态能稳定回流到前端

4. 补 `RegionLabelOut + 标签保存接口`

- 让前端标签编辑真正落到服务端

5. 补 `VirtualWallOut + 保存接口`

- 让虚拟墙不仅能画，还能进入后端 / ROS2 keepout 体系

6. 最后补 WebSocket 增量事件

- `map.snapshot`
- `robot.pose`
- `mission.state`
- `robot.telemetry`

### 6. 一句话结论

当前仓库已经把“前端目标协议”和“后端基础模型”都铺好了，但两者之间还缺一层明确的 Web 输出模型与状态映射层。后续接车最核心的工作，不是重写 UI，而是把 ROS2 / API / Web 之间的这层映射补完整。

## 实施 Backlog

下面这张表可以直接作为后续接车时的工程任务清单使用。

| 优先级 | 任务 | 后端模型/接口 | WebSocket 事件 | 前端替换点 | ROS2 / 系统依赖 |
|--------|------|---------------|----------------|------------|-----------------|
| P0 | 输出真实地图快照 | 新增 `MapSnapshotOut`，扩展 `GET /api/map`、`GET /api/system/snapshot` | `map.snapshot` | 用真实 `world` 替换 `createMockWorldModel()` | `slam_toolbox`、`OccupancyGrid`、地图元数据 |
| P0 | 输出真实小车位姿 | 新增 `RobotPoseOut`，扩展系统快照 | `robot.pose` | 用真实 `runtime.robotPose` 替换前端本地推进 | `odom`、`tf`、定位模块 |
| P0 | 输出真实导航路径 | 新增 `PathStateOut`，扩展导航接口响应 | `mission.state` 或 `map.snapshot` 中带路径 | 用后端真实路径替换 `buildNavigationPath()` 的长期前端预演 | Nav2 `NavigateToPose` / `NavigateThroughPoses` |
| P0 | 单目标导航闭环 | `POST /api/missions/navigate` 支持目标点请求体 | `mission.state` | 右击规划后由后端回传 `planned/executing` 状态 | Nav2 action client |
| P1 | 多节点路径导航 | 扩展 `POST /api/missions/navigate` 支持 `waypoints` | `mission.state` | 节点规划模式改用后端真实规划结果 | Nav2 多目标导航 |
| P1 | 标签持久化 | 新增 `RegionLabelOut`、标签增删改接口 | `map.snapshot` | 替换当前前端本地标签数组 | 数据库存储或地图 sidecar 存储 |
| P1 | 虚拟墙持久化 | 新增 `VirtualWallOut`、虚拟墙保存接口 | `map.snapshot` | 替换当前前端本地虚拟墙数组 | keepout filter / costmap 配置 |
| P1 | 历史轨迹回流 | 新增轨迹序列输出字段 | `robot.pose` 或独立 `robot.trace` | 用真实历史轨迹替换前端临时线段 | `odom` 缓存、轨迹聚合 |
| P1 | 建图进度回流 | 扩展 `MapSnapshotOut.mapping_status/progress` | `map.snapshot` | 替换当前前端扫描进度 mock | SLAM 会话状态机 |
| P2 | 统一任务摘要 | 新增 `TaskSummaryOut` | `mission.state`、`tasks.updated` | 用后端任务队列替换前端 `TaskItem` mock | 任务编排层 |
| P2 | 统一遥测聚合 | 新增 `TelemetryOut` | `robot.telemetry` | 用真实 CPU/温度/电流/定位质量替换 mock | 系统监控、底盘遥测、网络探测 |
| P2 | 相机通道真实化 | 扩展 `camera.frame` / 静态快照元数据 | `camera.frame` | 替换当前占位图 `frameUrl` | 摄像头驱动、MJPEG/WebRTC |
| P2 | 语音状态真实化 | 扩展 `voice.state` | `voice.state` | 替换当前语音状态 mock | ASR / 唤醒词 / TTS 适配 |
| P3 | AI 指令真实编排 | 扩展 `POST /api/missions/ai-command` | `mission.state` | 让对话历史真正反映 AI 任务执行 | `rover_ai_bridge` |
| P3 | 垃圾巡检联动 | 扩展垃圾检测与任务状态更新 | `mission.state`、`alerts.active` | 将垃圾上报融入真实任务流 | `rover_vision`、OpenClaw |

### 建议的 Sprint 切分

如果按最小风险切分，建议分成 4 个阶段：

1. 地图与位姿

- `MapSnapshotOut`
- `RobotPoseOut`
- `map.snapshot`
- `robot.pose`

2. 导航与轨迹

- 单目标导航
- 多节点导航
- 路径状态
- 历史轨迹

3. 编辑与持久化

- 区域标签
- 虚拟墙
- keepout 同步

4. 体验与扩展

- 任务摘要
- 语音状态
- 相机通道
- AI 指令
- 垃圾巡检

### 每项任务的验收标准

每个 backlog 项建议至少满足这 3 条验收标准：

1. RViz / ROS2 视角正确

- ROS2 内部状态、路径和地图是真实可用的，不只是前端显示正确

2. API / WebSocket 视角正确

- `curl` 或 WebSocket 抓包能看到字段名、状态值和 payload 结构符合约定

3. Web 视角正确

- 浏览器看到的地图、路径、轨迹、标签、虚拟墙与后端状态一致，没有双重状态源

这样做的好处是，每个任务都能同时在机器人、接口层和前端三侧验证，不会出现“前端看起来对了，但底层根本没跑起来”的假完成状态。

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
