"""Pure validation of the prerequisites for a mapping session."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PreflightSnapshot:
    publisher_counts: dict[str, int]
    stream_age_s: dict[str, float]
    tf_available: dict[str, bool]
    duplicate_tf_publishers: int
    duplicate_ekf_nodes: int
    slam_backend_nodes: int
    free_bytes: int
    emergency_stop: bool
    final_cmd_vel_publishers: int = 1
    teleop_cmd_vel_publishers: int = 1


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    checks: dict[str, CheckResult]


class PreflightChecker:
    """Evaluate a snapshot without accessing ROS or the filesystem."""

    REQUIRED_TOPICS = ("/scan", "/odom_raw", "/imu")
    REQUIRED_TF = "base_footprint->laser_frame"

    def __init__(
        self,
        sensor_timeout_s: float,
        min_free_bytes: int,
        *,
        required_topics: tuple[str, ...] | None = None,
        required_tf: str = REQUIRED_TF,
    ) -> None:
        if sensor_timeout_s <= 0:
            raise ValueError("sensor_timeout_s must be positive")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes cannot be negative")
        if not required_topics:
            required_topics = self.REQUIRED_TOPICS
        if not required_tf:
            raise ValueError("required_tf cannot be empty")
        self.sensor_timeout_s = sensor_timeout_s
        self.min_free_bytes = min_free_bytes
        self.required_topics = tuple(required_topics)
        self.required_tf = required_tf

    def check(self, snapshot: PreflightSnapshot) -> PreflightReport:
        checks: dict[str, CheckResult] = {}
        for topic in self.required_topics:
            count = snapshot.publisher_counts.get(topic, 0)
            checks[f"{topic} publisher"] = CheckResult(
                count >= 1,
                f"{topic} has {count} publisher(s); expected at least one",
            )
            age = snapshot.stream_age_s.get(topic, float("inf"))
            checks[f"{topic} fresh"] = CheckResult(
                isfinite(age) and age <= self.sensor_timeout_s,
                f"{topic} age is {age:.3f}s; limit is {self.sensor_timeout_s:.3f}s"
                if isfinite(age)
                else f"{topic} has no recent sample",
            )

        checks["required TF"] = CheckResult(
            snapshot.tf_available.get(self.required_tf, False),
            f"{self.required_tf} is "
            + ("available" if snapshot.tf_available.get(self.required_tf, False) else "unavailable"),
        )
        checks["unique TF publishers"] = CheckResult(
            snapshot.duplicate_tf_publishers == 0,
            f"{snapshot.duplicate_tf_publishers} duplicate TF publisher(s) detected",
        )
        checks["unique EKF"] = CheckResult(
            snapshot.duplicate_ekf_nodes == 0,
            f"{snapshot.duplicate_ekf_nodes} duplicate EKF node(s) detected",
        )
        checks["no competing SLAM"] = CheckResult(
            snapshot.slam_backend_nodes == 0,
            f"{snapshot.slam_backend_nodes} competing SLAM backend(s) detected",
        )
        checks["disk space"] = CheckResult(
            snapshot.free_bytes >= self.min_free_bytes,
            f"{snapshot.free_bytes} free bytes; minimum is {self.min_free_bytes}",
        )
        checks["emergency stop"] = CheckResult(
            snapshot.emergency_stop is False,
            "emergency stop is active" if snapshot.emergency_stop else "emergency stop is clear",
        )
        checks["final cmd_vel publisher"] = CheckResult(
            snapshot.final_cmd_vel_publishers == 1,
            f"/cmd_vel has {snapshot.final_cmd_vel_publishers} publisher(s); expected exactly one",
        )
        checks["teleop cmd_vel publisher"] = CheckResult(
            snapshot.teleop_cmd_vel_publishers >= 1,
            f"/cmd_vel_teleop has {snapshot.teleop_cmd_vel_publishers} publisher(s); expected at least one",
        )
        return PreflightReport(ok=all(result.ok for result in checks.values()), checks=checks)
