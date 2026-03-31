# ROS 小车接入计划

## 目标

把当前仓库里的 Web 控制台、API 网关和 ROS2 包，从 mock 演示状态推进到“可接真实 Yahboom 小车联调”的状态。

这份计划只关心一件事：让真实 `SLAM + Nav2 + Web` 形成闭环。

闭环标准：

- Web 能展示真实建图结果
- Web 能展示真实小车位姿和历史轨迹
- Web 的目标点 / 节点规划能驱动真实 Nav2
- Web 中的虚拟墙和标签能保存并回流

## 范围

本计划覆盖：

- `ros2_ws/src`
- `services/api`
- `apps/web`
- `docker`
- `docs`

本计划不覆盖：

- 外观设计的大幅重做
- 语音模型选型细节
- 垃圾识别模型效果优化
- 生产部署平台自动化

## 前置条件

开始之前先确认这些条件成立：

1. 真机可稳定运行 `ROS2 Humble`
2. 雷达、相机、底盘控制、`odom`、`tf` 话题已经可读
3. Docker 能访问真实串口和设备
4. 至少能在 RViz 中看到地图或位姿

如果这四条里任何一条不成立，不要先改 Web。先修底层。

## 环境变量清单

建议在真正接车前，把下面这些环境变量统一收敛并记录到部署说明中：

| 变量 | 作用 | 建议来源 |
|------|------|----------|
| `ROS_DOMAIN_ID` | ROS2 域隔离 | 机器人运行时配置 |
| `MICROROS_SERIAL_DEVICE` | micro-ROS 控制板串口设备 | 真机设备清单 |
| `MICROROS_SERIAL_BAUD` | micro-ROS 串口波特率 | 控制板说明书 / 实测 |
| `RPLIDAR_DEVICE` | 雷达设备节点 | 真机设备清单 |
| `ROVER_TELEMETRY_INTERVAL_SECONDS` | API / WebSocket 遥测推送频率 | 平台性能策略 |
| `ROVER_OPENCLAW_WEBHOOK_URL` | 垃圾发现上报地址 | 运维配置 |
| `JARVIS_ENABLE_WAKE_WORD` | 是否启用唤醒词 | 语音部署策略 |
| `JARVIS_ENABLE_ASR` | 是否启用语音识别 | 语音部署策略 |
| `JARVIS_ENABLE_TTS` | 是否启用语音合成 | 语音部署策略 |

建议规则：

- 所有真机相关环境变量都进入 `.env.example`
- 所有部署环境都保留一份真实值清单
- 不要把设备路径和 webhook 地址硬编码进代码

## 里程碑

### M0. 底层通路打通

目标：

- 真机 ROS2 话题、串口、设备映射可用

任务：

- 确认真实串口名、雷达设备名、相机设备名
- 校验 `docker compose` 的设备映射与权限
- 在真机上记录真实话题名、frame 名和 action 名
- 补一份真机环境变量模板

交付物：

- 一份真实设备清单
- 一份真实 ROS2 话题清单
- 一套可启动的真机 Docker 参数

验收：

- `ros2 topic list` 可看到底盘、雷达、相机、定位相关话题
- `docker compose up` 后主运行时容器不因设备缺失退出

建议输出模板：

```text
设备清单
- micro-ROS 串口：
- 雷达设备：
- 摄像头设备：

ROS2 话题清单
- /map:
- /odom:
- /tf:
- /scan:
- /camera/image_raw:
```

### M1. 建图结果进入 Web

目标：

- Web 不再依赖 mock 地图，能展示真实建图状态和地图快照

任务：

- 在 `rover_mapping` 中整理 `OccupancyGrid`、地图边界、墙体线段、区域多边形
- 在 API 中新增 `MapSnapshotOut`
- 为 `GET /api/map` 和 `system.snapshot` 输出真实地图快照
- Web 用真实 `world` 数据替换 `createMockWorldModel()`

交付物：

- 真实地图快照输出模型
- Web 中的未建图 / 建图中 / 已建图三态

验收：

- 未建图时 Web 显示空态
- 建图中时 Web 显示真实进度
- 建图完成后 Web 中出现真实区域和边界

### M2. 导航与轨迹闭环

目标：

- Web 的目标点 / 节点路径能驱动真实 Nav2，且路径与轨迹来自后端

任务：

- 在 `rover_navigation` 中接入 Nav2 单目标导航
- 扩展为多节点导航
- API 输出 `RobotPoseOut`、`PathStateOut`
- Web 用真实 `robot_pose`、`path`、历史轨迹替换本地推进逻辑

交付物：

- 单目标导航闭环
- 多节点导航闭环
- 历史轨迹回流

验收：

- 右击目标点后，Web 显示真实规划路径
- 点击执行后，小车真实移动
- Web 中历史轨迹与 RViz 中路径一致

### M3. 地图编辑持久化

目标：

- 标签、虚拟墙和路径节点编辑不再停留在浏览器本地

任务：

- 新增 `RegionLabelOut` 和标签保存接口
- 新增 `VirtualWallOut` 和虚拟墙保存接口
- 将虚拟墙转换成 Nav2 keepout / costmap 约束
- 标签和虚拟墙保存后回流到 Web 和 ROS2

交付物：

- 标签增删改查接口
- 虚拟墙增删改查接口
- keepout 同步机制

验收：

- 删除标签后，刷新页面不会恢复
- 删除虚拟墙后，规划路径会变化
- keepout 与 Web 展示一致

### M4. 体验层接实车状态

目标：

- Web 控制台主要面板都改用真实状态

任务：

- 任务队列改用真实 `TaskSummaryOut`
- 设备状态改用真实遥测
- 相机区改用真实视频通道 / 帧地址
- 语音状态改用真实语音链路

交付物：

- 真实任务队列
- 真实设备状态
- 真实相机状态
- 真实语音状态

验收：

- Web 不再依赖固定 mock 文案
- 刷新页面后，状态能从后端恢复

## 里程碑执行表

| 里程碑 | 建议负责人 | 主要输出文件 | 建议测试命令 | 风险级别 | 主要依赖 |
|--------|------------|--------------|--------------|----------|----------|
| M0 | ROS2 / 运维 | `compose.yaml`、`.env`、`docker/entrypoint.sh`、设备清单文档 | `docker compose up`, `ros2 topic list`, `ros2 topic echo /tf` | 高 | 真机设备、串口权限、Docker 设备映射 |
| M1 | ROS2 + API | `ros2_ws/src/rover_mapping/*`, `services/api/app/models/map.py`, `services/api/app/routers/map.py` | `ros2 topic echo /map`, `curl /api/map`, `curl /api/system/snapshot` | 高 | `slam_toolbox`, 真实 `OccupancyGrid`, 地图边界重建 |
| M2 | ROS2 + API + Web | `ros2_ws/src/rover_navigation/*`, `services/api/app/models/telemetry.py`, `apps/web/src/App.vue`, `apps/web/src/lib/roverScene.ts` | Nav2 action 调用、`curl /api/system/snapshot`, 浏览器右击规划与执行 | 高 | Nav2、位姿回流、路径输出 |
| M3 | API + Web + ROS2 Safety | `services/api/app/models/zone.py`, 新增标签/虚拟墙接口, `apps/web/src/App.vue` | 标签保存/删除、虚拟墙保存、刷新页面后校验、路径重规划 | 中 | keepout filter、地图持久化、API 状态缓存 |
| M4 | API + Web | `services/api/app/models/system.py`, 任务/遥测/语音输出层, `apps/web/src/types/contract.ts` | WebSocket 抓包、相机联调、任务状态刷新、语音状态验证 | 中 | 任务编排层、相机通道、语音桥接 |

说明：

- `建议负责人` 不是强制的人名，而是建议的主责模块。
- `主要输出文件` 表示该里程碑完成时，最可能被修改的代码位置。
- `风险级别` 的判断标准是：是否依赖真机、是否跨多层、是否容易返工。

## 推荐验证命令

为了让每个里程碑都能快速自测，建议统一保留下面这组命令：

### ROS2 侧

```bash
ros2 topic list
ros2 topic echo /map
ros2 topic echo /odom
ros2 topic echo /tf
ros2 action list
```

### API 侧

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/map
curl http://127.0.0.1:8000/api/system/snapshot
```

### Web 侧

```bash
cd apps/web
npm run build
```

如果接入 WebSocket 调试，建议额外保留一份抓包脚本或最小测试客户端，验证：

- `map.snapshot`
- `robot.pose`
- `mission.state`
- `robot.telemetry`

这四类事件是否按协议持续输出。

## 话题盘点模板

建议在第一次接车时就补一份真实话题盘点表，放在项目文档或部署笔记里：

| 能力 | 真实话题 / action / service | 备注 |
|------|-----------------------------|------|
| 地图 |  |  |
| 地图元数据 |  |  |
| 里程计 |  |  |
| TF |  |  |
| 雷达 |  |  |
| 相机 |  |  |
| 底盘控制 |  |  |
| Nav2 单目标 |  |  |
| Nav2 多节点 |  |  |
| 急停 / 安全状态 |  |  |

这张表必须先补。没有真实话题盘点，后续所有 API / Web 适配都容易返工。

## 依赖关系

里程碑之间存在明确依赖关系：

- M1 依赖 M0
- M2 依赖 M1
- M3 依赖 M1 和 M2
- M4 依赖 M2

不建议跳过依赖直接推进后面的工作。尤其是：

- 没有真实地图快照，不要先做标签持久化
- 没有真实路径输出，不要先做复杂的节点规划体验
- 没有真实位姿回流，不要先优化轨迹动画

## 交付完成定义

建议把“完成”分成三层，而不是只看代码是否提交：

1. 代码完成

- 对应模块代码已提交
- 单元测试或构建通过

2. 接口完成

- `curl` / WebSocket 抓包能看到约定字段
- 字段名与 `integration-contract.md` 一致

3. 真机完成

- RViz 侧正确
- Web 侧正确
- 真机动作正确

只有第三层完成，才应该视为该里程碑真正完成。

## 联调记录模板

每次联调建议留一份最小记录，避免重复踩坑：

```markdown
# 联调记录

日期：
负责人：
环境：
- 机器人：
- Docker 镜像：
- 分支：

## 本次目标
- 

## 实际验证
- [ ] RViz 地图正常
- [ ] Web 地图正常
- [ ] 目标点规划正常
- [ ] 执行动作正常
- [ ] 轨迹回流正常

## 问题
- 

## 下一步
- 
```

## 上线前检查清单

在准备把真机版本交给业务或现场演示前，建议至少完成：

- [ ] `docker compose` 能稳定启动主运行时
- [ ] 地图建图状态真实可用
- [ ] 右击目标点能规划并执行
- [ ] 自定义节点路径能规划并执行
- [ ] 虚拟墙保存后能影响规划结果
- [ ] 标签编辑刷新后仍然存在
- [ ] Web 中轨迹与 RViz 一致
- [ ] 相机区能显示真实通道状态
- [ ] 弱网或断流时 Web 能显示错误状态
- [ ] 急停 / 返航有明确状态回流

## 回滚策略

接车联调过程中，如果新链路引入不稳定，建议按下面顺序回滚，而不是整仓回退：

1. 先回滚 Web 到只读展示

- 禁止标签 / 虚拟墙写入
- 禁止路径执行，只保留查看

2. 再回滚 API 到只读快照模式

- 停止接收导航写操作
- 只保留 `GET /api/map`、`GET /api/system/snapshot`

3. 最后回滚 ROS2 新增能力

- 关闭自定义导航桥接
- 退回基础 SLAM / RViz 验证链路

原则是：优先保“能看状态”，再恢复“能发命令”。不要在问题未定位前继续把浏览器写操作直接打给底盘。

## 工作拆分

### ROS2 侧

- `rover_mapping`
  - 地图导出
  - 建图进度
  - 地图版本管理

- `rover_navigation`
  - 单目标导航
  - 多节点导航
  - 真实路径输出

- `rover_safety`
  - keepout
  - 虚拟墙
  - 急停 / 风险状态

### API 侧

- 输出模型统一
- REST 接口统一
- WebSocket 事件统一
- 状态缓存与快照聚合

### Web 侧

- 用真实快照替换 mock
- 用真实轨迹替换前端推进
- 标签 / 虚拟墙编辑改用后端持久化
- 控制台状态改用真实遥测

## 推荐顺序

最小风险顺序如下：

1. 先做 M0
2. 再做 M1
3. 再做 M2
4. 再做 M3
5. 最后做 M4

不要跳过 M1 直接做 M3。地图快照协议不稳定时，标签和虚拟墙保存很容易返工。

## 联调检查点

每个里程碑结束时都做三侧核对：

1. ROS2 / RViz 视角

- 地图是否真实
- 路径是否真实
- 小车位姿是否真实

2. API 视角

- `curl` / WebSocket 抓包是否拿到正确 payload
- 字段名是否与协议文档一致

3. Web 视角

- 地图是否与 RViz 对齐
- 路径是否与后端返回一致
- 编辑动作刷新后是否还能保留

## 风险点

- 真实 `tf` 关系不稳定，Web 会显示错位
- keepout 同步晚于路径规划，Web 和 Nav2 结果会不一致
- 多节点导航如果只在前端拼路径，实际执行会与展示偏离
- 相机 / 视觉链路过重，会拖累树莓派主导航能力

## 建议配套文档

这份计划应与下面三份文档一起使用：

- [README.md](/Users/yuanxiaoyu/Desktop/plan/README.md)
- [architecture.md](/Users/yuanxiaoyu/Desktop/plan/docs/architecture.md)
- [integration-contract.md](/Users/yuanxiaoyu/Desktop/plan/docs/integration-contract.md)
