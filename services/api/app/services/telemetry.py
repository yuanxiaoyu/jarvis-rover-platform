import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from app.models.map import Coordinate2D
from app.models.telemetry import TelemetryPacket
from app.services.sensor_data import unavailable_sensor_snapshot


async def telemetry_stream(interval_seconds: float = 1.0) -> AsyncIterator[TelemetryPacket]:
    """Stream only explicitly unavailable telemetry until a real source is wired."""
    while True:
        yield TelemetryPacket(
            timestamp=datetime.now(timezone.utc),
            pose=Coordinate2D(x=0.0, y=0.0),
            speed_mps=0.0,
            sensor=unavailable_sensor_snapshot("实时位姿和传感器数据源未连接"),
        )
        await asyncio.sleep(interval_seconds)
