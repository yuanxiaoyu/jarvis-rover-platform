import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from app.models.telemetry import TelemetryPacket
from app.services.mock_data import make_pose, make_sensor_snapshot


async def telemetry_stream(interval_seconds: float = 1.0) -> AsyncIterator[TelemetryPacket]:
    while True:
        yield TelemetryPacket(
            timestamp=datetime.now(timezone.utc),
            pose=make_pose(),
            speed_mps=0.3,
            sensor=make_sensor_snapshot(),
        )
        await asyncio.sleep(interval_seconds)

