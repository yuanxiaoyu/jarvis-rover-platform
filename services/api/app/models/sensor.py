from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SensorType(str, Enum):
    BATTERY = "battery"
    TEMPERATURE = "temperature"
    IMU = "imu"
    LIDAR = "lidar"


class BatteryReading(BaseModel):
    percent: float | None = Field(default=None, ge=0.0, le=100.0)
    voltage_v: float | None = Field(default=None, ge=0.0)
    charging: bool | None = None


class TemperatureReading(BaseModel):
    board_c: float | None = None
    motor_c: float | None = None


class ImuReading(BaseModel):
    yaw_rad: float | None = None
    pitch_rad: float | None = None
    roll_rad: float | None = None


class LidarReading(BaseModel):
    source: str = "MS200_TOF"
    points_2d: int | None = Field(default=None, ge=0)
    map_quality: float | None = Field(default=None, ge=0.0, le=1.0)


class SensorSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    available: bool = False
    error: str | None = None
    battery: BatteryReading = Field(default_factory=BatteryReading)
    temperature: TemperatureReading = Field(default_factory=TemperatureReading)
    imu: ImuReading = Field(default_factory=ImuReading)
    lidar: LidarReading = Field(default_factory=LidarReading)

