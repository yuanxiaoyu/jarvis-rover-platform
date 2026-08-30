# 稳定建图运行时离线验收与缺口修复设计

## 背景与目标

当前工作树已经包含稳定建图运行时计划 Task 1～8 的大部分实现，但计划复选项仍未更新，且没有完整的离线验证证据。此工作聚焦于：

- 对照 `docs/superpowers/plans/2026-08-28-stable-mapping-runtime.md` 审查现有实现；
- 以测试驱动方式修复能够由离线测试证明的缺口；
- 在隔离 Python 虚拟环境中执行 API 和纯 Python 测试；
- 对 ROS 2 launch、接口、Docker/Compose 和脚本执行可用的静态或容器验证；
- 如当前环境无法连接目标真机，不伪造 Task 9 的性能、故障注入或硬件出口证据。

不新增沿墙探索、完整 Web 3D、语音任务编排或其他阶段 2～4 功能。不提交、不推送。

## 约束与完成定义

1. 宿主系统 Python 不安装项目依赖；在当前工作树创建隔离 `.venv`，用于安装 `services/api` 的开发依赖。
2. 每个生产行为缺口先有一个能证明缺口的失败测试，再实施最小修复；配置和文档只做必要同步。
3. ROS 相关测试优先在现有 ROS Humble/Docker 环境中执行；没有可用容器或硬件时，记录环境阻塞，不将静态检查当成真机验收。
4. 验证范围包括 API、纯 Python 模块、脚本、ROS 静态 launch 契约、Compose 配置和 `git diff --check`。
5. Task 9 的真机步骤只有在实际命令输出、日志、baseline JSON 和故障注入记录存在时才可标记完成；本轮默认保持待现场执行。

## 现有实现重点审查面

### 会话、持久化与地图校验

核对 `SessionController` 的状态迁移是否始终在运动许可关闭时进入 `STARTING`、`PAUSED`、`SAVING` 和 `ERROR_RECOVERABLE`，并验证启动、暂停、恢复、停止、保存、加载和错误恢复的边界。核对 `SessionStore` 的组件名校验、revision staging、manifest 哈希、current 原子替换、损坏检测和旧 revision 保留。核对 PGM P2/P5、旋转 origin、unknown/occupied/free 像素和越界坐标。

### ROS runtime 与安全层

检查统一 launch 是否只有一个 EKF、一个 async SLAM、三条静态 TF、mapping node 和 safety node；检查参数安装和包依赖。验证 preflight 对传感器新鲜度、TF、重复节点、磁盘、急停和控制 publisher 的拒绝逻辑。验证 gate 在没有 mapping 许可、命令过期、状态许可过期、急停和输入重启时输出零，并且只复制和限幅安全的差速 Twist。

### API 与部署

在 fake backend 下验证 REST 状态码和 Pydantic 输入边界；在不导入 `rclpy` 的条件下验证 bridge 的初始锁定、未知状态降级、service 调用超时和关闭路径。核对 lifespan 在 production required bridge 失败时 fail-fast，在本地 fake 模式不连接真实机器人。核对 entrypoint 双进程退出传播、Compose profile 互斥意图、ROS Domain 20、脚本的必需 graph 检查和 probe 的有界采样。

## 验证顺序

1. 建立 `.venv` 并安装 API dev 依赖。
2. 运行现有纯 Python/API/script 测试，定位真实失败。
3. 为每个确认的生产缺口补失败回归测试，观察预期失败。
4. 实施最小修复并重复聚焦测试，再运行全部相关测试。
5. 执行 Python 编译、shell 语法/静态检查、launch AST/文本契约、Compose config；若 Docker/ROS 不可用，记录明确原因。
6. 更新计划复选项，只勾选有本轮证据的离线步骤；在 runbook 增加“本轮离线验证”和“真机证据仍缺失”记录。
7. 最终运行 `git diff --check`、完整可用测试集和工作树状态检查；不提交。

## 真机部署与开机自启动

用户确认当前执行环境是真机，并选择“官方 Yahboom 硬件容器 + 项目 runtime”的互斥拓扑，以及系统级 systemd 服务。实现增加：

- `deploy/jarvis-rover-runtime.service`：由 systemd 在 Docker 和网络就绪后托管项目 `rover-runtime`；
- `scripts/install_rover_runtime_service.sh`：检查仓库、Docker Compose、`.env`、ROS Domain 20 和未启用硬件 profile，构建 runtime、安装 unit 并启用服务；
- `scripts/uninstall_rover_runtime_service.sh`：停止/禁用并移除 unit，不删除地图、容器镜像或官方硬件容器；
- `README.md`：记录官方硬件启动顺序、安装/查看日志/停止/卸载/回滚命令、graph check、baseline 和人工运动验收边界。

开机服务只管理 `rover-runtime`，不挂载串口、不启动 `yahboom-hardware` 或 `micro-ros-agent`，也不自动调用 mapping `start`/`resume`。runtime 初始状态必须为 `IDLE` 且最终 `/cmd_vel` 保持零速，官方硬件层继续由既有 Yahboom Supervisor 管理。服务重启只影响软件 runtime，保留 `/workspace/data/maps`。

## 失败处理与安全边界

- 测试依赖安装失败时不改系统环境，保留错误输出并继续可做的静态检查。
- ROS service 名称、响应字段、TF 外参和性能指标没有目标环境输出时，不推断为已验证。
- 部署脚本不执行 `/start`、`/resume`、非零 `cmd_vel` 或故障注入；真机运动验收仅按 runbook 由人工在安全场地执行。
- systemd 安装、启用和停止属于对本机运行状态的外部影响，必须在用户明确批准后执行；unit 模板和脚本可先静态审查。
- 发现保存、加载或 runtime 故障时，优先确保旧 current revision 和运动锁定行为不被破坏。
