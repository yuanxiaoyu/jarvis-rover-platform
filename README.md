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
- 基于 Web 的区域编辑与虚拟墙设置
- 摄像头与雷达的实时叠加展示
- 浏览器输入 AI 指令并下发到小车执行
- Web 端与小车之间的语音交互
- 面向树莓派部署的本地唤醒词、ASR、TTS 预留能力

## 目录结构

- `apps/web`：基于 Vue 3 的 Web 控制台与 3D 空间视图
- `services/api`：FastAPI 网关，提供 REST / WebSocket / 静态资源托管
- `ros2_ws/src`：ROS2 包，覆盖启动、建图、导航、安全、AI、语音等模块
- `docker`：容器镜像与运行脚本
- `docs`：架构、接口约定、硬件与运行策略文档

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
- 结合 Nav2 keepout filter 的本地避障与安全层
- 适配树莓派算力约束的 `贾维斯` 唤醒词、ASR、TTS 预留方案
- 语音触发的整屋垃圾扫描与 OpenClaw 飞书上报，确保发现垃圾时自动拍照、记录位置并通过企业通知推送

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
