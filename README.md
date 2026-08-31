# 贾维斯小车控制台

本地语音部署和故障行为见 [docs/voice-runtime-runbook.md](docs/voice-runtime-runbook.md)。宿主机服务使用 openWakeWord、sherpa-onnx 与 Piper，并通过受保护的 `ROVER_AI_API_KEY` 与 `ROVER_VOICE_GATEWAY_TOKEN` 配置运行。

`Jarvis Rover Console` 是一套面向 Yahboom `MicroROS-Pi5` 小车的 `ROS2 + Docker + Web` 控制系统。

本项目围绕 Yahboom 为 `MicroROS-Pi5` 平台公开的硬件能力和课程范围进行设计，核心前提包括：

- 以 `ROS2 Humble` 运行在树莓派 5 上；
- 基于 `ESP32` 的 micro-ROS 运动控制板；
- 用于建图与导航的 `MS200` TOF 雷达；
- 安装在双自由度云台上的 2MP 摄像头；
- 官方课程中已覆盖 Docker 运行方式。

本仓库不是 Yahboom 课程源码的镜像，而是在相同硬件假设之上增加一层面向产品使用的应用层，用来实现：

- TOF 雷达一键建图；
- 2D 地图与轻量重建 3D 空间视图；
- 基于 Web 的区域编辑与虚拟墙设置；
- 摄像头与雷达的实时叠加展示；
- 浏览器输入 AI 指令并下发到小车执行；
- Web 端与小车之间的语音交互；
- 面向树莓派部署的本地唤醒词、ASR、TTS 适配。

## 当前实现范围

阶段 0～1 的实现重点是**稳定遥控建图和可恢复建图会话**：

- 统一真实 Yahboom 接口和 `ROS_DOMAIN_ID=20`；
- SLAM Toolbox `online_async` 主链路；
- 建图会话的 start/pause/resume/save/load/stop；
- pose graph、PGM/YAML 地图和校验 manifest 的版本化保存；
- 搬运到已知位置后通过人工初始位姿恢复；
- 安全速度 gate、急停和 watchdog；
- FastAPI mapping-session REST API；
- ROS 图、QoS、频率、时间戳和资源基线诊断工具。

沿墙自主探索、完整房间语义、完整 Web 3D 控制台和语音任务编排在阶段 2～4 中独立交付，不会绕过阶段 1 的安全和会话接口。

## 目录结构

- `apps/web`：基于 Vue 3 的 Web 控制台与 3D 空间视图；
- `services/api`：FastAPI 网关，提供 REST / WebSocket / 静态资源托管；
- `ros2_ws/src`：ROS2 包，覆盖启动、建图、导航、安全、AI、语音等模块；
- `docker`：容器镜像与运行脚本；
- `scripts`：ROS 图检查和真机基线工具；
- `docs`：架构、接口、硬件、运行和阶段 0～1 手册。

## 真机 Docker 运行

真实 Yahboom 硬件容器和项目 runtime 必须处于同一个 ROS Domain。当前真机使用 `ROS_DOMAIN_ID=20`。

### 现有官方容器作为硬件层

```bash
cp .env.example .env
sh ~/ros2_humble.sh
# 官方容器只运行底盘、雷达、IMU、里程计和输入设备
# 不要在其中再启动官方 EKF、Cartographer 或 GMapping

# 注意：未重映射的官方手柄会发布 /cmd_vel，与项目安全层最终 /cmd_vel 冲突。
# 阶段 1 建图请使用 Compose hardware profile，或将官方 Supervisor 的
# /root/run_handle.sh 替换为 docker/vendor/run_handle.sh，使手柄输出 /cmd_vel_teleop。

docker compose build rover-runtime
docker compose up -d rover-runtime
```

### Compose hardware profile

```bash
cp .env.example .env
docker compose build rover-runtime yahboom-hardware
docker compose --profile hardware --profile micro-ros-agent up -d
```

这两种拓扑只能二选一。禁止同时运行两个 Yahboom 容器、两个 micro-ROS agent、多个 EKF、多个 `map -> odom` publisher 或多个 SLAM 后端。详细命令、状态机和故障恢复见 [`docs/phase-0-1-runbook.md`](docs/phase-0-1-runbook.md)。

## 真机部署与 systemd 开机自启动

本节是当前 Yahboom 真机的可复现部署流程。采用**官方 Yahboom 硬件容器 + 项目 `rover-runtime`** 拓扑：官方脚本/Supervisor 负责唯一的底盘、雷达、IMU、里程计和手柄硬件层；systemd 只托管项目软件 runtime。所有容器使用 `ROS_DOMAIN_ID=20`。

**不要同时运行两个 Yahboom 硬件容器、两个 micro-ROS agent、官方 EKF 与项目 EKF，或 Cartographer/GMapping 与 SLAM Toolbox。**本服务不会启动 `yahboom-hardware` 或 `micro-ros-agent` profile，也不接管串口。

### 1. 准备并确认配置

在包含本次代码的 checkout 中执行（若使用 worktree，`git rev-parse` 会返回该 worktree 的绝对路径）：

```bash
cd /home/jarvis-rover-platform
REPO_DIR="$(git rev-parse --show-toplevel)"

# 只在 .env 不存在时创建，绝不覆盖已有配置
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
fi

# 编辑 .env，至少确认：
# ROS_DOMAIN_ID=20
# ROVER_ROS_BRIDGE_ENABLED=true
# ROVER_ROS_BRIDGE_REQUIRED=true
# COMPOSE_PROFILES 不设置或保持为空
```

### 2. 先启动唯一官方硬件层

```bash
sh ~/ros2_humble.sh
```

官方容器内只运行底盘、雷达、IMU、里程计和已经重映射到 `/cmd_vel_teleop` 的手柄。不要在该容器中再次启动 `yahboomcar_bringup_launch.py`、官方 EKF、Cartographer 或 GMapping。若官方手柄仍直接发布 `/cmd_vel`，必须先按 `docker/vendor/run_handle.sh` 完成 remap；否则 graph check 会拒绝进入建图。

**不要再运行第二份 `sh ~/ros2_humble.sh`，也不要在本拓扑执行 `docker compose --profile hardware ...` 或 `--profile micro-ros-agent ...`。**如果选择 Compose hardware profile，必须改用另一套互斥部署方案，不能与本节服务同时使用。

### 3. 部署并启用开机服务

安装脚本会先验证 `.env`、Domain 20、Docker Compose 默认服务集合和 runtime 镜像，再安装 `/etc/systemd/system/jarvis-rover-runtime.service`。它不会调用 mapping `start`/`resume`，不会发送非零 `/cmd_vel`，也不会删除地图：

```bash
cd "$REPO_DIR"
make runtime-prerequisites
sudo bash scripts/install_rover_runtime_service.sh

systemctl is-enabled jarvis-rover-runtime.service
systemctl is-active jarvis-rover-runtime.service
systemctl status jarvis-rover-runtime.service --no-pager
```

开机后服务只保持 `rover-runtime` 运行；mapping 初始状态必须是 `idle`，`motion_allowed=false`，等待人工显式操作。服务等待 `/mapping/command` ready 后才启动 API，避免 required ROS bridge 在启动竞态中误判不可用。

### 4. 查看日志与执行无运动 smoke test

```bash
journalctl -u jarvis-rover-runtime.service -f
make runtime-smoke

# 也可以直接执行只读诊断
bash scripts/verify_ros_graph.sh
bash scripts/measure_ros_baseline.sh
```

`runtime-smoke` 只检查 API health、mapping `idle`/锁定、ROS graph、节点/服务列表、baseline 和 `/cmd_vel` 零速样本；它不会调用 `/api/v1/mapping/start` 或 `/resume`。证据保存到 `data/evidence/<UTC timestamp>/`。Smoke 通过只表示软件启动和初始安全状态满足契约，不表示 30 分钟建图验收通过。

### 5. 服务生命周期、停止和回滚

```bash
systemctl is-enabled jarvis-rover-runtime.service
systemctl is-active jarvis-rover-runtime.service
journalctl -u jarvis-rover-runtime.service --since boot

# 只重启软件 runtime；不停止官方硬件容器、不删除地图
sudo systemctl restart jarvis-rover-runtime.service
sudo systemctl stop jarvis-rover-runtime.service
sudo systemctl disable jarvis-rover-runtime.service

# 卸载 unit；不会 docker compose down，也不会删除 data/、地图、volume 或镜像
sudo bash scripts/uninstall_rover_runtime_service.sh
```

安装时如果发现同名但非本项目管理的 unit，会先备份为 `/etc/systemd/system/jarvis-rover-runtime.service.bak.<UTC timestamp>`，然后拒绝静默覆盖；恢复备份前必须人工检查。若本项目 unit 启动失败，应先查看 `systemctl status` 和 `journalctl`，不要通过关闭 `ROVER_ROS_BRIDGE_REQUIRED`、启用 fake backend 或绕过安全 gate 来“修复”。

当前这台真机观测到的局域网地址为 `192.168.2.81`；DHCP 变化后请用 `hostname -I` 重新查询，不要把该地址写死到客户端配置。

访问地址：

- 本机 health：<http://127.0.0.1:8000/health>
- 本机 mapping 状态：<http://127.0.0.1:8000/api/v1/mapping>
- 局域网 health：<http://192.168.2.81:8000/health>
- 局域网 mapping 状态：<http://192.168.2.81:8000/api/v1/mapping>
- 局域网 telemetry WebSocket：`ws://192.168.2.81:8000/ws/telemetry`

API 绑定在 `0.0.0.0:8000`；只有在同一受信任局域网中访问，生产环境仍应在反向代理或防火墙层增加认证与访问控制。


| 层级 | 证据 | 含义 |
| --- | --- | --- |
| 配置 | `make runtime-prerequisites`、`docker compose config` | Domain/profile/Compose 配置可部署 |
| 服务 | `systemctl is-active`、`health` JSON | runtime 和 API 存活 |
| ROS 图 | `verify_ros_graph.sh` 输出 | 唯一 EKF、SLAM、TF 和 control graph 满足契约 |
| 初始安全 | `mapping-status.json`、`/cmd_vel` 零速样本 | 开机没有自动运动 |
| 资源基线 | `data/evidence/.../baseline.json` | 实际频率、QoS、CPU、内存、温度；不能把启用 SLAM 的结果称为 no-SLAM baseline |
| 阶段 1 | 30 分钟、五次 pause/resume、save/load、搬运恢复、故障注入日志 | 真机建图出口验收，不能由构建或 smoke test 代替 |

完成阶段 1 前，必须按 [`docs/phase-0-1-runbook.md`](docs/phase-0-1-runbook.md) 在安全场地人工确认运动测试。不要将敏感日志、设备信息或 `.env` 上传到公共仓库。

## 本地开发

1. 前端预览：

```bash
cd apps/web
npm install
npm run dev
```

2. API fake backend：

```bash
cd services/api
python3 -m pip install -e ".[dev]"
ROVER_ROS_BRIDGE_ENABLED=false uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

3. ROS workspace（在 ROS 2 Humble 环境中）：

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

## 诊断与测试

```bash
make runtime-test
make ros-graph-check
make ros-baseline
```

在 runtime 容器中也可以运行：

```bash
docker exec jarvis-rover-runtime bash /workspace/scripts/verify_ros_graph.sh
docker exec jarvis-rover-runtime bash /workspace/scripts/measure_ros_baseline.sh
```

`make ros-baseline` 需要 ROS 图正在运行；它会将传感器频率、时间戳年龄、QoS、TF、节点和 Pi 资源写入 `data/baselines/`。代码测试通过不等于真实小车验收通过，阶段出口还需要按 runbook 完成 30 分钟性能和故障注入测试。

## 核心接口

ROS 运行时的阶段 1 接口包括：

- `/scan`、`/odom_raw`、`/imu`：Yahboom 硬件层输入；
- `/odom`、`/map`：唯一定位和 SLAM 输出；
- `/mapping/status`、`/mapping/motion_allowed`、`/mapping/diagnostics`；
- `/mapping/command`：会话生命周期 service；
- `/cmd_vel`：安全层唯一最终速度输出。

API 接口为：

- `GET /api/v1/mapping`；
- `POST /api/v1/mapping/start`、`pause`、`resume`、`save`、`load`、`stop`；
- `WS /ws/telemetry`：当前是轻量 mock/遥测流，不是原始 ROS 地图流。

## 目标路线

- 阶段 0：真机接口、TF、QoS、资源基线；
- 阶段 1：稳定建图、暂停恢复、持久化和安全门控；
- 阶段 2：沿房间边缘的前沿探索与 Nav2 任务执行；
- 阶段 3：2D 操作闭环和轻量 3D 重建可视化；
- 阶段 4：结构化语音意图、多步骤任务和对讲控制。

## 上游参考

- Yahboom 学习页：<https://www.yahboom.com/study/MicroROS-Pi5>
- Yahboom 产品页：<https://category.yahboom.net/products/microros-pi5>
- Nav2 keepout filter 教程：<https://docs.nav2.org/tutorials/docs/navigation2_with_keepout_filter.html>
- SLAM Toolbox 文档：<https://docs.ros.org/en/ros2_packages/humble/api/slam_toolbox/index.html>
- sherpa-onnx 文档：<https://k2-fsa.github.io/sherpa/onnx/>

## 当前限制

真正部署前仍需在目标真机上记录和校验：

- 实际 ROS2 话题频率、时间戳和 QoS；
- MS200 雷达有效范围和外参；
- `base_footprint`、`base_link`、`laser_frame`、`imu_frame` 的 TF 关系；
- 串口设备名和唯一 micro-ROS agent；
- SLAM Toolbox 服务名与 Pi 5 CPU/温度余量；
- 30 分钟建图、暂停恢复、保存加载和异常停车结果。
