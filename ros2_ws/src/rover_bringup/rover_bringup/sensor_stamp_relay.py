from __future__ import annotations

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Imu, LaserScan

from rover_bringup.timestamp import NANOSECONDS_PER_SECOND, normalize_stamp


class SensorStampRelay(Node):
    """Relay Yahboom sensor data while correcting stale host-clock stamps."""

    def __init__(self) -> None:
        super().__init__("rover_sensor_stamp_relay")
        self.declare_parameter("stamp_max_skew_seconds", 2.0)
        max_skew_seconds = float(self.get_parameter("stamp_max_skew_seconds").value)
        if max_skew_seconds < 0:
            raise ValueError("stamp_max_skew_seconds must be non-negative")
        self._max_skew_ns = int(max_skew_seconds * NANOSECONDS_PER_SECOND)
        self._warned_streams: set[str] = set()
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._scan_pub = self.create_publisher(LaserScan, "/scan_normalized", qos)
        self._odom_pub = self.create_publisher(Odometry, "/odom_raw_normalized", qos)
        self._imu_pub = self.create_publisher(Imu, "/imu_normalized", qos)
        self.create_subscription(LaserScan, "/scan", self._on_scan, qos)
        self.create_subscription(Odometry, "/odom_raw", self._on_odom, qos)
        self.create_subscription(Imu, "/imu", self._on_imu, qos)

    def _relay(self, stream: str, message):
        now_ns = self.get_clock().now().nanoseconds
        source_ns = message.header.stamp.sec * NANOSECONDS_PER_SECOND + message.header.stamp.nanosec
        normalized_ns, adjusted = normalize_stamp(source_ns, now_ns, self._max_skew_ns)
        if adjusted:
            seconds, nanoseconds = divmod(normalized_ns, NANOSECONDS_PER_SECOND)
            message.header.stamp.sec = int(seconds)
            message.header.stamp.nanosec = int(nanoseconds)
            if stream not in self._warned_streams:
                skew = (source_ns - now_ns) / NANOSECONDS_PER_SECOND
                self.get_logger().warning(
                    f"/{stream} header timestamp differs from ROS time by {skew:.3f}s; "
                    "using relay receive time for this sensor stream"
                )
                self._warned_streams.add(stream)
        return message

    def _on_scan(self, message: LaserScan) -> None:
        self._scan_pub.publish(self._relay("scan", message))

    def _on_odom(self, message: Odometry) -> None:
        self._odom_pub.publish(self._relay("odom_raw", message))

    def _on_imu(self, message: Imu) -> None:
        self._imu_pub.publish(self._relay("imu", message))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SensorStampRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
