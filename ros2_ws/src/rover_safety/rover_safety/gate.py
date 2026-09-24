"""Pure fail-closed velocity gate used by the ROS safety node and unit tests."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Velocity:
    linear_x: float = 0.0
    angular_z: float = 0.0


@dataclass(frozen=True)
class GateInput:
    command: Velocity
    command_age_s: float
    scan_ranges: Sequence[float]
    scan_angle_min: float
    scan_angle_increment: float
    scan_range_min: float
    scan_range_max: float
    scan_age_s: float
    motion_allowed: bool
    motion_heartbeat_age_s: float
    emergency_stop: bool | None
    emergency_stop_age_s: float
    speed_scale: float
    speed_scale_age_s: float


@dataclass(frozen=True)
class GateResult:
    velocity: Velocity
    ready: bool
    reason: str


@dataclass(frozen=True)
class GateConfig:
    scan_timeout_s: float = 0.35
    command_timeout_s: float = 0.25
    heartbeat_timeout_s: float = 0.5
    robot_radius_m: float = 0.22
    clearance_margin_m: float = 0.08
    max_linear_mps: float = 0.18
    max_angular_rps: float = 0.6
    braking_accel_mps2: float = 0.5
    reaction_time_s: float = 0.2
    front_half_angle_rad: float = math.radians(40.0)


def select_command_source(exploration_state: str, navigation_motion_allowed: bool) -> tuple[str | None, bool]:
    """Keep the Nav2 and joystick command streams mutually exclusive."""
    if exploration_state == "exploring":
        return "navigation", bool(navigation_motion_allowed)
    if exploration_state in {"starting", "paused", "stopping", "error"}:
        return "navigation", False
    if exploration_state in {"idle", "complete"}:
        return "teleop", True
    return None, False


def evaluate(command: GateInput, config: GateConfig = GateConfig()) -> GateResult:
    """Validate the command and scan, then conservatively limit translation."""
    if command.emergency_stop is None or command.emergency_stop_age_s > config.heartbeat_timeout_s:
        return _blocked("急停状态无效或已超时")
    if command.emergency_stop:
        return _blocked("急停已触发")
    if command.motion_heartbeat_age_s > config.heartbeat_timeout_s:
        return _blocked("运动许可心跳已超时")
    if not command.motion_allowed:
        return _blocked("当前任务未获运动许可")
    if command.speed_scale_age_s > config.heartbeat_timeout_s:
        return _blocked("区域限速状态已超时")
    if not math.isfinite(command.speed_scale) or not 0.0 < command.speed_scale <= 1.0:
        return _blocked("区域限速值无效")
    if command.command_age_s > config.command_timeout_s:
        return _blocked("导航速度命令已超时")
    if command.scan_age_s > config.scan_timeout_s or not command.scan_ranges:
        return _blocked("雷达数据无效或已超时")
    if not math.isfinite(command.command.linear_x) or not math.isfinite(command.command.angular_z):
        return _blocked("导航速度命令包含非有限值")

    front, rear, closest = _clearances(command, config)
    if closest is None:
        return _blocked("雷达扫描没有有效测距")
    max_linear = config.max_linear_mps * command.speed_scale
    max_angular = config.max_angular_rps * command.speed_scale
    linear = max(-max_linear, min(max_linear, command.command.linear_x))
    angular = max(-max_angular, min(max_angular, command.command.angular_z))

    if linear > 0.0:
        stopping_distance = config.robot_radius_m + config.clearance_margin_m \
            + linear * config.reaction_time_s + linear * linear / (2.0 * config.braking_accel_mps2)
        if front is None or front <= stopping_distance:
            linear = 0.0
    elif linear < 0.0:
        reverse_speed = abs(linear)
        stopping_distance = config.robot_radius_m + config.clearance_margin_m \
            + reverse_speed * config.reaction_time_s + reverse_speed * reverse_speed / (2.0 * config.braking_accel_mps2)
        if rear is None or rear <= stopping_distance:
            linear = 0.0

    if angular and (closest is None or closest <= config.robot_radius_m + config.clearance_margin_m):
        angular = 0.0

    return GateResult(Velocity(linear, angular), True, "安全门控已就绪")


def _clearances(command: GateInput, config: GateConfig) -> tuple[float | None, float | None, float | None]:
    front: list[float] = []
    rear: list[float] = []
    all_ranges: list[float] = []
    for index, raw_range in enumerate(command.scan_ranges):
        distance = float(raw_range)
        if not math.isfinite(distance) or distance < command.scan_range_min or distance > command.scan_range_max:
            continue
        angle = command.scan_angle_min + index * command.scan_angle_increment
        normalized = math.atan2(math.sin(angle), math.cos(angle))
        all_ranges.append(distance)
        if abs(normalized) <= config.front_half_angle_rad:
            front.append(distance)
        elif abs(abs(normalized) - math.pi) <= config.front_half_angle_rad:
            rear.append(distance)
    return (
        min(front) if front else None,
        min(rear) if rear else None,
        min(all_ranges) if all_ranges else None,
    )


def _blocked(reason: str) -> GateResult:
    return GateResult(Velocity(), False, reason)
