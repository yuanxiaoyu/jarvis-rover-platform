from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SensorType(str, Enum):
    BATTERY = "battery"
    TEMPERATURE = "temperature"
    IMU = "imu"
    LIDAR = "lidar"


class BatteryReading(BaseModel):
    percent: float = Field(ge=0.0, le=100.0)
    voltage_v: float = Field(ge=0.0)
    charging: bool = False


class TemperatureReading(BaseModel):
    board_c: float
    motor_c: float


class ImuReading(BaseModel):
    yaw_rad: float
    pitch_rad: float
    roll_rad: float


class LidarReading(BaseModel):
    source: str = "MS200_TOF"
    points_2d: int = Field(ge=0)
    map_quality: float = Field(ge=0.0, le=1.0)


class SensorSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    battery: BatteryReading
    temperature: TemperatureReading
    imu: ImuReading
    lidar: LidarReading

