from datetime import datetime, timezone

from app.models.sensor import (
    BatteryReading,
    ImuReading,
    LidarReading,
    SensorSnapshot,
    TemperatureReading,
)


def unavailable_sensor_snapshot(reason: str = "传感器数据源未连接") -> SensorSnapshot:
    """Return an explicit unavailable snapshot instead of inventing measurements."""
    return SensorSnapshot(
        timestamp=datetime.now(timezone.utc),
        available=False,
        error=reason,
        battery=BatteryReading(percent=None, voltage_v=None, charging=None),
        temperature=TemperatureReading(board_c=None, motor_c=None),
        imu=ImuReading(yaw_rad=None, pitch_rad=None, roll_rad=None),
        lidar=LidarReading(points_2d=None, map_quality=None),
    )
