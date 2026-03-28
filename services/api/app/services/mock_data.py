import random
from datetime import datetime, timezone

from app.models.map import Coordinate2D
from app.models.sensor import (
    BatteryReading,
    ImuReading,
    LidarReading,
    SensorSnapshot,
    TemperatureReading,
)


def make_sensor_snapshot() -> SensorSnapshot:
    return SensorSnapshot(
        timestamp=datetime.now(timezone.utc),
        battery=BatteryReading(
            percent=round(random.uniform(45.0, 100.0), 2),
            voltage_v=round(random.uniform(11.1, 12.6), 2),
            charging=False,
        ),
        temperature=TemperatureReading(
            board_c=round(random.uniform(45.0, 65.0), 2),
            motor_c=round(random.uniform(50.0, 75.0), 2),
        ),
        imu=ImuReading(
            yaw_rad=round(random.uniform(-3.14, 3.14), 3),
            pitch_rad=round(random.uniform(-0.2, 0.2), 3),
            roll_rad=round(random.uniform(-0.2, 0.2), 3),
        ),
        lidar=LidarReading(
            points_2d=random.randint(700, 1400),
            map_quality=round(random.uniform(0.7, 0.99), 2),
        ),
    )


def make_pose() -> Coordinate2D:
    return Coordinate2D(
        x=round(random.uniform(-5.0, 5.0), 3),
        y=round(random.uniform(-5.0, 5.0), 3),
    )

