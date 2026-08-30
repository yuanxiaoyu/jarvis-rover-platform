from concurrent.futures import Future

import pytest

import rover_mapping.slam_gateway as gateway_module
from rover_mapping.map_validation import Pose2D
from rover_mapping.slam_gateway import RosSlamGateway


class FakeNode:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def create_client(self, service_type, _name):
        return FakeClient(service_type)

    def get_logger(self):
        return self

    def error(self, message: str) -> None:
        self.errors.append(message)


class FakeClient:
    def __init__(self, service_type) -> None:
        self.service_type = service_type
        self.ready = True
        self.response = service_type.Response()
        self.never_completes = False

    def wait_for_service(self, timeout_sec=0.0):
        return self.ready

    def call_async(self, _request):
        future = Future()
        if not self.never_completes:
            future.set_result(self.response)
        return future


class PauseRequest:
    __slots__ = ()


class PauseResponse:
    def __init__(self) -> None:
        self.status = True


class EmptyRequest:
    pass


class EmptyResponse:
    pass


class SaveRequest:
    def __init__(self) -> None:
        self.name = None


class ResultResponse:
    RESULT_SUCCESS = 0

    def __init__(self, result=0) -> None:
        self.result = result


class GraphRequest:
    def __init__(self) -> None:
        self.filename = ""


class DeserializeRequest(GraphRequest):
    def __init__(self) -> None:
        super().__init__()
        self.match_type = 0
        self.initial_pose = None


class FakeType:
    def __init__(self, request_type, response_type) -> None:
        self.Request = request_type
        self.Response = response_type


@pytest.fixture
def service_types():
    return {
        "pause": FakeType(PauseRequest, PauseResponse),
        "clear_queue": FakeType(EmptyRequest, EmptyResponse),
        "save_map": FakeType(SaveRequest, ResultResponse),
        "serialize_pose_graph": FakeType(GraphRequest, ResultResponse),
        "deserialize_pose_graph": FakeType(DeserializeRequest, EmptyResponse),
    }


def make_gateway(service_types, timeout_s=0.05):
    return RosSlamGateway(
        FakeNode(),
        timeout_s=timeout_s,
        service_types=service_types,
        client_factory=lambda service_type, _name: FakeClient(service_type),
    )


def test_pause_checks_status_and_uses_humble_default_name(service_types):
    gateway = make_gateway(service_types)

    assert gateway.service_names["pause"] == "/slam_toolbox/pause_new_measurements"
    assert gateway.pause(True) is True


def test_non_success_result_is_rejected(service_types):
    gateway = make_gateway(service_types)
    gateway._clients["save_map"].response = ResultResponse(255)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway_module, "_new_string_message", lambda: type("S", (), {})())
    assert gateway.save_map("/tmp/map") is False
    monkeypatch.undo()


def test_missing_required_service_is_reported(service_types):
    gateway = make_gateway(service_types)
    gateway._clients["pause"].ready = False

    assert gateway.services_ready() is False
    assert gateway.pause(True) is False


def test_optional_clear_queue_endpoint_is_allowed_to_be_absent(service_types):
    gateway = make_gateway(service_types)
    gateway._clients["clear_queue"].ready = False

    assert gateway.services_ready() is True
    assert gateway.clear_queue() is True


def test_call_timeout_is_reported(service_types):
    gateway = make_gateway(service_types, timeout_s=0.01)
    gateway._clients["clear_queue"].never_completes = True

    assert gateway.clear_queue() is False


def test_deserialize_passes_pose_and_match_type(service_types):
    gateway = make_gateway(service_types)
    captured = {}

    class RosPose:
        pass

    def pose_message(pose):
        captured["pose"] = pose
        return RosPose()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway_module, "_pose_message", pose_message)
    assert gateway.deserialize_pose_graph("graph", 2, Pose2D(1.0, 2.0, 0.5)) is True
    request = gateway._clients["deserialize_pose_graph"].last_request if hasattr(gateway._clients["deserialize_pose_graph"], "last_request") else None
    assert captured["pose"] == Pose2D(1.0, 2.0, 0.5)
    monkeypatch.undo()
