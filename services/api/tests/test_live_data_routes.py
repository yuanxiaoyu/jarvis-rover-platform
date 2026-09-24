from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
import zlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.hardware import RadarScan
from app.models.map import Coordinate2D, GridOrigin, MapModel, MapSource, OccupancyGridMeta
from app.models.mapping import MappingState, MappingStatus
from app.models.sensor import BatteryReading, ImuReading, LidarReading, SensorSnapshot, TemperatureReading
from app.models.system import RobotPoseState
from app.services.mapping_backend import InMemoryMappingBackend
from app.services.zone_store import ZoneStore


class FakeRuntime:
    def __init__(self) -> None:
        self.model = MapModel(
            map_id="live-map",
            name="live map",
            source=MapSource.MS200_TOF_2D,
            available=True,
            updated_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
            occupancy=OccupancyGridMeta(
                resolution_m_per_cell=0.1,
                width_cells=3,
                height_cells=2,
                origin=GridOrigin(x=-1.0, y=-2.0),
                frame_id="map",
                data=[0, 50, 100, -1, 20, 95],
            ),
        )

    def map_snapshot(self, *, include_data: bool = True):
        snapshot = self.model.model_copy(deep=True)
        if not include_data:
            snapshot.occupancy.data = None
        return snapshot

    def mapping_status(self):
        return MappingStatus(state=MappingState.MAPPING, ready=True, motion_allowed=True)

    def robot_pose(self):
        return RobotPoseState(
            available=True,
            x=1.0,
            y=2.0,
            yaw_rad=0.3,
            linear_velocity_mps=0.25,
        )

    def sensor_snapshot(self):
        return SensorSnapshot(
            available=True,
            battery=BatteryReading(percent=80),
            temperature=TemperatureReading(),
            imu=ImuReading(yaw_rad=0.3),
            lidar=LidarReading(points_2d=42),
        )

    def radar_scan(self):
        return RadarScan(available=True, points=[])


@contextmanager
def live_client(tmp_path) -> Iterator[TestClient]:
    old_runtime = getattr(app.state, "ros_runtime", None)
    old_backend = getattr(app.state, "mapping_backend", None)
    old_zones = getattr(app.state, "zone_store", None)
    old_dir = settings.mapping_session_dir
    settings.mapping_session_dir = str(tmp_path)
    app.state.ros_runtime = FakeRuntime()
    app.state.mapping_backend = InMemoryMappingBackend()
    app.state.zone_store = ZoneStore(tmp_path / "zones.json")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        settings.mapping_session_dir = old_dir
        for name, previous in (("ros_runtime", old_runtime), ("mapping_backend", old_backend), ("zone_store", old_zones)):
            if previous is None:
                if hasattr(app.state, name):
                    delattr(app.state, name)
            else:
                setattr(app.state, name, previous)


def test_system_snapshot_uses_real_map_pose_and_mapping_state(tmp_path):
    with live_client(tmp_path) as client:
        response = client.get("/api/v1/system/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["map"]["available"] is True
    assert payload["map"]["occupancy"]["data"] is None
    assert payload["robot_pose"]["x"] == 1.0
    assert payload["mapping"]["state"] == "mapping"


def test_telemetry_websocket_streams_injected_runtime_state(tmp_path):
    with live_client(tmp_path) as client:
        with client.websocket_connect("/ws/telemetry") as websocket:
            telemetry = websocket.receive_json()
            sensors = websocket.receive_json()
            radar = websocket.receive_json()

    assert telemetry["type"] == "robot.telemetry"
    assert telemetry["data"]["pose"] == {"x": 1.0, "y": 2.0}
    assert telemetry["data"]["speed_mps"] == pytest.approx(0.25)
    assert telemetry["data"]["sensor"]["available"] is True
    assert sensors["type"] == "sensor.snapshot"
    assert radar["type"] == "lidar.scan"


def test_grid_endpoint_transmits_compressed_signed_occupancy_data(tmp_path):
    with live_client(tmp_path) as client:
        response = client.get("/api/v1/map/grid")
        assert response.status_code == 200
        assert zlib.decompress(response.content) == bytes((0, 50, 100, 255, 20, 95))
        cached = client.get("/api/v1/map/grid", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304


def test_zone_geometry_is_persisted_and_can_be_edited(tmp_path):
    zone = {
        "zone_id": "lab",
        "name": "实验区",
        "type": "semantic",
        "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}],
    }
    with live_client(tmp_path) as client:
        created = client.post("/api/v1/zones", json=zone)
        updated = client.put("/api/v1/zones/lab", json={**zone, "name": "东侧实验区"})
        fetched = client.get("/api/v1/zones")
    assert created.status_code == 200
    assert updated.status_code == 200
    assert fetched.json()[0]["name"] == "东侧实验区"
    assert (tmp_path / "zones.json").is_file()


def test_mapping_routes_drive_the_injected_runtime_backend(tmp_path):
    with live_client(tmp_path) as client:
        started = client.post("/api/v1/mapping/start", json={"session_id": "test-session"})
        status = client.get("/api/v1/mapping/status")
    assert started.status_code == 200
    assert started.json()["accepted"] is True
    assert status.json()["state"] == "starting"


def test_navigation_plan_endpoint_returns_world_frame_path(tmp_path):
    with live_client(tmp_path) as client:
        runtime = app.state.ros_runtime
        runtime.model = MapModel(
            map_id="planning-map",
            name="planning map",
            source=MapSource.MS200_TOF_2D,
            available=True,
            occupancy=OccupancyGridMeta(
                resolution_m_per_cell=0.1,
                width_cells=30,
                height_cells=30,
                origin=GridOrigin(),
                data=[0] * 900,
            ),
        )
        response = client.post("/api/v1/navigation/plan", json={"goal": {"x": 2.0, "y": 2.0}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["length_m"] > 0
    assert payload["goal_reached"]["x"] == pytest.approx(2.05)
    assert payload["waypoints"][0] == {"x": 1.0, "y": 2.0}
