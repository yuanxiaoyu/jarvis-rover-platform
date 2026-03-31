# 贾维斯小车控制台

`Jarvis Rover Console` 是一套面向 Yahboom `MicroROS-Pi5` 小车的 `ROS2 + Docker + Web` 控制系统。

本项目围绕 Yahboom 为 `MicroROS-Pi5` 平台公开的硬件能力和课程范围进行设计，核心前提包括：

- 以 `ROS2 Humble` 运行在树莓派 5 上
- 基于 `ESP32` 的 micro-ROS 运动控制板
- 用于建图与导航的 `MS200` TOF 雷达
- 安装在双自由度云台上的 2MP 摄像头
- 官方课程中已覆盖 Docker 运行方式

本仓库并不是 Yahboom 课程源码的镜像，而是在相同硬件假设之上，额外构建一层更适合产品化的应用层，用来实现：

- TOF 雷达一键建图
- 2D + 3D 空间可视化
- 未建模工作区的一键全屋扫描空态提示
- 基于 Web 的区域编辑与虚拟墙设置
- 地图右键导航、实时轨迹展示与自动避障路径预览
- 摄像头与雷达的实时叠加展示
- 浏览器输入 AI 指令并下发到小车执行
- Web 端与小车之间的语音交互
- 紧凑的一屏式 AI 对话历史窗口
- 面向树莓派部署的本地唤醒词、ASR、TTS 预留能力

## 目录结构

- `apps/web`：基于 Vue 3 的 Web 控制台与 3D 空间视图
- `services/api`：FastAPI 网关，提供 REST / WebSocket / 静态资源托管
- `ros2_ws/src`：ROS2 包，覆盖启动、建图、导航、安全、AI、语音等模块
- `docker`：容器镜像与运行脚本
- `docs`：架构、接口约定、硬件与运行策略文档，以及真实 ROS 小车接入计划

### 文档导航

建议按下面顺序阅读文档：

- [docs/architecture.md](/Users/yuanxiaoyu/Desktop/plan/docs/architecture.md)：理解整体系统分层、职责边界和落地顺序
- [docs/integration-contract.md](/Users/yuanxiaoyu/Desktop/plan/docs/integration-contract.md)：查看 Web / API / ROS2 的协议、payload、字段对照和 backlog
- [docs/ros-integration-plan.md](/Users/yuanxiaoyu/Desktop/plan/docs/ros-integration-plan.md)：按里程碑推进真实小车接入
- [docs/pi-runtime-profile.md](/Users/yuanxiaoyu/Desktop/plan/docs/pi-runtime-profile.md)：树莓派运行资源策略

## 运行策略

开发阶段使用多容器拆分，便于快速迭代。

在树莓派生产环境中优先控制资源占用：

- 一个主 `ROS2/API` 容器承载机器人主运行时
- 前端静态资源由 API 容器直接托管
- 语音模型按配置启用，而不是默认常驻推理

## 快速开始

1. 本地启动前端预览

```bash
cd apps/web
npm install
npm run dev
```

2. 本地启动 API

```bash
cd services/api
python3 -m pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

3. 面向树莓派的 Docker 运行方式

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

当前 Docker 运行方式假定宿主机上已经存在真实硬件设备，例如 `/dev/myserial` 和 `/dev/rplidar`。

## 目标功能

- 基于 SLAM 与序列化地图输出的 TOF 雷达一键建图
- 从占据栅格地图重建可交互的 3D 空间视图
- 支持房间/区域目标与虚拟墙的 Web 任务控制台
- 摄像头、雷达、位姿、任务状态的实时流式展示
- AI 命令到任务编排与执行的桥接层
- 浏览器与小车之间的麦克风语音对话能力
- 区域标签的增、删、改与地图内标签展示
- 地图上两点绘制虚拟墙，并参与路径避让
- 固定俯视地图视角，不允许旋转地图角度
- 任务队列、区域与虚拟墙以 ICON 弹窗管理
- 小车状态、运行控制与相机画面以浮动 HUD 方式叠加在地图区
- 结合 Nav2 keepout filter 的本地避障与安全层
- 适配树莓派算力约束的 `贾维斯` 唤醒词、ASR、TTS 预留方案
- 语音触发的整屋垃圾扫描与 OpenClaw 飞书上报，确保发现垃圾时自动拍照、记录位置并通过企业通知推送

### 当前 Web 控制台交互

当前 `apps/web` 的控制台原型已经按单屏操作台重排，核心交互如下：

- 工作区未建模时，地图区域保持为空，并显示 ICON 提示和“一键全屋扫描”入口
- 启动扫描后，会模拟小车执行全屋自动避障扫描，建模完成后自动生成区域、标签和虚拟墙编辑上下文
- 地图固定为俯视角，不再允许旋转；操作者可直接右键地图下发目标点
- 右键目标点会触发一条带虚拟墙避让的导航轨迹，小车位姿会沿该轨迹自动推进
- 区域标签支持增、删、改，新增标签可绑定到已建模区域并直接叠加在地图上
- 虚拟墙支持在弹窗中启停、改名、删除，也支持回到地图上通过两点绘制新的隔离线
- 任务队列与“区域/虚拟墙”不再长期占用侧边栏，而是通过 ICON 弹窗打开
- 小车状态、运行控制、相机画面与 AI 对话历史都改为紧凑浮层，保证地图始终是主视图

### 后续接入 ROS 小车的技术栈结合方式

当前仓库的 Web 控制台已经把地图交互、区域标签、虚拟墙、路径规划和轨迹展示这几个产品层能力预演出来。后续接入真实 ROS2 小车时，建议按下面的方式把技术栈与本项目结合起来：

1. `SLAM + Nav2` 与 Web 挂钩

- 建图阶段由 `slam_toolbox` 或兼容 SLAM 节点持续产出 `OccupancyGrid`、`map_metadata` 和机器人位姿。
- `rover_mapping` 负责把这些 ROS2 话题整理成前端可消费的地图快照，包括房间区域、墙体线段、可通行区和地图边界。
- `rover_navigation` 负责接收 Web 下发的目标点、节点路径或区域目标，再统一转成 Nav2 `NavigateToPose` / `NavigateThroughPoses` 请求。
- `services/api` 作为中间层，对浏览器隐藏 ROS2 话题细节，对外只暴露 REST / WebSocket 的地图、任务和遥测协议。

2. 实时展示小车运行轨迹

- 真实小车运行时，`/odom`、`/tf`、定位结果和 Nav2 当前路径应持续回流到 API。
- API 通过 WebSocket 将当前位置、历史轨迹点、当前规划路径和任务状态推送给前端。
- 前端不应自己“猜测”轨迹，而应以 ROS2 回传的位姿序列为准，把轨迹折线、当前位置和朝向叠加到地图上。

3. 在 Web 中直观进行路径规划

- 浏览器侧的右击目标点、自定义节点、虚拟墙绘制都只是交互入口，最终应由后端做合法性校验。
- API 收到目标点后，需要校验目标是否落在可通行区域内，是否穿越 keepout 区，是否需要重规划。
- 对于“节点规划模式”，建议直接映射到 Nav2 的多目标导航能力，让 Web 负责收集节点，ROS2 负责实际路径求解和执行。
- 前端展示的路径应优先使用后端返回的真实规划结果，而不是长期停留在前端 mock 路径。

4. 在 Web 中体现建模场景

- 建图未完成时，Web 应展示空态和建模进度，而不是展示伪造好的房间。
- 建图完成后，`rover_mapping` 输出的墙体、多边形区域、语义标签、虚拟墙和可通行边界应同步映射为可交互的场景元素。
- 如果后续继续采用当前的 2.5D 工作区视图，建议保留“墙体 + 地板 + 阴影 + 路径 + 标签”的表达方式，让操作员能直观看到建模结果和导航关系。
- 区域标签、虚拟墙、路径节点等编辑动作，都应当在保存后回写到 API / ROS2 侧，而不是只留在浏览器本地状态。

一条更稳妥的落地原则是：Web 负责交互与可视化，API 负责协议收敛与权限校验，ROS2 负责建图、定位、规划和执行。这样后续无论接 Yahboom 原生话题、`slam_toolbox` 还是 Nav2，都不需要把浏览器逻辑直接塞进机器人节点里。

### 真实小车接入清单

如果后续要把当前原型真正接到 ROS2 小车上，建议按下面顺序推进：

1. 硬件与话题盘点

- 确认底盘控制、雷达、摄像头、IMU、里程计、`tf`、`odom`、`map` 的真实话题名
- 确认串口设备名、波特率、Docker 设备映射和宿主机权限
- 在真机上先用 `ros2 topic list`、`ros2 topic echo`、`rviz2` 验证底层数据是通的

2. 接通建图链路

- 落地 `slam_toolbox` 或等效 SLAM 节点，稳定产出 `OccupancyGrid`
- 在 `rover_mapping` 中补地图快照导出逻辑，把占据栅格转换成前端可用的边界、墙体和区域
- 让 API 提供“未建图 / 建图中 / 已建图”三态，并把建图进度推给 Web

3. 接通 Nav2 导航链路

- 在 `rover_navigation` 中把 Web 的目标点、节点路径、返航请求统一转成 Nav2 action
- 把虚拟墙和禁行区转换成 keepout filter / costmap 约束
- 浏览器右击规划、节点规划和返航，都应该最终落到真实的 Nav2 规划与执行结果

4. 接通实时轨迹与遥测

- 将位姿、速度、电量、网络时延、任务状态通过 API / WebSocket 持续广播
- 前端的轨迹折线、小车位置、当前路径和历史路径都基于后端回传数据刷新
- 不再让前端长期使用 mock 推进逻辑作为真实状态来源

5. 接通 Web 场景编辑

- 区域标签、虚拟墙、自定义节点等编辑动作需要能保存到服务端
- 服务端保存后再同步回 ROS2，保证 Web、API、Nav2 看到的是同一份地图编辑结果
- 删除标签、删除虚拟墙、路径重规划这类动作都要能在真机上闭环

6. 做联合验证

- 在 RViz 和 Web 中同时核对地图、位姿、路径和 keepout 是否一致
- 验证“建图 -> 右击规划 -> 点击执行 -> 轨迹展示 -> 标签编辑 -> 虚拟墙重规划”整条闭环
- 补急停、返航、任务中断恢复、弱网、重复建图等异常场景测试

7. 做性能与上线准备

- 树莓派上关闭不必要的持续渲染和高频推流，优先保导航和建图主链路
- 评估前端静态资源、WebSocket 频率、图像帧率、视觉算法负载
- 固化 Docker 启动参数、环境变量、健康检查和日志采集方式

可以把这份清单当作后续真机联调的最小实施路线。先打通第 1 到第 4 项，再做编辑与体验层能力，风险会更低。

### 垃圾扫描与 OpenClaw 上报

对运营者来说，理想的流程是：对着麦克风说“贾维斯，请帮我扫描整个房屋，发现有垃圾请拍照告诉我”，系统便会把该指令交给 AI/任务桥接层，触发一次全宅扫描任务。一旦视觉、雷达或语义模型在任意房间发现垃圾，就会拍摄当前视野，将定位信息、任务状态与图片交给后端的 `OpenClaw` 上报组件，由它再通过绑定的飞书机器人/应用把结果推送到运维组。

当前仓库已经补齐的接口链路如下：

- `POST /api/v1/voice/command`：识别“整屋扫描 + 垃圾拍照上报”语音意图
- `POST /api/v1/missions/whole-home-garbage-scan`：直接创建整屋垃圾巡检任务
- `POST /api/v1/garbage/detections`：由视觉/语义检测链路回灌垃圾发现结果，并按配置自动上报 OpenClaw

ROS2 侧现在新增了 `rover_vision` 包，提供一个 YOLO 类垃圾检测节点：它会订阅相机图像，轮询当前是否存在运行中的 `whole_home_scan` 任务，命中垃圾类标签后将抓拍图片保存到本地，再调用 `POST /api/v1/garbage/detections` 触发 OpenClaw/飞书上报。

如果采用 TACO 数据集，当前默认配置已经切到 TACO 风格：默认权重路径为 `/workspace/models/yolo/taco_pi_best.pt`，并支持通过 `label_map_csv` 读取 TACO 官方那种 `source_label,target_label` 映射表。这样你既可以用 60 个原始细类模型，也可以用官方推荐的 `map_10.csv`、`map_17.csv` 这类合并类别方案。

为了兼容树莓派运行，`rover_vision` 还新增了 Pi 轻量参数：

- `pi_mode: true`
- `frame_stride: 6`
- `max_image_dim: 640`
- `model_input_size: 640`

这套默认值的目标是降低 Pi5 上的 CPU/GPU 压力，优先保证“能持续巡检并及时抓拍上报”。

YOLO 检测默认通过 `ultralytics` 后端加载 `/workspace/models/yolo/yolov8n.pt`，发现对象后会把带注释框的图片和 metadata 写入 `capture_dir`（默认 `/tmp/rover_captures`），并把 `capture_base_url` 合成的访问地址随 payload 发给 API。想要把图片对外发布，可在容器里把 `capture_dir` 挂载到一个简单的静态服务器或 nginx 目录，并在 `vision.yaml` 中把 `capture_base_url` 指向对应的前缀。所有关键参数（`min_confidence`、`report_cooldown_seconds`、`allowed_labels`、`save_annotated_capture`）都可以在 `ros2_ws/src/rover_vision/params/vision.yaml` 里调节。

这样既能保持树莓派侧的低延迟扫房，又能把垃圾发现结果及时同步到协作群。使用前请在 `.env` 中配置 `ROVER_OPENCLAW_WEBHOOK_URL`，并在机器人环境安装 `ultralytics`、`pillow`、`numpy`。主启动默认关闭视觉检测，需要在 ROS2 bringup 时显式打开 `use_garbage_detection:=true`。

## 上游参考

- Yahboom 学习页：<https://www.yahboom.com/study/MicroROS-Pi5>
- Yahboom 产品页：<https://category.yahboom.net/products/microros-pi5>
- Nav2 keepout filter 教程：<https://docs.nav2.org/tutorials/docs/navigation2_with_keepout_filter.html>
- SLAM Toolbox 文档：<https://docs.ros.org/en/ros2_packages/humble/api/slam_toolbox/index.html>
- sherpa-onnx 文档：<https://k2-fsa.github.io/sherpa/onnx/>

## 当前状态

本仓库当前提供的是一套可继续扩展的自定义开发骨架。真正接入 Yahboom 实物小车前，仍需要在真机上校验：

- 实际 ROS2 话题名
- 串口设备名
- TF 坐标关系
- 最终启动链路与 Docker 设备映射
