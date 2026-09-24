from types import SimpleNamespace

import pytest

from app.models.mapping import MappingState
from app.services.ros_runtime import RosRuntimeStore


class FakeRosNode:
    def __init__(self, nodes=(), publishers=()):
        self.nodes = nodes
        self.publishers = publishers

    def get_node_names_and_namespaces(self):
        return self.nodes

    def get_publishers_info_by_topic(self, _topic):
        return self.publishers


class FakeProcess:
    pid = 1234
    returncode = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def feed_fresh_sensors(runtime: RosRuntimeStore, received: float = 100.0) -> None:
    runtime._error = None
    runtime._scan = {"received": received}
    runtime._odom = {"received": received}
    runtime._imu = {"received": received}


def test_mapping_preflight_requires_fresh_imu(monkeypatch):
    now = [101.0]
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: now[0])
    runtime = RosRuntimeStore(enabled=True, stale_seconds=3.0)
    runtime._node = FakeRosNode()
    feed_fresh_sensors(runtime)

    assert runtime.mapping_status().ready is True
    runtime._imu = None
    assert runtime.mapping_status().ready is False
    result = runtime.start_mapping("session")
    assert result.accepted is False
    assert result.message == "雷达、里程计和 IMU 必须先稳定在线"


def test_mapping_start_rejects_an_existing_slam_node(monkeypatch):
    now = [101.0]
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: now[0])
    runtime = RosRuntimeStore(enabled=True, stale_seconds=3.0)
    runtime._node = FakeRosNode([("slam_toolbox", "/")])
    feed_fresh_sensors(runtime)
    monkeypatch.setattr("app.services.ros_runtime.subprocess.Popen", lambda *_args, **_kwargs: pytest.fail("must not launch duplicate SLAM"))

    result = runtime.start_mapping("session")

    assert result.accepted is False
    assert "已有定位或建图节点" in result.message


def test_mapping_status_transitions_to_mapping_when_launch_nodes_are_ready(monkeypatch):
    now = [101.0]
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: now[0])
    runtime = RosRuntimeStore(enabled=True)
    runtime._node = FakeRosNode([("rover_ekf", "/"), ("slam_toolbox", "/")])
    runtime._mapping_process = FakeProcess()
    runtime._mapping_state = MappingState.STARTING

    status = runtime.mapping_status()

    assert status.state is MappingState.MAPPING
    assert status.motion_allowed is False


def test_autonomous_mapping_launch_enables_nav2_without_changing_voice_mapping_default(tmp_path, monkeypatch):
    now = [101.0]
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: now[0])
    commands = []

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr("app.services.ros_runtime.subprocess.Popen", fake_popen)
    runtime = RosRuntimeStore(enabled=True, mapping_session_dir=str(tmp_path))
    runtime._node = FakeRosNode()
    feed_fresh_sensors(runtime)

    result = runtime.start_mapping("web-session", enable_navigation=True)

    assert result.accepted is True
    assert commands[0][-1] == "enable_navigation:=true"
    assert runtime._mapping_navigation_enabled is True


def test_autonomous_mapping_rejects_an_existing_unknown_cmd_vel_writer(tmp_path, monkeypatch):
    now = [101.0]
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: now[0])
    runtime = RosRuntimeStore(enabled=True, mapping_session_dir=str(tmp_path))
    runtime._node = FakeRosNode(publishers=[SimpleNamespace(node_name="_NODE_NAME_UNKNOWN_", node_namespace="/")])
    feed_fresh_sensors(runtime)
    monkeypatch.setattr(
        "app.services.ros_runtime.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("must not launch navigation with an unknown /cmd_vel writer"),
    )

    result = runtime.start_mapping("web-session", enable_navigation=True)

    assert result.accepted is False
    assert "/cmd_vel" in result.message
    assert "节点名未知" in result.message


def test_voice_mapping_launch_does_not_enable_autonomous_navigation(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(
        "app.services.ros_runtime.subprocess.Popen",
        lambda command, **_kwargs: (commands.append(command) or FakeProcess()),
    )
    runtime = RosRuntimeStore(enabled=True, mapping_session_dir=str(tmp_path))
    runtime._node = FakeRosNode()
    feed_fresh_sensors(runtime, received=100.0)
    monkeypatch.setattr("app.services.ros_runtime.time.monotonic", lambda: 101.0)

    result = runtime.start_mapping("voice-session")

    assert result.accepted is True
    assert "enable_navigation:=true" not in commands[0]
    assert runtime._mapping_navigation_enabled is False


def test_stopping_before_first_grid_skips_map_save(monkeypatch):
    runtime = RosRuntimeStore(enabled=True)
    runtime._mapping_process = FakeProcess()
    runtime._mapping_state = MappingState.STARTING
    monkeypatch.setattr("app.services.ros_runtime.os.killpg", lambda *_args: None)

    result = runtime.stop_mapping()

    assert result.accepted is True
    assert result.state is MappingState.IDLE
    assert "首张地图尚未生成，未执行保存" in result.message
