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
- 面向树莓派部署的本地“贾维斯”唤醒词、ASR、TTS 与开放式 AI 对话能力

## 目录结构

- `apps/web`：基于 Vue 3 的 Web 控制台与 3D 空间视图
- `services/api`：FastAPI 网关，提供 REST / WebSocket / 静态资源托管，以及受保护的语音 gateway
- `services/voice`：宿主机本地语音服务（ALSA、openWakeWord、sherpa-onnx，以及可选 Pocket TTS）
- `ros2_ws/src`：ROS2 包，覆盖启动、建图、导航、安全、AI、语音等模块
- `docker`：容器镜像与运行脚本
- `docs`：架构、接口约定、硬件与运行策略文档

## 运行策略

开发阶段使用多容器拆分，便于快速迭代。

在树莓派生产环境中优先控制资源占用：

- 一个主 `ROS2/API` 容器承载机器人主运行时
- 前端静态资源由 API 容器直接托管
- 语音模型按配置启用，而不是默认常驻推理
- 语音服务独立于 ROS/API 容器运行，只通过 loopback 和独立 token 交换有界文本与状态
- 默认不启用语音。`ROVER_TTS_ENGINE=pocket_tts` 时，Pocket TTS checkpoint 与 voice state 必须由部署者放入仓库外的受保护目录；中文播报可使用 `ROVER_TTS_ENGINE=sherpa_vits`，只需提供本地 `model.onnx`、`lexicon.txt` 和 `tokens.txt`。

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
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

3. 宿主机安装语音服务（默认不启用）

```bash
cd services/voice
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[runtime]'
cd ../..
sudo ./scripts/check_voice_prerequisites.sh
```

`ROVER_WAKEWORD_MODEL` 可指向 openWakeWord `.onnx` 文件，或包含
`tokens.txt`、encoder/decoder/joiner 与 `keywords.txt` 的 sherpa-onnx KWS 目录；
后者用于本地中文“贾维斯”关键词检测。对开放词表模型，应将
`ROVER_WAKEWORD_KEYWORDS_FILE` 指向由 `text2token` 生成且包含
`@贾维斯` 的专用词表；服务会优先使用它，并保留本地 ASR 的短语兜底。
ASR 使用本地流式 sherpa-onnx Zipformer；TTS 根据
`ROVER_TTS_ENGINE` 选择 Pocket TTS 或中文 sherpa VITS，均只从本地路径加载，不会自动下载模型或
把原始音频上传到网络。缺少真实设备、模型、gateway 或 provider 时，系统报告
`unavailable`，不会用模拟回复或静态音频填充。

唤醒词识别后会先用本地 TTS 播放“我在，请说。”作为反馈；用户在反馈音播放期间讲话会立即打断它并开始录音。
可通过 `ROVER_VOICE_WAKE_ACK_TEXT` 修改这句提示。

树莓派 5 建议优先使用 `ROVER_TTS_ENGINE=sherpa_vits` 的量化中文模型；播放管线会在
模型生成首个音频块后立即把 PCM 写入同一个 ALSA `aplay` 流，避免等待整段回复。若使用
Pocket TTS，`ROVER_TTS_CONFIG`（省略时为 `ROVER_TTS_MODEL_DIR/config.yaml`）必须是只引用
本地 `tokenizer.model` 和 checkpoint 的配置文件，`ROVER_TTS_CHECKPOINT` 与 voice state
也必须位于本地受保护目录。两种引擎都使用 CPU、有界音频和可中断播放，不会在运行时访问网络。

4. 面向树莓派的 Docker 运行方式

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

大模型配置通过同一个 `.env` 注入 API 容器。`ROVER_AI_MAX_OUTPUT_TOKENS` 会按所选协议映射为
Chat Completions 的 `max_tokens`，或 Responses 的 `max_output_tokens`；不要在语音服务中重复配置
大模型 key。

当前 Docker 运行方式假定宿主机上已经存在真实硬件设备，例如 `/dev/myserial` 和 `/dev/rplidar`。

## 目标功能

- 基于 SLAM 与序列化地图输出的 TOF 雷达一键建图
- 从占据栅格地图重建可交互的 3D 空间视图
- 支持房间/区域目标与虚拟墙的 Web 任务控制台
- 摄像头、雷达、位姿、任务状态的实时流式展示
- AI 命令到任务编排与执行的桥接层
- 浏览器与小车之间的麦克风语音对话能力
- 结合 Nav2 keepout filter 的本地避障与安全层
- 基于树莓派算力约束的 `贾维斯` 唤醒词、中文 ASR、本地中文 TTS 播报链路；会话支持开放式闲聊与趣味问答

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
