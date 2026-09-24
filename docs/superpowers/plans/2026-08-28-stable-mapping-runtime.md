# 稳定建图运行时实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 本仓库策略要求在用户明确要求前不提交或推送，因此每个任务的“检查点”只运行验证命令并保留工作树，不执行 `git commit`。

**Goal:** 在真实 Yahboom MicroROS-Pi5 + Raspberry Pi 5 + ROS 2 Humble 环境中交付阶段 0～1：统一硬件接口和 ROS 图、以 SLAM Toolbox `online_async` 为主的流畅建图、可暂停/恢复/保存/加载的会话管理、搬运后手动初始位姿恢复，以及不会因 SLAM/API 故障继续运动的安全速度门控。

**Architecture:** 保留 Yahboom 的 `YB_Car_Node` 作为硬件层，只让它发布 `/scan`、`/odom_raw`、`/imu` 并接收最终 `/cmd_vel`。项目运行时由一个统一 launch 启动 IMU 滤波、唯一 EKF、静态 TF、SLAM Toolbox、`rover_mapping` 会话节点和安全门控；FastAPI 通过后台 rclpy bridge 调用会话服务并缓存状态。所有容器使用 `ROS_DOMAIN_ID=20`，同一时刻只允许一个 EKF、一个 `map -> odom` 发布者和一个最终 `/cmd_vel` 发布者。

**Tech Stack:** ROS 2 Humble、Python 3.10/3.11、`rclpy`、`slam_toolbox` `online_async`、`robot_localization`、`imu_complementary_filter`、FastAPI、Pydantic v2、Docker Compose、pytest、rosbag2。

---

## Scope and file map

本计划只实现已经确认的阶段 0～1；沿墙探索、完整 Web 2D/3D 视图和语音任务编排另写独立计划，不在本计划中偷偷扩展。

### 新增文件

- `ros2_ws/src/rover_interfaces/msg/MappingSession.msg`：ROS 图上的会话状态契约。
- `ros2_ws/src/rover_interfaces/srv/MappingCommand.srv`：开始、暂停、恢复、停止、保存、加载和手动位姿加载命令。
- `ros2_ws/src/rover_mapping/rover_mapping/session.py`：不依赖 ROS 的状态机、状态快照和合法迁移。
- `ros2_ws/src/rover_mapping/rover_mapping/persistence.py`：版本化会话目录、manifest、SHA-256 和原子 current 指针。
- `ros2_ws/src/rover_mapping/rover_mapping/map_validation.py`：读取地图 YAML/PGM 并校验手动初始位姿落在已知可通行像素。
- `ros2_ws/src/rover_mapping/rover_mapping/preflight.py`：传感器、TF、磁盘和重复发布者预检。
- `ros2_ws/src/rover_mapping/rover_mapping/slam_gateway.py`：SLAM Toolbox service client 协议和 rclpy 实现。
- `ros2_ws/src/rover_mapping/params/slam_toolbox_online_async.yaml`：Pi 5 初始异步 SLAM 参数。
- `ros2_ws/src/rover_mapping/test/test_session.py`、`test_persistence.py`、`test_map_validation.py`、`test_preflight.py`：纯 Python 单元测试。
- `ros2_ws/src/rover_safety/rover_safety/gate.py`：纯 Python 速度门控和 watchdog。
- `ros2_ws/src/rover_safety/test/test_gate.py`：安全门控单元测试。
- `ros2_ws/src/rover_bringup/launch/mapping.launch.py`：统一 ROS 运行链路。
- `ros2_ws/src/rover_bringup/test/test_mapping_launch_contract.py`：统一 launch 的静态契约测试。
- `ros2_ws/src/rover_bringup/params/ekf.yaml`：项目唯一 EKF 配置。
- `services/api/app/models/mapping.py`：API 会话模型。
- `services/api/app/services/mapping_backend.py`：API 后端协议和内存测试后端。
- `services/api/app/services/ros_bridge.py`：FastAPI 到 ROS service/status 的线程桥接。
- `services/api/app/routers/mapping.py`：建图会话 REST 路由。
- `services/api/tests/test_mapping_routes.py`、`test_ros_bridge.py`：API 单元测试。
- `scripts/ros_graph_probe.py`：记录传感器频率、时间戳、QoS、TF 和资源基线。
- `scripts/verify_ros_graph.sh`：部署前的 ROS 图唯一性和必需接口检查。
- `scripts/measure_ros_baseline.sh`：调用 probe 保存阶段 0 基线。
- `docker/Dockerfile.hardware`：可复现的 Yahboom 硬件镜像派生层。
- `docker/vendor/joy_remapped.launch.py`：把手柄输出从 `/cmd_vel` 重映射到 `/cmd_vel_teleop`。
- `docker/vendor/run_handle.sh`：硬件镜像中使用重映射 launch 的 Supervisor 入口。
- `docs/phase-0-1-runbook.md`：真机部署、诊断、恢复和验收手册。

### 修改文件

- `ros2_ws/src/rover_interfaces/CMakeLists.txt`、`package.xml`：注册消息/服务及依赖。
- `ros2_ws/src/rover_mapping/rover_mapping/mapping_node.py`、`setup.py`、`package.xml`、`params/mapping.yaml`：从空骨架变为会话管理节点。
- `ros2_ws/src/rover_bringup/launch/bringup.launch.py`、`setup.py`、`package.xml`：改为统一建图入口并注册 EKF 参数。
- `ros2_ws/src/rover_safety/rover_safety/safety_node.py`、`setup.py`、`package.xml`、`params/safety.yaml`：实现最终速度门控。
- `services/api/app/config.py`、`main.py`、`routers/__init__.py`、`state.py`、`README.md`、`pyproject.toml`：加入 ROS bridge 配置、生命周期和 API 契约。
- `compose.yaml`、`.env.example`、`docker/Dockerfile.runtime`、`docker/entrypoint.sh`：统一 Domain、运行模式、硬件 profile 和 runtime 启动。
- `docs/integration-contract.md`、`docs/pi-runtime-profile.md`、`README.md`：同步阶段 0～1 的真实运行约定。

---

## Task 1: 先锁定纯 Python 会话状态机与 ROS 接口

**Files:**
- Create: `ros2_ws/src/rover_mapping/test/test_session.py`
- Create: `ros2_ws/src/rover_mapping/rover_mapping/session.py`
- Create: `ros2_ws/src/rover_interfaces/msg/MappingSession.msg`
- Create: `ros2_ws/src/rover_interfaces/srv/MappingCommand.srv`
- Modify: `ros2_ws/src/rover_interfaces/CMakeLists.txt`
- Modify: `ros2_ws/src/rover_interfaces/package.xml`
- Modify: `ros2_ws/src/rover_mapping/package.xml`

- [ ] **Step 1: Write failing state-machine tests**

在 `test_session.py` 先写不导入 ROS 生成类型的测试，锁定状态和迁移规则：

```python
from rover_mapping.session import (
    CommandType,
    MappingState,
    SessionController,
    SessionError,
)


def test_new_session_is_idle_and_motion_locked():
    status = SessionController("room-20260828").snapshot()
    assert status.state is MappingState.IDLE
    assert status.motion_allowed is False
    assert status.session_id == "room-20260828"


def test_start_requires_successful_preflight():
    controller = SessionController("room-1")
    result = controller.request(CommandType.START, preflight_ok=False)
    assert result.accepted is False
    assert controller.snapshot().state is MappingState.IDLE
    assert "preflight" in result.message.lower()


def test_start_pause_resume_and_stop_transitions():
    controller = SessionController("room-1")
    assert controller.request(CommandType.START, preflight_ok=True).accepted
    controller.mark_started()
    assert controller.snapshot().state is MappingState.MAPPING
    assert controller.snapshot().motion_allowed is True

    assert controller.request(CommandType.PAUSE).accepted
    controller.mark_paused()
    assert controller.snapshot().state is MappingState.PAUSED
    assert controller.snapshot().motion_allowed is False

    assert controller.request(CommandType.RESUME, preflight_ok=True).accepted
    controller.mark_resumed()
    assert controller.snapshot().state is MappingState.MAPPING

    assert controller.request(CommandType.STOP).accepted
    controller.mark_saved()
    assert controller.snapshot().state is MappingState.IDLE


def test_illegal_resume_from_idle_is_rejected():
    controller = SessionController("room-1")
    result = controller.request(CommandType.RESUME, preflight_ok=True)
    assert result.accepted is False
    assert controller.snapshot().state is MappingState.IDLE


def test_gateway_failure_enters_recoverable_error_and_locks_motion():
    controller = SessionController("room-1")
    controller.request(CommandType.START, preflight_ok=True)
    controller.mark_failed("slam service unavailable")
    status = controller.snapshot()
    assert status.state is MappingState.ERROR_RECOVERABLE
    assert status.motion_allowed is False
    assert status.last_error == "slam service unavailable"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd ros2_ws
python3 -m pytest src/rover_mapping/test/test_session.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'rover_mapping.session'`.

- [ ] **Step 3: Implement the minimal pure state machine**

`session.py` 使用 `IntEnum` 以便直接映射到 ROS message 常量；状态迁移只允许以下路径：`IDLE -> STARTING -> MAPPING -> PAUSED -> MAPPING`，停止经过 `SAVING` 回到 `IDLE`，任何运行态可进入 `ERROR_RECOVERABLE`。实现以下公开类型和方法，不把 ROS client 或文件 IO 放入该文件：

```python
from dataclasses import dataclass
from enum import IntEnum


class MappingState(IntEnum):
    IDLE = 0
    STARTING = 1
    MAPPING = 2
    PAUSED = 3
    SAVING = 4
    ERROR_RECOVERABLE = 5


class CommandType(IntEnum):
    START = 0
    PAUSE = 1
    RESUME = 2
    STOP = 3
    SAVE = 4
    LOAD = 5


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    state: MappingState
    motion_allowed: bool
    ready: bool = False
    current_revision: str | None = None
    last_error: str = ""
    map_update_age_s: float | None = None


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    message: str


class SessionError(RuntimeError):
    pass


class SessionController:
    def __init__(self, session_id: str) -> None:
        self._status = SessionSnapshot(
            session_id=session_id,
            state=MappingState.IDLE,
            motion_allowed=False,
        )

    def snapshot(self) -> SessionSnapshot:
        return self._status

    def request(
        self,
        command: CommandType,
        *,
        preflight_ok: bool | None = None,
        has_initial_pose: bool = False,
    ) -> CommandResult:
        state = self._status.state
        if command is CommandType.START:
            if state is not MappingState.IDLE:
                return CommandResult(False, "start is only valid from IDLE")
            if preflight_ok is not True:
                return CommandResult(False, "preflight must pass before start")
            self._status = self._replace(state=MappingState.STARTING)
            return CommandResult(True, "start accepted")
        if command is CommandType.PAUSE:
            if state is not MappingState.MAPPING:
                return CommandResult(False, "pause is only valid from MAPPING")
            self._status = self._replace(state=MappingState.PAUSED)
            return CommandResult(True, "pause accepted")
        if command is CommandType.RESUME:
            if state is not MappingState.PAUSED:
                return CommandResult(False, "resume is only valid from PAUSED")
            if preflight_ok is not True:
                return CommandResult(False, "preflight must pass before resume")
            self._status = self._replace(state=MappingState.MAPPING, last_error="")
            return CommandResult(True, "resume accepted")
        if command is CommandType.STOP:
            if state not in (MappingState.MAPPING, MappingState.PAUSED):
                return CommandResult(False, "stop is only valid while mapping or paused")
            self._status = self._replace(state=MappingState.SAVING)
            return CommandResult(True, "stop accepted")
        if command is CommandType.SAVE:
            if state not in (MappingState.MAPPING, MappingState.PAUSED):
                return CommandResult(False, "save is only valid while mapping or paused")
            self._status = self._replace(state=MappingState.SAVING)
            return CommandResult(True, "save accepted")
        if command is CommandType.LOAD:
            if state not in (MappingState.IDLE, MappingState.PAUSED):
                return CommandResult(False, "load is only valid from IDLE or PAUSED")
            if not has_initial_pose:
                return CommandResult(False, "load requires an explicit initial pose")
            self._status = self._replace(state=MappingState.STARTING)
            return CommandResult(True, "load accepted")
        return CommandResult(False, "unknown mapping command")

    def mark_started(self) -> None:
        self._status = self._replace(state=MappingState.MAPPING, motion_allowed=True, ready=True)

    def mark_paused(self) -> None:
        self._status = self._replace(state=MappingState.PAUSED, motion_allowed=False)

    def mark_resumed(self) -> None:
        self._status = self._replace(state=MappingState.MAPPING, motion_allowed=True, ready=True)

    def mark_saved(self, *, resume: bool = False, revision: str | None = None) -> None:
        self._status = self._replace(
            state=MappingState.MAPPING if resume else MappingState.IDLE,
            motion_allowed=resume,
            ready=resume,
            current_revision=revision or self._status.current_revision,
        )

    def mark_failed(self, message: str) -> None:
        self._status = self._replace(
            state=MappingState.ERROR_RECOVERABLE,
            motion_allowed=False,
            ready=False,
            last_error=message,
        )

    def _replace(self, **changes: object) -> SessionSnapshot:
        from dataclasses import replace
        return replace(self._status, **changes)
```

- [ ] **Step 4: Add the ROS message and service contract**

`MappingSession.msg` 内容固定为：

```text
std_msgs/Header header
uint8 IDLE=0
uint8 STARTING=1
uint8 MAPPING=2
uint8 PAUSED=3
uint8 SAVING=4
uint8 ERROR_RECOVERABLE=5
string session_id
uint8 state
bool ready
bool motion_allowed
float32 map_update_age_s
string current_revision
string last_error
```

`MappingCommand.srv` 内容固定为：

```text
uint8 START=0
uint8 PAUSE=1
uint8 RESUME=2
uint8 STOP=3
uint8 SAVE=4
uint8 LOAD=5
uint8 command
string session_id
string map_name
int8 match_type
bool has_initial_pose
geometry_msgs/Pose2D initial_pose
---
bool accepted
uint8 state
string message
```

在 `rover_interfaces/CMakeLists.txt` 将两项加入 `rosidl_generate_interfaces`，保留 `DEPENDENCIES std_msgs geometry_msgs`；`package.xml` 增加 `geometry_msgs` 的 build/exec 依赖。`rover_mapping/package.xml` 增加 `geometry_msgs`、`nav_msgs`、`sensor_msgs`、`std_msgs`、`tf2_ros`、`slam_toolbox` 和 `rover_interfaces` 运行依赖，并增加 `python3-pytest` 测试依赖。

- [ ] **Step 5: Build the interface package and rerun tests**

Run:

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --packages-select rover_interfaces rover_mapping --symlink-install
source install/setup.bash
python3 -m pytest src/rover_mapping/test/test_session.py -q
ros2 interface show rover_interfaces/msg/MappingSession
ros2 interface show rover_interfaces/srv/MappingCommand
```

Expected: build succeeds, both interfaces print, and all focused tests pass.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check` and `git status --short`; do not commit until the user explicitly requests commits.

---

## Task 2: Implement durable session persistence and map-pose validation

**Files:**
- Create: `ros2_ws/src/rover_mapping/test/test_persistence.py`
- Create: `ros2_ws/src/rover_mapping/test/test_map_validation.py`
- Create: `ros2_ws/src/rover_mapping/rover_mapping/persistence.py`
- Create: `ros2_ws/src/rover_mapping/rover_mapping/map_validation.py`
- Modify: `ros2_ws/src/rover_mapping/setup.py`
- Modify: `ros2_ws/src/rover_mapping/params/mapping.yaml`

- [ ] **Step 1: Write persistence and pose-validation tests**

测试必须使用 `tmp_path`，不接触 `/workspace/data` 或真实 SD 卡。核心场景：

```python
import json

import pytest

from rover_mapping.map_validation import Pose2D, validate_pose_in_map
from rover_mapping.persistence import SessionStore


def test_save_revision_writes_manifest_and_hashes(tmp_path):
    store = SessionStore(tmp_path)
    revision = store.save_revision(
        session_id="room-1",
        map_name="living-room",
        map_pgm=b"P5\\n1 1\\n255\\n\\xff",
        map_yaml="image: living-room.pgm\\nresolution: 1.0\\norigin: [0, 0, 0]\\n",
        pose_graph=b"pose-graph-v1",
        metadata={"frame_id": "map", "last_pose": [0.0, 0.0, 0.0]},
    )
    manifest = store.load_current("room-1")
    assert manifest["revision_id"] == revision
    assert manifest["files"]["map_pgm_sha256"]
    assert (tmp_path / "sessions" / "room-1" / "revisions" / revision / "manifest.json").exists()


def test_failed_revision_does_not_change_current_pointer(tmp_path):
    store = SessionStore(tmp_path)
    first = store.save_revision("room-1", "map", b"one", "image: map.pgm\n", b"graph", {})
    with pytest.raises(ValueError):
        store.save_revision("room-1", "map", b"", "", b"", {})
    assert store.load_current("room-1")["revision_id"] == first


def test_session_id_and_map_name_cannot_escape_root(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_revision("../outside", "map", b"pgm", "yaml", b"graph", {})
    with pytest.raises(ValueError):
        store.save_revision("room", "../../outside", b"pgm", "yaml", b"graph", {})


def test_initial_pose_must_land_on_free_pixel(tmp_path):
    map_yaml = """image: map.pgm
resolution: 1.0
origin: [0.0, 0.0, 0.0]
occupied_thresh: 0.65
free_thresh: 0.196
negate: 0
"""
    # White, black, white: x=0 is free, x=1 is occupied, x=2 is free.
    pgm = b"P5\n3 1\n255\n\xff\x00\xff"
    assert validate_pose_in_map(map_yaml, pgm, Pose2D(0.2, 0.2, 0.0))
    assert not validate_pose_in_map(map_yaml, pgm, Pose2D(1.2, 0.2, 0.0))
    assert not validate_pose_in_map(map_yaml, pgm, Pose2D(4.0, 0.2, 0.0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd ros2_ws
python3 -m pytest src/rover_mapping/test/test_persistence.py src/rover_mapping/test/test_map_validation.py -q
```

Expected: FAIL because `SessionStore`, `Pose2D` and `validate_pose_in_map` do not exist.

- [ ] **Step 3: Implement safe, versioned persistence**

`SessionStore` 使用如下目录布局，避免用固定文件名直接覆盖上一份可用会话：

```text
<session_dir>/
└── sessions/<session_id>/
    ├── current.json
    └── revisions/<revision_id>/
        ├── map.pgm
        ├── map.yaml
        ├── posegraph
        └── manifest.json
```

实现以下接口：

```python
class SessionStore:
    def __init__(self, root: str | Path): ...
    def save_revision(
        self,
        session_id: str,
        map_name: str,
        map_pgm: bytes,
        map_yaml: str,
        pose_graph: bytes,
        metadata: dict[str, object],
    ) -> str: ...
    def load_current(self, session_id: str) -> dict[str, object]: ...
    def revision_paths(self, session_id: str, revision_id: str) -> dict[str, Path]: ...
    def resolve_current_paths(self, session_id: str) -> dict[str, Path]: ...
```

具体实现规则：

1. `_validate_component` 只接受正则 `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`，拒绝 `..`、斜杠、空字符串和绝对路径。
2. `save_revision` 先在同级 `.staging-<uuid>` 目录写入三个文件，调用 `flush()`、`os.fsync()`，计算 SHA-256，并写 manifest。
3. 用 `os.replace(staging_manifest, manifest_path)` 完成 revision 内 manifest 的原子落盘；确认三个文件存在且非空后，用临时 current 文件写 revision id，再 `os.replace` 到 `current.json`。
4. 任一步失败都删除 staging 目录，并且不修改已有 `current.json`。
5. manifest 至少包含 `schema_version=1`、`session_id`、`map_name`、`revision_id`、UTC `created_at`、`files` 哈希、`metadata`。
6. `load_current` 校验 JSON 中的 session/revision 字段和文件哈希；哈希不匹配直接抛出 `ValueError`，禁止加载损坏会话。

- [ ] **Step 4: Implement PGM pose validation**

`map_validation.py` 提供：

```python
@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


def validate_pose_in_map(map_yaml: str, pgm: bytes, pose: Pose2D) -> bool:
    """Return True only when the pose maps to a known free PGM pixel."""
```

解析 YAML 的 `image`、`resolution`、`origin`、`occupied_thresh`、`free_thresh`、`negate`；支持 P5 和 P2 PGM。将世界坐标按 origin 的 yaw 逆变换到栅格索引，越界、未知灰度（205 附近）和占用像素均返回 `False`。第一阶段只接受二维地图，origin 缺少时按 `[0, 0, 0]`，分辨率必须大于零；不 silently 放宽不完整地图。

- [ ] **Step 5: Add mapping parameters and run tests**

把 `rover_mapping/params/mapping.yaml` 改成：

```yaml
rover_mapping:
  ros__parameters:
    scan_topic: /scan
    odom_raw_topic: /odom_raw
    imu_topic: /imu
    map_topic: /map
    session_dir: /workspace/data/maps
    base_frame: base_footprint
    laser_frame: laser_frame
    odom_frame: odom
    map_frame: map
    sensor_timeout_seconds: 0.75
    min_free_bytes: 104857600
    status_publish_hz: 2.0
    checkpoint_on_pause: true
    slam_service_prefix: /slam_toolbox
```

`setup.py` 将 `params/slam_toolbox_online_async.yaml` 和 `params/mapping.yaml` 一起安装。运行：

```bash
cd ros2_ws
python3 -m pytest src/rover_mapping/test/test_persistence.py src/rover_mapping/test/test_map_validation.py -q
```

Expected: 全部 PASS。

- [ ] **Step 6: Review checkpoint**

Run `git diff --check`，确认失败保存不会修改 current 指针，再等待用户决定是否提交。

---

## Task 3: 建立 Pi 5 的统一 SLAM、EKF 和 TF launch

**Files:**
- Create: `ros2_ws/src/rover_mapping/params/slam_toolbox_online_async.yaml`
- Create: `ros2_ws/src/rover_bringup/launch/mapping.launch.py`
- Create: `ros2_ws/src/rover_bringup/params/ekf.yaml`
- Modify: `ros2_ws/src/rover_bringup/launch/bringup.launch.py`
- Modify: `ros2_ws/src/rover_bringup/setup.py`
- Modify: `ros2_ws/src/rover_bringup/package.xml`
- Modify: `docker/Dockerfile.runtime`

- [ ] **Step 1: Add a launch-description contract test**

创建 `ros2_ws/src/rover_bringup/test/test_mapping_launch_contract.py`，不启动真实节点，读取 launch 源文本并断言生产 launch 包含且只包含以下 executable 字符串：`complementary_filter_node`、`ekf_node`、`static_transform_publisher`、`async_slam_toolbox_node`、`mapping_node`、`safety_node`；同时断言源文件没有 `cartographer_node`、`slam_gmapping` 或第二个 EKF。测试代码：

```python
from pathlib import Path


LAUNCH = Path(__file__).parents[1] / "launch" / "mapping.launch.py"


def test_mapping_launch_has_one_slam_backend_and_one_ekf():
    text = LAUNCH.read_text()
    assert text.count("async_slam_toolbox_node") == 1
    assert "cartographer_node" not in text
    assert "slam_gmapping" not in text
    assert text.count("ekf_node") == 1


def test_mapping_launch_contains_safety_gate_and_session_manager():
    text = LAUNCH.read_text()
    assert "mapping_node" in text
    assert "safety_node" in text
    assert "static_transform_publisher" in text
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run:

```bash
cd ros2_ws
python3 -m pytest src/rover_bringup/test/test_mapping_launch_contract.py -q
```

Expected: FAIL because `mapping.launch.py` does not exist.

- [ ] **Step 3: Add explicit async SLAM parameters**

`slam_toolbox_online_async.yaml` 采用真机可调的保守起点，并明确覆盖官方 online_async 默认的仿真时钟：

```yaml
slam_toolbox:
  ros__parameters:
    use_sim_time: false
    mode: mapping
    odom_frame: odom
    map_frame: map
    base_frame: base_footprint
    scan_topic: /scan
    use_map_saver: true
    debug_logging: false
    throttle_scans: 1
    transform_publish_period: 0.05
    map_update_interval: 1.0
    resolution: 0.05
    max_laser_range: 6.0
    minimum_time_interval: 0.20
    transform_timeout: 0.20
    tf_buffer_duration: 30.0
    stack_size_to_use: 40000000
    enable_interactive_mode: false
    use_scan_matching: true
    use_scan_barycenter: true
    minimum_travel_distance: 0.10
    minimum_travel_heading: 0.10
    scan_buffer_size: 10
    scan_buffer_maximum_scan_distance: 8.0
    link_match_minimum_response_fine: 0.1
    link_scan_maximum_distance: 1.5
    loop_search_maximum_distance: 3.0
    do_loop_closing: true
    loop_match_minimum_chain_size: 10
    loop_match_maximum_variance_coarse: 3.0
    loop_match_minimum_response_coarse: 0.35
    loop_match_minimum_response_fine: 0.45
    correlation_search_space_dimension: 0.5
    correlation_search_space_resolution: 0.02
    correlation_search_space_smear_deviation: 0.10
    loop_search_space_dimension: 6.0
    loop_search_space_resolution: 0.05
    loop_search_space_smear_deviation: 0.03
    distance_variance_penalty: 0.5
    angle_variance_penalty: 1.0
    fine_search_angle_offset: 0.00349
    coarse_search_angle_offset: 0.349
    coarse_angle_resolution: 0.0349
    minimum_angle_penalty: 0.9
    minimum_distance_penalty: 0.5
    use_response_expansion: true
```

这些值是基线，不是最终调参结论；阶段 0 probe 的真实雷达 `range_max`、频率和 CPU 数据决定后续调整。禁止通过同时启动 Cartographer/GMapping 来比较，比较时必须一次只运行一个后端。

- [ ] **Step 4: Add the single EKF configuration**

`rover_bringup/params/ekf.yaml` 只融合连续轮速里程计的 x/y/yaw/速度和互补滤波后的 IMU yaw/yaw velocity：

```yaml
ekf_filter_node:
  ros__parameters:
    use_sim_time: false
    frequency: 30.0
    sensor_timeout: 0.20
    two_d_mode: true
    transform_time_offset: 0.0
    transform_timeout: 0.0
    print_diagnostics: true
    publish_tf: true
    publish_acceleration: false
    reset_on_time_jump: true
    odom_frame: odom
    base_link_frame: base_footprint
    world_frame: odom
    odom0: /odom_raw
    odom0_config: [true, true, false,
                   false, false, true,
                   true, true, false,
                   false, false, true,
                   false, false, false]
    odom0_queue_size: 5
    odom0_nodelay: true
    odom0_differential: false
    odom0_relative: false
    imu0: /imu/data
    imu0_config: [false, false, false,
                  false, false, true,
                  false, false, false,
                  false, false, true,
                  false, false, false]
    imu0_queue_size: 5
    imu0_nodelay: true
    imu0_differential: false
    imu0_relative: true
    imu0_remove_gravitational_acceleration: true
```

若阶段 0 发现 `/imu` 已经提供可靠姿态且 `/imu/data` 不存在，只允许通过参数和预检报告调整输入，不复制第二个 EKF 或静默改话题名。

- [ ] **Step 5: Implement the unified mapping launch**

`mapping.launch.py` 要用 `get_package_share_directory` 找参数路径，声明 `use_sim_time`、`start_imu_filter`、`session_dir` 和 `slam_params_file`，默认值分别为 `false`、`true`、`/workspace/data/maps` 和项目安装的 SLAM YAML。节点顺序为：

1. `imu_complementary_filter/complementary_filter_node`，将其默认输入 `/imu/data_raw` remap 到厂商实际的 `/imu`，输出保持 `/imu/data`；
2. `robot_localization/ekf_node`，加载 `ekf.yaml`；
3. 三个 `tf2_ros/static_transform_publisher`，仅项目 launch 发布：
   - `base_footprint -> base_link`：`0 0 0.05 0 0 0`，与 Yahboom `description_launch.py` 的实际外参一致；
   - `base_link -> laser_frame`：`-0.0046412 0 0.094079 0 0 0`；
   - `base_link -> imu_frame`：`-0.002999 -0.0030001 0.031701 0 0 0`；
4. `slam_toolbox/async_slam_toolbox_node`，加载 `slam_params_file` 并强制 `use_sim_time`；
5. `rover_mapping/mapping_node`，传入 `session_dir`；
6. `rover_safety/safety_node`，加载 `params/safety.yaml`。

`start_imu_filter` 用 `IfCondition` 控制滤波节点，但 EKF、TF、SLAM、会话和安全节点永远只出现一次。为避免重复 TF/EKF，runbook 明确要求项目 launch 运行时不要在 Yahboom 容器中再执行 `yahboomcar_bringup_launch.py`；如果外部节点已经存在，预检必须报错而不是继续。

- [ ] **Step 6: Update package metadata and Docker dependencies**

`rover_bringup/package.xml` 增加 `robot_localization`、`slam_toolbox`、`tf2_ros`、`imu_complementary_filter`、`rover_mapping`、`rover_safety` 和 `rover_interfaces`；`setup.py` 把 `launch/mapping.launch.py`、`params/ekf.yaml` 加入 `data_files`。

`docker/Dockerfile.runtime` 的 apt 包增加：

```dockerfile
ros-humble-robot-localization \
ros-humble-imu-tools \
python3-yaml
```

保留已有 `ros-humble-slam-toolbox`、`ros-humble-nav2-bringup` 和 `ros-humble-rosbridge-server`；安装完成后清理 apt lists。`rover_mapping/setup.py` 安装新的 SLAM 参数文件。

- [ ] **Step 7: Build and run launch contract checks**

Run:

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --packages-select rover_interfaces rover_mapping rover_safety rover_bringup --symlink-install
source install/setup.bash
python3 -m pytest src/rover_bringup/test/test_mapping_launch_contract.py -q
ros2 launch rover_bringup mapping.launch.py --show-args
```

Expected: build/test pass；`--show-args` 显示 `use_sim_time=false`、`start_imu_filter=true`、`session_dir` 和 `slam_params_file`，不启动真实节点。

- [ ] **Step 8: Review checkpoint**

运行 `git diff --check`，确认 launch 源中没有第二 SLAM/第二 EKF，再等待用户决定是否提交。

---

## Task 4: 实现预检、SLAM service gateway 和 `rover_mapping` ROS 节点

**Files:**
- Create: `ros2_ws/src/rover_mapping/test/test_preflight.py`
- Create: `ros2_ws/src/rover_mapping/rover_mapping/preflight.py`
- Create: `ros2_ws/src/rover_mapping/rover_mapping/slam_gateway.py`
- Modify: `ros2_ws/src/rover_mapping/rover_mapping/mapping_node.py`
- Modify: `ros2_ws/src/rover_mapping/rover_mapping/__init__.py`
- Modify: `ros2_ws/src/rover_mapping/setup.py`
- Modify: `ros2_ws/src/rover_mapping/package.xml`

- [ ] **Step 1: Write preflight tests with fake probes**

`test_preflight.py` 先覆盖：

```python
from rover_mapping.preflight import CheckResult, PreflightChecker, PreflightSnapshot


def healthy_snapshot():
    return PreflightSnapshot(
        publisher_counts={"/scan": 1, "/odom_raw": 1, "/imu": 1},
        stream_age_s={"/scan": 0.05, "/odom_raw": 0.03, "/imu": 0.04},
        tf_available={"base_footprint->laser_frame": True},
        duplicate_tf_publishers=0,
        duplicate_ekf_nodes=0,
        slam_backend_nodes=0,
        free_bytes=500_000_000,
        emergency_stop=False,
    )


def test_healthy_snapshot_passes():
    report = PreflightChecker(sensor_timeout_s=0.75, min_free_bytes=100_000_000).check(healthy_snapshot())
    assert report.ok is True
    assert all(item.ok for item in report.checks.values())


def test_missing_scan_and_duplicate_ekf_fail():
    snapshot = healthy_snapshot()
    snapshot = snapshot.__class__(**{**snapshot.__dict__, "publisher_counts": {"/scan": 0, "/odom_raw": 1, "/imu": 1}, "duplicate_ekf_nodes": 1})
    report = PreflightChecker(sensor_timeout_s=0.75, min_free_bytes=100_000_000).check(snapshot)
    assert report.ok is False
    assert report.checks["/scan publisher"].ok is False
    assert report.checks["unique EKF"].ok is False


def test_stale_sensor_and_low_disk_fail():
    snapshot = healthy_snapshot()
    snapshot = snapshot.__class__(**{**snapshot.__dict__, "stream_age_s": {"/scan": 2.0, "/odom_raw": 0.03, "/imu": 0.04}, "free_bytes": 1})
    report = PreflightChecker(sensor_timeout_s=0.75, min_free_bytes=100_000_000).check(snapshot)
    assert report.ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd ros2_ws
python3 -m pytest src/rover_mapping/test/test_preflight.py -q
```

Expected: FAIL because `PreflightSnapshot`, `PreflightChecker` and `CheckResult` do not exist.

- [ ] **Step 3: Implement preflight data types and checks**

`preflight.py` 定义：

```python
@dataclass(frozen=True)
class PreflightSnapshot:
    publisher_counts: dict[str, int]
    stream_age_s: dict[str, float]
    tf_available: dict[str, bool]
    duplicate_tf_publishers: int
    duplicate_ekf_nodes: int
    slam_backend_nodes: int
    free_bytes: int
    emergency_stop: bool

@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str

@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    checks: dict[str, CheckResult]
```

`PreflightChecker.check` 必须检查：`/scan`、`/odom_raw`、`/imu` 的 publisher count >= 1；各流 age <= `sensor_timeout_s`；`base_footprint->laser_frame` TF 可用；duplicate EKF == 0；当前 SLAM backend node count == 0（开始前由 manager 自己占有，检查函数接收外部计数）；可用磁盘 >= `min_free_bytes`；急停为 false。结果中每一项都带可读 detail，API/日志可以直接展示失败原因。

- [ ] **Step 4: Implement the SLAM Toolbox gateway**

`slam_gateway.py` 先定义可替换协议。SLAM Toolbox Humble 的实际 service 名称和返回值必须以启动后的 `ros2 service list`、`ros2 interface show` 及真机响应为准；不得假设旧发行版中的别名。默认 canonical 名称如下：

```python
class SlamGateway(Protocol):
    def services_ready(self) -> bool: ...
    def pause(self, paused: bool) -> bool: ...
    def clear_queue(self) -> bool: ...
    def save_map(self, path_without_extension: str) -> bool: ...
    def serialize_pose_graph(self, filename: str) -> bool: ...
    def deserialize_pose_graph(self, filename: str, match_type: int, pose: Pose2D) -> bool: ...
```

`RosSlamGateway` 在 `__init__` 创建 clients 时，通过参数 `slam_service_prefix` 和明确的 service-suffix 参数解析实际名称；默认 suffix 映射必须来自同一版本的 launch/运行时检查，并在缺少任一 service 时返回“服务契约不匹配”，而不是把命令误报为成功。Humble 标准接口至少包括 `slam_toolbox/srv/Pause`、`ClearQueue`、`SaveMap`、`SerializePoseGraph`、`DeserializePoseGraph`，但具体资源名（如 pause、clear_queue、serialize_map、deserialize_map）必须由 probe 验证并记录。

所有调用通过 `call_async` + `threading.Event` 等待，超时默认 10 秒；不能在 ROS executor callback 中调用 `spin_until_future_complete`，避免死锁。`Pause.status`、`ClearQueue.status`、`SerializePoseGraph.result` 和 `SaveMap.result` 必须检查，非成功值转为 `False` 并写日志。`deserialize_pose_graph` 使用请求中的 `match_type` 和 `geometry_msgs/Pose2D`；第一阶段搬运后恢复默认 `START_AT_GIVEN_POSE=2`。Gateway 单元测试必须使用 fake client 覆盖 service 缺失、超时和非零结果码，不能对尚未验证的 service 名称做成功断言。

- [ ] **Step 5: Implement `mapping_node.py` as a serialized command worker**

节点必须声明 `mapping.yaml` 中的参数，订阅 `/scan`、`/odom_raw`、`/imu`，用单调时钟记录最后收到时间，并创建 `tf2_ros.Buffer`/`TransformListener`。它发布：

- `/mapping/status`：`rover_interfaces/msg/MappingSession`，频率由 `status_publish_hz` 控制；
- `/mapping/motion_allowed`：`std_msgs/Bool`，只有 `MAPPING` 为 true；
- `/mapping/diagnostics`：`diagnostic_msgs/DiagnosticArray`，每次预检/错误包含失败项。

它提供 `/mapping/command`：`rover_interfaces/srv/MappingCommand`。service callback 只做参数校验、状态机合法性检查和将任务提交给单线程 `ThreadPoolExecutor(max_workers=1)`，立即返回 `accepted`；所有可能阻塞的 SLAM service、保存和 TF 操作在 worker 中执行。

worker 的具体行为：

- `START`：停止底盘，运行预检；通过后将状态置 `STARTING`，等待 SLAM clients ready，调用 `pause(false)`，成功才 `mark_started()`；失败调用 `mark_failed()`。
- `PAUSE`：先发布零 `Twist`，调用 `pause(true)`，调用 `clear_queue()` 丢弃暂停期间积压数据；若 `checkpoint_on_pause=true`，先保存 pose graph/map revision；成功后 `mark_paused()`。
- `RESUME`：预检通过后先 `clear_queue()`，调用 `pause(false)`，成功后 `mark_resumed()`；恢复前一直保持零速度。
- `SAVE`：先锁住运动，进入 `SAVING`；在 staging revision 中分别调用 `serialize_pose_graph` 和 `save_map`，验证输出文件并交给 `SessionStore` 写 manifest/current；从 `PAUSED` 返回 `PAUSED`，从 `MAPPING` 保存成功后恢复原状态，保存失败进入 `ERROR_RECOVERABLE` 并保留旧 revision。
- `STOP`：零速度、`pause(true)`、保存完整 revision，成功后状态回到 `IDLE`；任何保存失败都保留旧 current 指针并进入 `ERROR_RECOVERABLE`。
- `LOAD`：只允许 `IDLE` 或 `PAUSED`；必须 `has_initial_pose=true`，从 `SessionStore` 解析当前 revision，使用 `map_validation.py` 校验 free pixel，零速度后调用 `deserialize_pose_graph`；成功后保持 paused，发布状态等待人工确认，再由显式 `RESUME` 开始移动和继续建图。

启动时不要自动宣布 `MAPPING`；节点先是 `IDLE`、`motion_allowed=false`，等待 SLAM service ready 后调用 `pause(true)`。因此 launch 的 SLAM 节点不会因为 API 尚未连接而自动驱动车体。

- [ ] **Step 6: Add ROS QoS and package registration**

为 `/scan`、`/odom_raw`、`/imu` 显式使用 `QoSProfile(depth=5, reliability=RELIABLE, durability=VOLATILE, history=KEEP_LAST)`，与已观测到的 Yahboom publisher 兼容，并且不缓存无限旧消息。状态和 motion gate 使用 `RELIABLE + depth=10`。

`rover_mapping/setup.py` 将 `mapping_node` 继续注册为 console script，并注册测试目录所需的 pytest；`package.xml` 增加 `diagnostic_msgs`、`geometry_msgs`、`nav_msgs`、`sensor_msgs`、`std_msgs`、`tf2_ros`、`slam_toolbox`、`rover_interfaces`。

- [ ] **Step 7: Run pure tests, build, and inspect services**

Run:

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --packages-select rover_interfaces rover_mapping --symlink-install
source install/setup.bash
python3 -m pytest src/rover_mapping/test -q
ros2 interface show rover_interfaces/msg/MappingSession
ros2 interface show rover_interfaces/srv/MappingCommand
```

Expected: all pure tests pass and generated interfaces are available. No real SLAM command is sent by these tests.

- [ ] **Step 8: Review checkpoint**

运行 `git diff --check`；检查状态机在 `ERROR_RECOVERABLE` 时始终 `motion_allowed=false`，不提交。

---

## Task 5: Implement the safety velocity gate and reproducible Yahboom remap

**Files:**
- Create: `ros2_ws/src/rover_safety/rover_safety/gate.py`
- Create: `ros2_ws/src/rover_safety/test/test_gate.py`
- Create: `docker/Dockerfile.hardware`
- Create: `docker/vendor/joy_remapped.launch.py`
- Create: `docker/vendor/run_handle.sh`
- Modify: `ros2_ws/src/rover_safety/rover_safety/safety_node.py`
- Modify: `ros2_ws/src/rover_safety/params/safety.yaml`
- Modify: `ros2_ws/src/rover_safety/setup.py`
- Modify: `ros2_ws/src/rover_safety/package.xml`

- [ ] **Step 1: Write gate tests before ROS code**

`test_gate.py` 使用固定 monotonic 时间验证：

```python
from geometry_msgs.msg import Twist

from rover_safety.gate import CommandGate


def twist(x: float, z: float) -> Twist:
    message = Twist()
    message.linear.x = x
    message.angular.z = z
    return message


def test_gate_outputs_zero_until_mapping_allows_motion():
    gate = CommandGate(timeout_s=0.25)
    gate.update_input(twist(0.4, 0.2), now=10.0)
    assert gate.output(now=10.1).linear.x == 0.0
    gate.set_motion_allowed(True)
    assert gate.output(now=10.2).linear.x == 0.4


def test_stale_input_and_estop_output_zero():
    gate = CommandGate(timeout_s=0.25)
    gate.set_motion_allowed(True)
    gate.update_input(twist(0.4, 0.2), now=10.0)
    assert gate.output(now=10.3).linear.x == 0.0
    gate.update_input(twist(0.4, 0.2), now=11.0)
    gate.set_emergency_stop(True)
    assert gate.output(now=11.01).angular.z == 0.0


def test_clear_estop_does_not_enable_motion_by_itself():
    gate = CommandGate(timeout_s=0.25)
    gate.set_emergency_stop(True)
    gate.set_emergency_stop(False)
    assert gate.output(now=1.0).linear.x == 0.0
```

- [ ] **Step 2: Run the gate test and verify it fails**

Run:

```bash
cd ros2_ws
python3 -m pytest src/rover_safety/test/test_gate.py -q
```

Expected: FAIL because `CommandGate` does not exist.

- [ ] **Step 3: Implement pure gate and ROS safety node**

`gate.py` 只依赖 `geometry_msgs.msg.Twist`，提供 `update_input(Twist, now)`、`set_motion_allowed(bool)`、`set_emergency_stop(bool)` 和 `output(now)`；任何 gate false、急停或输入年龄 `> timeout_s` 均返回全零 Twist。输出必须复制消息，不返回调用者可继续修改的输入对象。

`safety_node.py` 改为：

- 订阅 `cmd_vel_in=/cmd_vel_teleop`、`/mapping/motion_allowed` 和 `emergency_stop_topic=/emergency_stop`；
- 发布 `cmd_vel_out=/cmd_vel`；
- 使用 20 Hz timer 输出 gate 结果；
- 启动时 `motion_allowed=false`、`emergency_stop=false` 但输入仍必须经过 250 ms watchdog；
- `/mapping/motion_allowed` 消息丢失时保持 false；
- `emergency_stop=true` 立即输出零；清除急停后仍需等待 mapping status 再允许运动；
- 日志只在状态变化时输出，不能每个 timer 周期刷屏。

`params/safety.yaml` 固定为：

```yaml
safety_node:
  ros__parameters:
    scan_topic: /scan
    cmd_vel_in: /cmd_vel_teleop
    cmd_vel_out: /cmd_vel
    motion_allowed_topic: /mapping/motion_allowed
    emergency_stop_topic: /emergency_stop
    command_timeout_seconds: 0.25
    publish_hz: 20.0
    max_linear_x_mps: 0.35
    max_angular_z_rps: 1.2
```

节点对 `linear.x` 和 `angular.z` 做参数限幅，清零 `linear.y/z` 与 `angular.x/y`，避免全向 Twist 意外传给差速底盘。

- [ ] **Step 4: Make the hardware control remap reproducible**

`docker/vendor/joy_remapped.launch.py` 只启动官方已安装的 `yahboomcar_ctrl/yahboom_joy` 和 `joy/joy_node`，对 `yahboom_joy` 设置：

```python
remappings=[("cmd_vel", "/cmd_vel_teleop")]
```

`docker/vendor/run_handle.sh` source `/opt/ros/humble/setup.bash` 和 `/root/yahboomcar_ws/install/setup.bash` 后执行：

```bash
exec ros2 launch /root/joy_remapped.launch.py
```

`docker/Dockerfile.hardware`：

```dockerfile
FROM yahboomtechnology/ros-humble:4.1.2

COPY docker/vendor/joy_remapped.launch.py /root/joy_remapped.launch.py
COPY docker/vendor/run_handle.sh /root/run_handle.sh
RUN chmod +x /root/run_handle.sh
```

该 profile 与用户当前手动 `yahboomtechnology/ros-humble:4.1.2` 容器二选一；不允许同时运行未 remap 的官方容器，否则 `/cmd_vel` 会有多个 publisher，`verify_ros_graph.sh` 必须阻止进入 MAPPING。

- [ ] **Step 5: Update safety package metadata and run tests**

`rover_safety/package.xml` 增加 `geometry_msgs`、`sensor_msgs`、`std_msgs`、`diagnostic_msgs`、`rover_interfaces`；`setup.py` 保留 `safety_node` entry point 并确保测试可由 colcon 发现。

Run:

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --packages-select rover_safety --symlink-install
source install/setup.bash
python3 -m pytest src/rover_safety/test -q
```

Expected: gate tests pass。

- [ ] **Step 6: Review checkpoint**

确认最终 `/cmd_vel` 只有安全节点发布、硬件节点只有订阅；执行 `git diff --check`，不提交。

---

## Task 6: Add FastAPI mapping-session bridge and REST endpoints

**Files:**
- Create: `services/api/app/models/mapping.py`
- Create: `services/api/app/services/mapping_backend.py`
- Create: `services/api/app/services/ros_bridge.py`
- Create: `services/api/app/routers/mapping.py`
- Create: `services/api/tests/test_mapping_routes.py`
- Create: `services/api/tests/test_ros_bridge.py`
- Modify: `services/api/app/config.py`
- Modify: `services/api/app/main.py`
- Modify: `services/api/app/routers/__init__.py`
- Modify: `services/api/app/state.py`
- Modify: `services/api/pyproject.toml`

- [ ] **Step 1: Write API tests against a fake backend**

测试不初始化 rclpy；通过 FastAPI dependency override 注入 `InMemoryMappingBackend`。覆盖：

```python
from fastapi.testclient import TestClient

from app.main import app
from app.services.mapping_backend import InMemoryMappingBackend


def client_with_backend():
    backend = InMemoryMappingBackend()
    app.state.mapping_backend = backend
    return TestClient(app)


def test_mapping_status_is_exposed():
    with client_with_backend() as client:
        response = client.get("/api/v1/mapping")
    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    assert response.json()["motion_allowed"] is False


def test_start_requires_session_id_and_returns_accepted():
    with client_with_backend() as client:
        response = client.post("/api/v1/mapping/start", json={"session_id": "room-1"})
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["state"] == "starting"


def test_pause_is_rejected_when_not_mapping():
    with client_with_backend() as client:
        response = client.post("/api/v1/mapping/pause")
    assert response.status_code == 409
    assert response.json()["detail"]


def test_load_requires_explicit_pose():
    with client_with_backend() as client:
        response = client.post("/api/v1/mapping/load", json={"session_id": "room-1"})
    assert response.status_code == 422
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
cd services/api
python3 -m pytest tests/test_mapping_routes.py -q
```

Expected: FAIL because mapping models, backend and router do not exist.

- [ ] **Step 3: Add Pydantic mapping models**

`app/models/mapping.py` 定义：

```python
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MappingState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    MAPPING = "mapping"
    PAUSED = "paused"
    SAVING = "saving"
    ERROR_RECOVERABLE = "error_recoverable"


class MappingStatus(BaseModel):
    session_id: str | None = None
    state: MappingState = MappingState.IDLE
    ready: bool = False
    motion_allowed: bool = False
    map_update_age_s: float | None = None
    current_revision: str | None = None
    last_error: str = ""


class MappingCommandResult(BaseModel):
    accepted: bool
    state: MappingState
    message: str


class SessionRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SaveRequest(BaseModel):
    map_name: str = Field(default="map", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class PoseRequest(SessionRequest):
    x: float
    y: float
    yaw: float
    match_type: Literal[2, 3] = 2
```

`load` 请求强制 `x/y/yaw`，默认 `match_type=2`（SLAM Toolbox `START_AT_GIVEN_POSE`）；`3` 只在明确要 `LOCALIZE_AT_POSE` 时允许。

- [ ] **Step 4: Implement backend protocol and deterministic local fake**

`mapping_backend.py` 定义 async Protocol：

```python
class MappingBackend(Protocol):
    async def status(self) -> MappingStatus: ...
    async def start(self, session_id: str) -> MappingCommandResult: ...
    async def pause(self) -> MappingCommandResult: ...
    async def resume(self) -> MappingCommandResult: ...
    async def stop(self) -> MappingCommandResult: ...
    async def save(self, map_name: str) -> MappingCommandResult: ...
    async def load(self, request: PoseRequest) -> MappingCommandResult: ...
    async def close(self) -> None: ...
```

`InMemoryMappingBackend` 只为本地测试和无 ROS 开发使用，初始 `MappingStatus()`；按同一状态规则返回 `202/409` 所需结果，不假装产生真实地图。它的 `start` 将状态设为 `starting`，其余命令严格检查当前状态。

`RosMappingBackend` 组合 `RosMappingBridge`，把每个方法映射为 `rover_interfaces/srv/MappingCommand` 请求；不能通过字符串拼接执行 `ros2 service call`。ROS response 的 numeric state 转成 API `MappingState`，未知值返回 `ERROR_RECOVERABLE` 和明确错误。

- [ ] **Step 5: Implement rclpy background bridge**

`ros_bridge.py` 延迟导入 rclpy 及生成接口，以便 API 单元测试在普通 Python 环境运行。`RosMappingBridge.start()`：

1. 保存当前 asyncio loop；
2. 创建独立 `rclpy.context.Context` 和 `Node("rover_api_bridge")`；
3. 创建 `/mapping/command` client 和 `/mapping/status` subscription；
4. 创建 `MultiThreadedExecutor(num_threads=2)`，在 daemon thread 中 `spin()`；
5. 等待 service ready，超时由 `ROVER_ROS_SERVICE_TIMEOUT_SECONDS` 控制，失败抛出 `RuntimeError`。

每次 service call 用 `client.call_async()`，在 rclpy future done callback 中通过 `loop.call_soon_threadsafe` 完成 asyncio Future，`asyncio.wait_for` 超时则返回失败结果。status callback 只更新锁保护的最近快照；不把原始 ROS message 放入无限队列。`close()` 先停止 executor、join thread，再 shutdown context。

- [ ] **Step 6: Add router and app lifespan**

`routers/mapping.py` 提供：

- `GET /api/v1/mapping` -> 当前 `MappingStatus`；
- `POST /api/v1/mapping/start` body `SessionRequest` -> `202`；
- `POST /api/v1/mapping/pause` -> `202`；
- `POST /api/v1/mapping/resume` -> `202`；
- `POST /api/v1/mapping/stop` -> `202`；
- `POST /api/v1/mapping/save` body `SaveRequest` -> `202`；
- `POST /api/v1/mapping/load` body `PoseRequest` -> `202`。

后端返回 `accepted=false` 时，当前状态冲突返回 HTTP 409，ROS bridge timeout 返回 HTTP 503；不把内部 traceback 返回给浏览器。

`config.py` 增加：

```python
ros_bridge_enabled: bool = False
ros_bridge_required: bool = False
ros_service_timeout_seconds: float = 10.0
ros_status_topic: str = "/mapping/status"
ros_command_service: str = "/mapping/command"
```

`main.py` 使用 `asynccontextmanager lifespan`：`ros_bridge_enabled=false` 时注入 `InMemoryMappingBackend`；true 时启动 `RosMappingBackend`，若 `ros_bridge_required=true` 且启动失败则让应用启动失败，不允许生产静默退回 fake。`routers/__init__.py` include mapping router。`state.py` 可以保留现有 mock map/mission 状态，不把它冒充为 ROS 地图；mapping status 由 backend 单独提供。

- [ ] **Step 7: Run API tests and static checks**

Run:

```bash
cd services/api
python3 -m pytest -q
python3 -m compileall app
```

Expected: all tests pass；已有 route 测试不受影响；未设置 `ROVER_ROS_BRIDGE_ENABLED` 时 API 仍可使用内存后端。

- [ ] **Step 8: Review checkpoint**

确认生产配置打开 bridge 后 ROS 不可用会 fail-fast，开发配置不会误连真实小车；运行 `git diff --check`，不提交。

---

## Task 7: 统一 Docker/Compose 运行模式和阶段 0 诊断脚本

**Files:**
- Create: `scripts/ros_graph_probe.py`
- Create: `scripts/verify_ros_graph.sh`
- Create: `scripts/measure_ros_baseline.sh`
- Modify: `docker/entrypoint.sh`
- Modify: `docker/Dockerfile.runtime`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `Makefile`

- [ ] **Step 1: Write probe unit tests for pure metric helpers**

在 `scripts/test_ros_graph_probe.py` 增加不初始化 ROS 的测试，先锁定频率计算、时间戳年龄和控制唯一性判断：

```python
from ros_graph_probe import hz_from_timestamps, unique_control_path


def test_hz_from_timestamps_uses_monotonic_sample_window():
    assert hz_from_timestamps([1.0, 1.1, 1.2, 1.3]) == 10.0


def test_unique_control_path_requires_one_final_publisher():
    assert unique_control_path(final_publishers=1, input_publishers=2) is True
    assert unique_control_path(final_publishers=2, input_publishers=1) is False
    assert unique_control_path(final_publishers=0, input_publishers=1) is False
```

- [ ] **Step 2: Run probe tests and verify they fail**

Run:

```bash
python3 -m pytest scripts/test_ros_graph_probe.py -q
```

Expected: FAIL because `ros_graph_probe.py` does not exist.

- [ ] **Step 3: Implement the ROS graph probe**

`scripts/ros_graph_probe.py` 通过 rclpy 采样 10 秒，命令行参数 `--duration`、`--output`、`--domain-id`；输出 JSON，至少包含：

```json
{
  "captured_at": "2026-08-28T00:00:00Z",
  "ros_domain_id": 20,
  "topics": {
    "/scan": {"publishers": 1, "hz": 8.0, "last_stamp_age_s": 0.04, "reliability": "RELIABLE", "durability": "VOLATILE"},
    "/odom_raw": {"publishers": 1, "hz": 30.0, "last_stamp_age_s": 0.02},
    "/imu": {"publishers": 1, "hz": 50.0, "last_stamp_age_s": 0.02}
  },
  "tf": {"base_footprint->laser_frame": true, "base_footprint->imu_frame": true},
  "nodes": {"ekf": [], "slam": [], "cmd_vel_final_publishers": 1},
  "resources": {"cpu_percent": 0.0, "memory_bytes": 0, "temperature_c": null},
  "control_path_ok": false
}
```

消息回调使用有界 deque；频率按 `(n-1)/(last-first)` 计算，空或单样本返回 null；ROS header stamp 为零或明显倒退时记录 error，不用接收时间掩盖时间戳错误。QoS 从 publisher endpoint info 中归一化为字符串。资源读取使用 `/proc/meminfo`、`/sys/class/thermal/thermal_zone0/temp` 和两次 `/proc/stat`，读取失败用 null 并记录 warning，不让 probe 崩溃。

- [ ] **Step 4: Implement graph verification shell script**

`verify_ros_graph.sh` 必须 source `/opt/ros/humble/setup.bash` 和 `/workspace/ros2_ws/install/setup.bash`，校验：

1. `ROS_DOMAIN_ID` 等于 20（允许通过 `EXPECTED_ROS_DOMAIN_ID` 覆盖）；
2. `/scan`、`/odom_raw`、`/imu`、`/mapping/status`、`/mapping/motion_allowed`、`/cmd_vel` 在 topic list 中；
3. `/cmd_vel` publisher count 恰为 1，`/cmd_vel_teleop` publisher count 至少 1；
4. EKF node count 恰为 1；
5. SLAM backend count 恰为 1，且节点名包含 `slam_toolbox`；
6. `/map -> /odom -> base_footprint -> laser_frame` TF 查询成功；
7. `ros2 service list` 包含 `/mapping/command` 和五个必须的 `/slam_toolbox/*` service。

任一失败打印具体项并退出码 1；不能用 `|| true` 吞掉必需检查失败。

- [ ] **Step 5: Implement baseline wrapper and Make targets**

`measure_ros_baseline.sh` 调用：

```bash
python3 /workspace/scripts/ros_graph_probe.py \
  --duration "${ROVER_BASELINE_DURATION_SECONDS:-10}" \
  --output "/workspace/data/baselines/$(date -u +%Y%m%dT%H%M%SZ).json"
```

脚本创建输出目录（`mkdir -p`，只创建项目 data 子目录），执行前检查 ROS source 已加载。`Makefile` 增加：

```make
ros-graph-check:
	./scripts/verify_ros_graph.sh

ros-baseline:
	./scripts/measure_ros_baseline.sh

runtime-test:
	cd services/api && python3 -m pytest -q
	cd ../ros2_ws && python3 -m pytest src/rover_mapping/test src/rover_safety/test src/rover_bringup/test -q
```

- [ ] **Step 6: Add entrypoint modes**

`docker/entrypoint.sh` 保留 `api`、`bringup`、`shell`，新增：

- `mapping`：`exec ros2 launch rover_bringup mapping.launch.py`，把 `session_dir` 和 `slam_params_file` 作为 launch 参数传入；
- `runtime`：在同一容器启动 `ros2 launch ... &` 和 `python3 -m uvicorn ... &`，保存两个 PID，trap `TERM/INT` 先发送终止信号并 `wait`，任一进程退出就停止另一个并返回非零状态；
- `probe`：`exec /workspace/scripts/verify_ros_graph.sh`。

runtime 模式不能使用 `exec bash` 留住退出的 ROS 进程，也不能把 API 当作唯一进程而忽略 launch 失败。

- [ ] **Step 7: Update Compose and environment**

`.env.example` 默认改为：

```dotenv
ROS_DOMAIN_ID=20
ROVER_ROS_BRIDGE_ENABLED=true
ROVER_ROS_BRIDGE_REQUIRED=true
ROVER_ROS_SERVICE_TIMEOUT_SECONDS=10
ROVER_MAPPING_SESSION_DIR=/workspace/data/maps
ROVER_BASELINE_DURATION_SECONDS=10
ROVER_ENABLE_WAKE_WORD=false
ROVER_ENABLE_ASR=false
ROVER_ENABLE_TTS=false
MICROROS_SERIAL_DEVICE=/dev/myserial
MICROROS_SERIAL_BAUD=115200
```

`compose.yaml`：

1. `rover-runtime` 使用 host network、项目 data/models volumes，环境显式传 `ROS_DOMAIN_ID: ${ROS_DOMAIN_ID:-20}`，默认 command 改为 `runtime`，healthcheck 为 `curl -fsS http://127.0.0.1:8000/health`；
2. `micro-ros-agent` 加 profile `micro-ros-agent`，不再默认和用户已运行的官方 agent 重复启动；
3. 增加 `yahboom-hardware` profile，基于 `docker/Dockerfile.hardware`，透传 `/dev/input`、`/dev/video0`，使用 host network 和相同 Domain；
4. 文档明确：`yahboom-hardware` 与现有 `sh ~/ros2_humble.sh` 只能二选一，`micro-ros-agent` 也只能保留一个实例；
5. 项目 runtime 不挂载 `/dev/myserial` 或 `/dev/rplidar` 来重复接管硬件，硬件仍由 Yahboom 容器提供，除非选择硬件 profile。

- [ ] **Step 8: Build/configure checks**

Run:

```bash
python3 -m pytest scripts/test_ros_graph_probe.py -q
docker compose config
docker compose build rover-runtime
```

Expected: probe tests pass；Compose config 展开后 Domain 为 20、runtime command 为 `runtime`、agent/hardware 只有 profile 控制；runtime image build succeeds。

- [ ] **Step 9: Review checkpoint**

运行 `git diff --check`，确认未把第二个 micro-ROS agent 设为默认服务，不提交。

---

## Task 8: 更新集成契约和真机阶段 0～1 runbook

**Files:**
- Create: `docs/phase-0-1-runbook.md`
- Modify: `docs/integration-contract.md`
- Modify: `docs/pi-runtime-profile.md`
- Modify: `services/api/README.md`
- Modify: `README.md`

- [ ] **Step 1: Document the only supported startup topologies**

runbook 必须明确两种互斥拓扑：

**拓扑 A：现有官方容器作为硬件层**

```text
sh ~/ros2_humble.sh
# 容器内仅运行底盘/雷达/IMU/odom/joy；不要运行 yahboomcar_bringup_launch.py

docker compose up -d rover-runtime
```

项目 runtime 使用 Domain 20，自己启动滤波、EKF、TF、SLAM、session manager 和 safety gate。

**拓扑 B：Compose hardware profile**

```text
docker compose --profile hardware --profile micro-ros-agent up -d
# 不再运行 sh ~/ros2_humble.sh 的第二份硬件容器
docker compose up -d rover-runtime
```

文档必须用加粗警告说明：不要同时运行两个 Yahboom 硬件容器、两个 micro-ROS agent、官方 EKF 和项目 EKF；不要同时启动 Cartographer、GMapping、SLAM Toolbox。

- [ ] **Step 2: Document diagnostic commands and expected graph**

加入以下命令和期望：

```bash
docker exec jarvis-rover-runtime /workspace/scripts/verify_ros_graph.sh
docker exec jarvis-rover-runtime /workspace/scripts/measure_ros_baseline.sh
docker exec jarvis-rover-runtime ros2 node list
docker exec jarvis-rover-runtime ros2 topic hz /scan
docker exec jarvis-rover-runtime ros2 topic hz /odom_raw
docker exec jarvis-rover-runtime ros2 topic hz /imu
docker exec jarvis-rover-runtime ros2 topic echo /mapping/status --once
docker exec jarvis-rover-runtime ros2 service list | grep -E '/mapping/command|/slam_toolbox/'
```

文档给出必需节点：`YB_Car_Node`、一个 `ekf_filter_node`、一个 `slam_toolbox`、`rover_mapping`、`rover_safety`；必需话题和 TF 链；说明目前真实 Yahboom `.bashrc` 是 Domain 20，而项目 `.env.example` 已同步。

- [ ] **Step 3: Document REST/session semantics**

在 `docs/integration-contract.md` 增加：

- `GET /api/v1/mapping`；
- `POST /api/v1/mapping/start`、`pause`、`resume`、`stop`、`save`、`load`；
- `WS /ws/telemetry` 当前仍是 mock/遥测流，不把它描述成已完成的 raw map stream；
- `/mapping/status` ROS message 字段和 state enum；
- 任何 `load` 必须包含 `session_id`、`x`、`y`、`yaw`，服务端/ROS 双重校验；
- `202` 表示命令已排队，客户端必须读取 status 直到终态；`409` 表示状态冲突，`503` 表示 ROS bridge 不可用。

- [ ] **Step 4: Document resource and rollback policy**

`pi-runtime-profile.md` 增加：

- 建图期间禁用 RViz、rosbridge 和摄像头推送作为基线；
- 采样/保存/压缩采用独立有界 worker，不能让 ROS callback 等待 SD 卡；
- 语音默认关闭；
- 目标控制 p99 指令间隔 <=250 ms、地图更新 p95 <=2 s、传感器频率相对空载下降 <=5%；
- 失败恢复顺序：安全零速度 -> 保留 current revision -> 标记 `ERROR_RECOVERABLE` -> 人工确认后再恢复；
- Cartographer 只能作为单独对照运行，不与 SLAM Toolbox 共存。

- [ ] **Step 5: Review docs for contradictory claims**

运行：

```bash
grep -RInE 'ROS_DOMAIN_ID|map_cartographer|map_gmapping|slam_toolbox|mapping/command|ros_bridge' README.md docs services/api/README.md
```

确认所有生产示例都使用 Domain 20，并且不再把 `yahboomcar_bringup_launch.py` 描述为完整建图入口。

- [ ] **Step 6: Review checkpoint**

运行 `git diff --check`；文档没有 `TODO`、`TBD`、未定义 API 或“稍后补充”表述，不提交。

---

## Task 9: 真机集成验证、故障注入和阶段出口验收

**Files:**
- Modify: `docs/phase-0-1-runbook.md`
- Modify: `scripts/verify_ros_graph.sh`（仅修复已由真机输出证明的检查问题）
- Modify: `services/api/tests/test_mapping_routes.py`（仅补充真实验证发现的 API 状态映射）

- [ ] **Step 1: Run all offline tests and builds**

在连接真机前执行。若在宿主机缺少 ROS 2，则必须在 `rover-runtime`/ROS Humble 容器内执行 ROS 相关命令；宿主机只执行 API、脚本和 Compose 检查：

```bash
cd services/api
python3 -m pytest -q
cd ../..
python3 -m pytest scripts/test_ros_graph_probe.py -q
docker compose config
# 在 ROS Humble 容器内：
source /opt/ros/humble/setup.bash
cd /workspace/ros2_ws
colcon build --symlink-install
source install/setup.bash
colcon test --event-handlers console_direct+
colcon test-result --verbose
```

Expected: API、ROS 包和脚本测试全部通过；如果某个测试需要 ROS 但当前环境没有 ROS，必须把它标成明确的环境前置条件，而不是吞掉错误。

- [ ] **Step 2: Start exactly one hardware topology**

按 runbook 选择现有官方容器或 hardware profile。确认：

```bash
ros2 node list
ros2 topic list
```

在项目 runtime 启动前，必须看到 `/scan`、`/odom_raw`、`/imu` 和 `/cmd_vel` 的硬件链路；如果没有，停止集成，不启动 SLAM。

- [ ] **Step 3: Capture the no-SLAM baseline**

先只运行硬件层和安全节点/项目 probe，记录：

```bash
docker exec jarvis-rover-runtime /workspace/scripts/measure_ros_baseline.sh
```

人工核对 `/scan`、`/odom_raw`、`/imu` 的频率、header 时间戳单调性、publisher QoS、CPU、内存、温度和 `/cmd_vel` publisher/subscriber 数。把 JSON 路径和关键数值写入 runbook 的“本机实测基线”小节；不要用设计目标冒充实测值。

- [ ] **Step 4: Start project mapping runtime and verify graph**

```bash
docker compose up -d rover-runtime
sleep 5
docker exec jarvis-rover-runtime /workspace/scripts/verify_ros_graph.sh
```

Expected：

- `/mapping/status` 初始为 `idle`，`motion_allowed=false`；
- `/cmd_vel` 只有安全节点 publisher，硬件节点 subscriber；
- `/map -> /odom -> base_footprint -> laser_frame` 可查询；
- `/slam_toolbox` service 全部 ready；
- 没有第二 EKF、Cartographer 或 GMapping。

- [ ] **Step 5: Exercise the start/pause/resume loop without moving first**

使用 API：

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v1/mapping/start \
  -H 'content-type: application/json' \
  -d '{"session_id":"bench-room"}'
curl -fsS http://127.0.0.1:8000/api/v1/mapping
```

底盘仍保持停止，确认状态从 `starting` 到 `mapping`，再执行 pause/resume；每次 pause 必须先出现零速度，`motion_allowed` 为 false；resume 前再次预检，成功后才为 true。重复原地 pause/resume 至少 5 次，任何一次 session manager 不应丢失状态。

- [ ] **Step 6: Run 30-minute manual mapping performance test**

在安全、无遮挡的测试区域，以低速手柄沿墙行驶 30 分钟；同时每 10 秒记录：

```bash
ros2 topic hz /scan --window 10
ros2 topic hz /odom_raw --window 10
ros2 topic hz /imu --window 10
ros2 topic hz /cmd_vel --window 10
```

把 `top`/`free -m`/温度数据和 API status 记录到日志。通过条件：无 OOM、无 swap 抖动、无明显热降频；控制输入 p99 间隔 <=250 ms；地图更新 p95 <=2 s；三路传感器频率相对 no-SLAM baseline 下降 <=5%；无持续 TF/message-filter/time-stamp error。

- [ ] **Step 7: Verify save/load and搬运后恢复**

1. 在 `MAPPING` 执行 `/save`，检查 `sessions/<id>/current.json`、map PGM/YAML、posegraph、manifest SHA-256。
2. 执行 `/stop`，重启 runtime，确认不会自动运动，状态为 `IDLE` 或待确认恢复态。
3. 通过 `/load` 提供已知 free pixel 的 `x/y/yaw`，确认状态保持 paused、`motion_allowed=false`。
4. 人工确认后 `/resume`，低速移动短距离，观察 `/map` 继续更新。
5. 将小车搬到 occupied/unknown/out-of-bounds 坐标，确认 `/load` 返回 409/失败且不会发布运动指令。

- [ ] **Step 8: Inject failures and verify safe behavior**

逐项测试并记录结果：

- 暂停/停止 SLAM service：安全 gate 立即输出零，状态 `ERROR_RECOVERABLE`；
- 断开 API 客户端：小车仍由 watchdog 控制，不接受新运动命令；
- 让保存目录不可写：旧 `current.json` 不改变，状态报告保存错误；
- 重启项目 runtime：硬件不会收到自动恢复运动命令；
- 发布第二个 `/cmd_vel` 或启动第二个 EKF：`verify_ros_graph.sh` 失败，不能标记阶段通过。

故障注入只在抬轮/安全场地进行；不要在真实行驶中使用会导致不可控运动的实验。

- [ ] **Step 9: Record acceptance evidence and final verification**

将每项结果、时间、硬件镜像 digest、Git 工作树状态和命令输出路径写入 `docs/phase-0-1-runbook.md`。最后运行：

```bash
git diff --check
cd services/api && python3 -m pytest -q
cd ../../ros2_ws && colcon test-result --verbose
cd .. && docker compose config >/dev/null
```

只有在所有离线测试和真机出口条件都有证据后，才向用户报告阶段 0～1 完成；若真机测试失败，报告具体失败项和日志，不把“代码已构建”表述为“建图已解决”。

- [ ] **Step 10: Review checkpoint**

检查最终 diff 是否只覆盖阶段 0～1；沿墙探索、完整 3D 和语音没有被提前实现。等待用户明确要求后再提交或进入下一独立计划。

---

## Implementation order and dependencies

```text
Task 1 contracts/state
        ↓
Task 2 persistence/pose validation
        ↓
Task 3 launch/EKF/SLAM parameters
        ↓
Task 4 mapping ROS node/gateway
        ↓
Task 5 safety gate + vendor remap
        ↓
Task 6 FastAPI bridge
        ↓
Task 7 Docker/Compose/probes
        ↓
Task 8 runbook/contracts
        ↓
Task 9 real-hardware acceptance
```

Task 1、2 的纯 Python 测试可以在没有小车时完成；Task 3～7 必须在 ROS 2 Humble 镜像中构建；Task 9 才允许对真实硬件执行运动测试。任何阶段都不能跳过 `verify_ros_graph.sh`，也不能把官方旧容器和新 hardware profile 同时启动。

## Spec coverage self-check

- 建图卡顿：Task 3 的 async SLAM 参数、Task 5 的 watchdog、Task 7 的基线和 Task 9 的 30 分钟性能验收覆盖。
- 正常移动持续建图：Task 3/4 的唯一 EKF、TF、SLAM 和 Task 9 的运动验收覆盖。
- 原地暂停恢复：Task 1/4 的状态机、pause/clear queue 和 Task 9 的 5 次循环覆盖。
- 保存/加载/搬运后继续：Task 2 的 revision/PGM 校验、Task 4 的 deserialize、Task 9 的 known-free/invalid pose 验收覆盖。
- ROS Domain 20 和官方容器边界：Task 7/8 覆盖。
- 单一控制发布者和异常停车：Task 5/7/9 覆盖。
- API 命令和状态：Task 6、Task 8 覆盖。
- 失败时保留旧会话：Task 2/4/9 覆盖。
- Pi 资源保护：Task 3、7、9 覆盖。
- 沿墙探索、完整 Web 3D、语音：明确留给后续独立计划，未假装包含在本次实现中。
