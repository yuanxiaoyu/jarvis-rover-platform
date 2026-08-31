# 阶段 0～1 真机运行手册

本文档描述当前项目在 Yahboom MicroROS-Pi5 真机上的唯一支持拓扑、建图会话操作、诊断方法和阶段验收标准。

## 1. 真机接口基线

已确认的厂商运行时事实：

- 宿主机 `~/ros2_humble.sh` 启动 `yahboomtechnology/ros-humble:4.1.2`。
- 容器 `/root/1.sh` 启动 Supervisor；Supervisor 管理底盘和 IP 服务。
- `YB_Car_Node` 发布：
  - `/scan`：`sensor_msgs/msg/LaserScan`
  - `/odom_raw`：`nav_msgs/msg/Odometry`
  - `/imu`：`sensor_msgs/msg/Imu`
  - `/battery`
- `YB_Car_Node` 订阅 `/cmd_vel`。
- 官方手柄链路发布 `cmd_vel`；生产硬件 profile 会将其重映射为 `/cmd_vel_teleop`。
- 真机使用 `ROS_DOMAIN_ID=20`。
- `yahboomcar_bringup_launch.py` 只提供 IMU 滤波、官方 EKF、描述和部分 TF，不是完整建图入口。
- 官方 Cartographer/GMapping 入口仅用于单独对照：
  - `ros2 launch yahboomcar_nav map_cartographer_app_launch.xml`
  - `ros2 launch yahboomcar_nav map_gmapping_app_launch.xml`

## 2. 互斥启动拓扑

### 拓扑 A：现有 Yahboom 容器作为硬件层

适合继续使用厂商已经验证的串口、雷达和底盘驱动：

```bash
sh ~/ros2_humble.sh
# 在厂商容器中只运行底盘、雷达、IMU、里程计和手柄。
# 不要在该容器中启动 yahboomcar_bringup_launch.py、Cartographer 或 GMapping。

# 宿主机项目目录；仅在不存在时创建，避免覆盖真机配置
if [ ! -f .env ]; then cp .env.example .env; fi
docker compose build rover-runtime
docker compose up -d rover-runtime
```

项目 runtime 使用 Domain 20，负责 IMU 滤波、唯一项目 EKF、统一 TF、SLAM Toolbox、会话节点和安全速度层。

**注意：未修改的官方手柄 launch 会直接发布 `/cmd_vel`，不能与项目安全层的最终 `/cmd_vel` 同时运行。拓扑 A 只有在将官方 Supervisor 的 `run_handle.sh` 替换为本项目 `docker/vendor/run_handle.sh`（使手柄输出为 `/cmd_vel_teleop`）后才可用于阶段 1；否则它仅用于阶段 0 传感器基线。无法持久化这个替换时，请使用拓扑 B。**

### 拓扑 B：Compose hardware profile

适合希望将厂商启动包装成可复现镜像的部署：

```bash
cp .env.example .env
docker compose build rover-runtime yahboom-hardware
docker compose --profile hardware --profile micro-ros-agent up -d
```

不要再执行 `sh ~/ros2_humble.sh` 启动第二个 Yahboom 容器。若底盘控制板由别的 agent 提供，也不要启动 `micro-ros-agent` profile。

### 强制互斥规则

**禁止同时运行两个 Yahboom 硬件容器、两个 micro-ROS agent、官方 EKF 和项目 EKF，或 Cartographer/GMapping/SLAM Toolbox 中的多个 SLAM 后端。**重复发布 `cmd_vel`、`odom -> base_*` 或 `map -> odom` 会使控制和定位不确定，项目预检必须拒绝建图。

## 3. 项目运行时预期 ROS 图

建图运行后必须存在：

```text
YB_Car_Node
  /scan /odom_raw /imu  ───────┐
  /cmd_vel <───────────────────┘
                               │ Domain 20
rover_bringup mapping.launch.py │
  complementary_filter_node → /imu/data
  ekf_node                  → /odom, odom→base_footprint
  static TF                 → base_footprint→base_link→laser_frame
  async_slam_toolbox_node   → /map, map→odom
  mapping_node              → /mapping/status, /mapping/command
  safety_node               → final /cmd_vel
```

初始状态为 `IDLE`，`/mapping/motion_allowed` 为 `false`。即使 SLAM 进程已经启动，底盘也不会因为 runtime 启动而自动运动。

## 4. 诊断命令

在项目 runtime 容器中执行：

```bash
docker exec jarvis-rover-runtime bash /workspace/scripts/verify_ros_graph.sh
docker exec jarvis-rover-runtime bash /workspace/scripts/measure_ros_baseline.sh
docker exec jarvis-rover-runtime ros2 node list
docker exec jarvis-rover-runtime ros2 topic hz /scan
docker exec jarvis-rover-runtime ros2 topic hz /odom_raw
docker exec jarvis-rover-runtime ros2 topic hz /imu
docker exec jarvis-rover-runtime ros2 topic hz /cmd_vel
docker exec jarvis-rover-runtime ros2 topic echo /mapping/status --once
docker exec jarvis-rover-runtime ros2 service list | grep -E '/mapping/command|/slam_toolbox/'
```

`verify_ros_graph.sh` 检查 Domain 20、必需话题、唯一 EKF、唯一 SLAM、`pause_new_measurements`/`save_map`/`serialize_map`/`deserialize_map` 服务、唯一最终 `/cmd_vel` 和 TF 链；`clear_queue` 在当前 Humble async 节点中是可选优化，缺失时会给出 warning，不能把 warning 当作通过条件。

`measure_ros_baseline.sh` 将带频率、时间戳年龄、QoS、TF、节点和 CPU/内存/温度信息的 JSON 写入 `/workspace/data/baselines/`，该文件是阶段 0 的 no-SLAM 对照证据。

## 5. 建图会话 REST 操作

API 地址默认为 `http://127.0.0.1:8000`：

```bash
# 查看会话状态
curl -fsS http://127.0.0.1:8000/api/v1/mapping

# 创建会话；响应 202 表示命令已排队，不代表已经开始行驶
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/start \
  -H 'content-type: application/json' \
  -d '{"session_id":"bench-room"}'

# 暂停、继续、停止
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/pause
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/resume
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/stop

# 显式保存
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/save \
  -H 'content-type: application/json' \
  -d '{"map_name":"living-room"}'

# 搬运到地图已知自由位置后的加载；坐标单位为米，yaw 为弧度
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/load \
  -H 'content-type: application/json' \
  -d '{"session_id":"bench-room","map_name":"living-room","x":1.0,"y":1.0,"yaw":0.0,"match_type":2}'
```

状态值为：`idle`、`starting`、`mapping`、`paused`、`saving`、`error_recoverable`。

- HTTP `202`：命令已进入会话 worker；继续读取 `GET /api/v1/mapping` 直到状态稳定。
- HTTP `409`：当前状态不允许该命令。
- HTTP `422`：请求字段不合法，例如 session ID 越界或 load 缺少初始位姿。
- HTTP `503`：ROS bridge 或 mapping service 不可用。

## 6. 暂停、保存和搬运后恢复

### 原地暂停恢复

1. 调用 `pause`；安全层先输出零速度。
2. SLAM 调用 `pause_new_measurements` 和 `clear_queue`，丢弃暂停期间积压的旧扫描。
3. 启用 `checkpoint_on_pause` 时保存完整 revision。
4. 状态变为 `paused`，motion gate 保持关闭。
5. 调用 `resume`；重新执行传感器、TF、磁盘和竞争节点预检。
6. 预检和 SLAM 恢复成功后才回到 `mapping`。

### 保存格式

如需创建与当前地图完全隔离的新 session，先停止项目 runtime 再重新启动；同一 SLAM 进程不会在已有 revision 后隐式清空地图。

每个 session 的目录为：

```text
/workspace/data/maps/sessions/<session_id>/
├── current.json
└── revisions/<revision_id>/
    ├── map.pgm
    ├── map.yaml
    ├── posegraph
    ├── posegraph.data        # SLAM Toolbox companion; present when emitted
    └── manifest.json
```

manifest 包含 schema version、session/map/revision identity、UTC 创建时间、各文件 SHA-256/大小和运行时元数据。新 revision 先写 staging 目录，完成 fsync 和完整校验后原子替换 `current.json`；保存失败不会修改上一份 current revision。

### 搬运后恢复

1. 在 `mapping` 或 `paused` 状态先停止并保存。
2. 人工搬运小车到地图中的已知位置。
3. 从已知 free pixel 选择 `x/y/yaw`，禁止选择 occupied、unknown 或越界位置。
4. 调用 `load`。服务端和 mapping node 都校验 session、文件 hash、PGM 和初始位姿。
5. SLAM Toolbox 使用 `START_AT_GIVEN_POSE=2`（或明确请求的 `LOCALIZE_AT_POSE=3`）反序列化 pose graph。
6. 加载成功后状态保持 `paused`；人工确认后调用 `resume`。
7. 先低速短距离验证扫描匹配，再进行正常遥控。

任意恢复流程都不会自动发送运动指令。

## 7. 性能与资源基线

阶段 0 记录 no-SLAM 基线；阶段 1 在相同区域、相同硬件和相同控制速度下对比：

- 连续运行 30 分钟不 OOM、不发生 swap 抖动、不明显热降频；
- 最终控制指令 p99 间隔不超过 250 ms；
- 地图更新延迟 p95 不超过 2 s；
- `/scan`、`/odom_raw`、`/imu` 频率相对 no-SLAM 基线下降不超过 5%；
- 没有持续 TF lookup、message-filter 或时间戳错误。

建图期间以异步 SLAM 和有界队列为基线。RViz、rosbridge、摄像头推送和本地语音默认关闭或降级；若必须启用，先重新测量性能，不得降低安全控制优先级。

## 8. 故障处理和回退

- SLAM service 或进程失败：立即零速度，状态 `error_recoverable`。
- `/scan`、`/odom_raw`、`/imu` 过期或 TF 不可用：不允许 start/resume。
- 保存目录不可写或 hash 校验失败：保留旧 current，报告保存错误。
- API 断开：不接受新命令；安全 watchdog 继续工作。
- runtime 重启：保持 `idle`/待确认，不自动恢复行驶。
- 需要对照 Cartographer 时，先停止项目 SLAM Toolbox，再单独启动官方 Cartographer；对照结束后恢复项目 topology，并重新执行 graph check。

## 9. 当前环境已验证的阶段 0 事实

本轮在真实 Yahboom ROS 容器中已确认：

- 官方镜像：`yahboomtechnology/ros-humble:4.1.2`；
- `/scan` 类型为 `sensor_msgs/msg/LaserScan`，1 个 publisher，QoS `RELIABLE/VOLATILE`；
- `/odom_raw` 类型为 `nav_msgs/msg/Odometry`，1 个 publisher，QoS `RELIABLE/VOLATILE`；
- `/imu` 类型为 `sensor_msgs/msg/Imu`，1 个 publisher，QoS `RELIABLE/VOLATILE`；
- `/cmd_vel` 类型为 `geometry_msgs/msg/Twist`，当前官方手柄 publisher 为 `joy_ctrl`，底盘订阅者为 `YB_Car_Node`；
- 官方 `yahboomcar_joy_launch.py` 启动 `yahboom_joy` 和 `joy_node`；
- 官方 Humble SLAM Toolbox endpoint 包括 `pause_new_measurements`、`clear_queue`、`save_map`、`serialize_map`、`deserialize_map`；
- Humble `Pause.srv` 请求为空、响应为 `bool status`；`DeserializePoseGraph.srv` 的 `initial_pose` 为 `geometry_msgs/Pose2D`。

以下出口证据仍需在项目 runtime 构建并连接真机后执行，当前不能用设计目标代替实测：

- no-SLAM 频率/时间戳/CPU/内存/温度 JSON；
- 项目 SLAM Toolbox 的 30 分钟控制和地图延迟指标；
- 五次 pause/resume、save/load 和搬运恢复；
- 第二 publisher、SLAM service 故障、写盘失败和 runtime 重启的故障注入。

## 10. 本轮真机部署与无运动验收记录

本机当前局域网地址为 `192.168.2.81`（通过 `hostname -I` 观测；DHCP 变化后重新查询）。runtime API 访问地址为：

- `http://127.0.0.1:8000/health`
- `http://192.168.2.81:8000/health`
- `http://192.168.2.81:8000/api/v1/mapping`
- `ws://192.168.2.81:8000/ws/telemetry`

部署命令：

```bash
cd /home/jarvis-rover-platform
REPO_DIR="$(git rev-parse --show-toplevel)"
if [ ! -f "$REPO_DIR/.env" ]; then cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"; fi
# 编辑 .env，确认 ROS_DOMAIN_ID=20、required ROS bridge=true，COMPOSE_PROFILES 为空
sh ~/ros2_humble.sh
cd "$REPO_DIR"
make runtime-prerequisites
sudo bash scripts/install_rover_runtime_service.sh
make runtime-smoke
```

安装成功只表示 unit 已安装/启用和 runtime 已尝试运行；必须单独记录：

| 项目 | 实际值/路径 | 结果 |
| --- | --- | --- |
| 执行日期（UTC） | 2026-08-30T04:32:24Z（最终复核 04:33:37Z） | 已执行部署与无运动 smoke |
| checkout 路径 | `/home/jarvis-rover-platform/.claude/worktrees/stable-mapping-runtime` | 已记录 |
| `ROS_DOMAIN_ID` | `20` | 通过 |
| 官方硬件容器/镜像 | `tender_bartik` / `yahboomtechnology/ros-humble:4.1.2` (`sha256:9bde3b7690079d595f047ad43f81b37d4bea9e8d82256041c18f0ad721b1cdce`) | 运行中；手柄已 remap |
| runtime 镜像 digest | `stable-mapping-runtime-rover-runtime` (`sha256:6ffbabb859fa0eb5cb472f621cef85f373e866ab9de6dacf1d23138f445e0c5f`) | 已构建并运行 |
| systemd `is-enabled`/`is-active` | `enabled` / `active` | 通过 |
| smoke evidence 目录 | `data/evidence/20260830T043224Z/` | 已生成完整证据；最终复核使用同一运行实例 |
| 初始 mapping 状态 | `idle`、`motion_allowed=false` | 通过；见 `mapping-status.json` |
| `/cmd_vel` 初始样本 | linear/angular 六个分量均为 `0.0` | 通过；见 `cmd-vel-once.txt` |
| ROS graph check | `ROS graph checks passed.` | 通过；IDLE 时 `map -> odom` 缺失按设计给出 warning，实际 baseline 的 TF 查询成功 |
| baseline JSON | `data/evidence/20260830T043224Z/baseline.json` | 已记录 Domain 20、传感器、TF、资源；这是 runtime baseline，不是 no-SLAM 对照 |

### 部署后的只读检查

```bash
systemctl is-enabled jarvis-rover-runtime.service
systemctl is-active jarvis-rover-runtime.service
systemctl status jarvis-rover-runtime.service --no-pager
journalctl -u jarvis-rover-runtime.service -n 200 --no-pager
docker exec jarvis-rover-runtime bash /workspace/scripts/verify_ros_graph.sh
docker exec jarvis-rover-runtime bash /workspace/scripts/measure_ros_baseline.sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/v1/mapping
```

这些命令不执行 mapping mutation。若初始状态不是 `idle/false`、graph check 失败、ROS bridge 不可用或 `/cmd_vel` 非零，停止验收并记录日志；不要改成 fake backend 或绕过安全 gate。

### 服务停止、卸载和数据保留

```bash
sudo systemctl stop jarvis-rover-runtime.service
sudo systemctl disable jarvis-rover-runtime.service
sudo bash scripts/uninstall_rover_runtime_service.sh
```

上述操作只处理项目 systemd unit/runtime，不停止官方硬件容器，不执行 `docker compose down`，不删除 `data/`、地图 revisions、volume、镜像或备份 unit。重新安装前应再次执行 `make runtime-prerequisites`。

### 本轮验收边界

在没有实际硬件日志、baseline JSON、状态记录和故障注入输出前，Task 9 的以下项目保持未完成：

- 30 分钟连续遥控建图和资源指标；
- 至少五次 pause/resume；
- save/stop/restart/load known-free pose/resume；
- occupied/unknown/out-of-bounds pose 拒绝；
- SLAM/API/写盘/runtime 重启故障注入；
- 最终阶段 0～1 出口验收。

只有无运动 smoke、人工监督的运动测试和故障注入分别有证据，才能报告阶段 0～1 完成。

## 11. 阶段验收记录

验收时记录以下证据：

- baseline JSON 文件路径、硬件镜像 digest、ROS Domain；
- 节点/话题/TF/QoS 检查输出；
- 30 分钟测试日志和控制/地图 p95/p99 指标；
- 五次 pause/resume 的状态记录；
- 五次 save/load 的 revision 和 hash 记录；
- 一次已知 free pose 搬运恢复和一次非法 pose 拒绝；
- SLAM/API/保存目录故障注入的零速度证据；
- offline pytest、colcon test、Compose config 和 `git diff --check` 输出。

只有离线测试和真机出口条件均有证据，阶段 0～1 才算完成。代码构建成功不等于真机建图已经验收。
