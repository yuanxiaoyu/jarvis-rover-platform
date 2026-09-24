import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Protocol

from app.models.map import Coordinate2D
from app.models.telemetry import TelemetryPacket
from app.models.sensor import SensorSnapshot
from app.models.system import RobotPoseState
from app.services.sensor_data import unavailable_sensor_snapshot


class TelemetryRuntime(Protocol):
    def robot_pose(self) -> RobotPoseState: ...

    def sensor_snapshot(self) -> SensorSnapshot: ...


async def telemetry_stream(
    interval_seconds: float = 1.0,
    runtime: TelemetryRuntime | None = None,
) -> AsyncIterator[TelemetryPacket]:
    """Stream current robot telemetry, falling back to explicit unavailable data."""
    while True:
        now = datetime.now(timezone.utc)
        pose = runtime.robot_pose() if runtime is not None else None
        pose_available = pose is not None and pose.available and pose.x is not None and pose.y is not None
        sensor = (
            runtime.sensor_snapshot()
            if runtime is not None
            else unavailable_sensor_snapshot("实时位姿和传感器数据源未连接")
        )
        yield TelemetryPacket(
            timestamp=pose.timestamp if pose_available and pose.timestamp is not None else now,
            pose=Coordinate2D(
                x=pose.x if pose_available else 0.0,
                y=pose.y if pose_available else 0.0,
            ),
            speed_mps=abs(pose.linear_velocity_mps or 0.0) if pose_available else 0.0,
            sensor=sensor,
        )
        await asyncio.sleep(interval_seconds)
