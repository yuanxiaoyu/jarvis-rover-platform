from types import SimpleNamespace

from app.models.mapping import MappingState
from app.services import ros_runtime
from app.services.ros_runtime import RosRuntimeStore


def test_pause_toggle_uses_slam_toolbox_service(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="response: status=True")

    monkeypatch.setattr(ros_runtime.subprocess, "run", fake_run)
    runtime = RosRuntimeStore()

    result = runtime._call_pause_toggle()

    assert result.accepted
    assert calls[0][0] == [
        "ros2",
        "service",
        "call",
        "/slam_toolbox/pause_new_measurements",
        "slam_toolbox/srv/Pause",
        "{}",
    ]


def test_pause_and_resume_share_the_pause_toggle_service(monkeypatch):
    calls = []
    runtime = RosRuntimeStore()
    runtime._mapping_state = MappingState.MAPPING
    runtime._call_pause_toggle = lambda: calls.append("toggle") or SimpleNamespace(accepted=True, message="ok")

    paused = runtime.pause_mapping()
    assert paused.accepted
    assert paused.state is MappingState.PAUSED

    runtime.mapping_status = lambda: SimpleNamespace(ready=True)
    runtime.robot_pose = lambda: SimpleNamespace(available=True)
    resumed = runtime.resume_mapping()
    assert resumed.accepted
    assert resumed.state is MappingState.MAPPING
    assert calls == ["toggle", "toggle"]
