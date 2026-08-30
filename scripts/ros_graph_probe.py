#!/usr/bin/env python3
"""Capture a bounded ROS graph and resource baseline as JSON."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_SENSOR_TOPICS = ("/scan", "/odom_raw", "/imu")


def hz_from_timestamps(timestamps: list[float] | tuple[float, ...]) -> float | None:
    """Return frequency for a monotonic sample window, or None if undefined."""
    if len(timestamps) < 2:
        return None
    span = timestamps[-1] - timestamps[0]
    if span <= 0:
        return None
    return round((len(timestamps) - 1) / span, 6)


def unique_control_path(*, final_publishers: int, input_publishers: int) -> bool:
    """Require one final output and at least one upstream command source."""
    return final_publishers == 1 and input_publishers >= 1


def _cpu_snapshot() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (OSError, IndexError, ValueError):
        return None


def _cpu_percent() -> float | None:
    first = _cpu_snapshot()
    if first is None:
        return None
    time.sleep(0.1)
    second = _cpu_snapshot()
    if second is None:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))


def _memory_bytes() -> int | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        if "MemTotal" not in values or "MemAvailable" not in values:
            return None
        return values["MemTotal"] - values["MemAvailable"]
    except (OSError, ValueError):
        return None


def _temperature_c() -> float | None:
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="ascii").strip()
        return int(raw) / 1000.0
    except (OSError, ValueError):
        return None


def _qos_value(endpoint: Any, field: str) -> str | None:
    qos = getattr(endpoint, "qos_profile", None)
    value = getattr(qos, field, None)
    if value is None:
        return None
    return getattr(value, "name", str(value)).upper()


def _capture(duration: float) -> dict[str, Any]:
    try:
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.duration import Duration
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from rclpy.time import Time
        from sensor_msgs.msg import Imu, LaserScan
        from tf2_ros import Buffer, TransformListener
    except ImportError as exc:  # pragma: no cover - requires ROS runtime
        raise RuntimeError("ROS 2 Python dependencies are unavailable") from exc

    class ProbeNode(Node):
        def __init__(self) -> None:
            super().__init__("rover_graph_probe")
            qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            )
            self.samples: dict[str, deque[float]] = {
                topic: deque(maxlen=1000) for topic in REQUIRED_SENSOR_TOPICS
            }
            self.received: dict[str, float] = {}
            self.timestamp_errors: dict[str, deque[str]] = {
                topic: deque(maxlen=16) for topic in REQUIRED_SENSOR_TOPICS
            }
            self.last_stamp: dict[str, float] = {}
            types = {"/scan": LaserScan, "/odom_raw": Odometry, "/imu": Imu}
            self._subscriptions = [
                self.create_subscription(
                    types[topic], topic, self._callback(topic), qos
                )
                for topic in REQUIRED_SENSOR_TOPICS
            ]
            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)

        def _callback(self, topic: str):
            def callback(message: Any) -> None:
                now = time.monotonic()
                self.received[topic] = now
                stamp = getattr(message, "header", None)
                stamp_value = None
                if stamp is not None:
                    stamp_value = float(stamp.stamp.sec) + float(stamp.stamp.nanosec) * 1e-9
                if stamp_value is None or stamp_value <= 0:
                    self.timestamp_errors[topic].append("zero timestamp")
                    return
                if stamp_value < self.last_stamp.get(topic, stamp_value):
                    self.timestamp_errors[topic].append("timestamp moved backwards")
                    return
                self.last_stamp[topic] = stamp_value
                self.samples[topic].append(stamp_value)

            return callback

    node = ProbeNode()
    deadline = time.monotonic() + max(0.1, duration)
    try:
        while time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=min(0.1, max(0.0, deadline - time.monotonic())))

        now = time.monotonic()
        topics: dict[str, Any] = {}
        for topic in REQUIRED_SENSOR_TOPICS:
            endpoints = node.get_publishers_info_by_topic(topic)
            qos = endpoints[0] if endpoints else None
            received = node.received.get(topic)
            topics[topic] = {
                "publishers": len(endpoints),
                "hz": hz_from_timestamps(list(node.samples[topic])),
                "last_stamp_age_s": None if received is None else max(0.0, now - received),
                "reliability": None if qos is None else _qos_value(qos, "reliability"),
                "durability": None if qos is None else _qos_value(qos, "durability"),
                "timestamp_errors": list(node.timestamp_errors[topic]),
            }

        def endpoint_count(topic: str) -> int:
            return len(node.get_publishers_info_by_topic(topic))

        names = node.get_node_names_and_namespaces()
        names_only = [name for name, _namespace in names]
        ekf_nodes = [name for name in names_only if "ekf" in name.lower()]
        slam_nodes = [
            name
            for name in names_only
            if any(token in name.lower() for token in ("slam_toolbox", "cartographer", "gmapping"))
        ]
        tf_pairs = {
            "map->odom": ("map", "odom"),
            "odom->base_footprint": ("odom", "base_footprint"),
            "base_footprint->laser_frame": ("base_footprint", "laser_frame"),
            "base_link->imu_frame": ("base_link", "imu_frame"),
        }
        def can_transform(target: str, source: str) -> bool:
            try:
                return bool(
                    node.tf_buffer.can_transform(
                        target, source, Time(), timeout=Duration(seconds=0.05)
                    )
                )
            except Exception:
                return False

        tf_status = {
            name: can_transform(target, source)
            for name, (target, source) in tf_pairs.items()
        }
        final_publishers = endpoint_count("/cmd_vel")
        input_publishers = endpoint_count("/cmd_vel_teleop")
        return {
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
            "topics": topics,
            "tf": tf_status,
            "nodes": {
                "ekf": ekf_nodes,
                "slam": slam_nodes,
                "cmd_vel_final_publishers": final_publishers,
                "cmd_vel_input_publishers": input_publishers,
            },
            "resources": {
                "cpu_percent": _cpu_percent(),
                "memory_bytes": _memory_bytes(),
                "temperature_c": _temperature_c(),
            },
            "control_path_ok": unique_control_path(
                final_publishers=final_publishers,
                input_publishers=input_publishers,
            ),
        }
    finally:
        node.destroy_node()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain-id", type=int, default=None)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be positive")
    if args.domain_id is not None:
        os.environ["ROS_DOMAIN_ID"] = str(args.domain_id)

    import rclpy

    rclpy.init()
    try:
        result = _capture(args.duration)
    finally:
        rclpy.shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
