"""Safety velocity gate for manual and autonomous rover commands."""

from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool

from .gate import CommandGate


class SafetyNode(Node):
    """Publish a bounded, watchdog-protected final velocity command."""

    def __init__(self) -> None:
        super().__init__("rover_safety")
        self._declare_parameters()
        self._gate = CommandGate(
            float(self.get_parameter("command_timeout_seconds").value),
            float(self.get_parameter("motion_status_timeout_seconds").value),
        )
        self._obstacle_blocked = False
        self._last_scan_time: float | None = None
        self._scan_valid = False
        self._last_gate_state: tuple[bool, bool, bool, bool] | None = None

        reliable_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        command_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._cmd_sub = self.create_subscription(
            Twist,
            str(self.get_parameter("cmd_vel_in").value),
            self._command_callback,
            command_qos,
        )
        self._motion_sub = self.create_subscription(
            Bool,
            str(self.get_parameter("motion_allowed_topic").value),
            self._motion_callback,
            command_qos,
        )
        self._estop_sub = self.create_subscription(
            Bool,
            str(self.get_parameter("emergency_stop_topic").value),
            self._estop_callback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE),
        )
        self._stop_sub = self.create_subscription(
            Twist,
            str(self.get_parameter("stop_topic").value),
            self._stop_callback,
            command_qos,
        )
        self._scan_sub = self.create_subscription(
            LaserScan,
            str(self.get_parameter("scan_topic").value),
            self._scan_callback,
            reliable_qos,
        )
        self._cmd_pub = self.create_publisher(
            Twist,
            str(self.get_parameter("cmd_vel_out").value),
            command_qos,
        )
        publish_hz = float(self.get_parameter("publish_hz").value)
        if publish_hz <= 0:
            raise ValueError("publish_hz must be positive")
        self._timer = self.create_timer(1.0 / publish_hz, self._publish_command)
        self.get_logger().info("rover_safety active; motion remains locked until mapping allows it")

    def _declare_parameters(self) -> None:
        defaults = {
            "scan_topic": "/scan",
            "cmd_vel_in": "/cmd_vel_teleop",
            "cmd_vel_out": "/cmd_vel",
            "motion_allowed_topic": "/mapping/motion_allowed",
            "emergency_stop_topic": "/emergency_stop",
            "stop_topic": "/mapping/stop_cmd_vel",
            "command_timeout_seconds": 0.25,
            "scan_timeout_seconds": 0.75,
            "motion_status_timeout_seconds": 0.75,
            "publish_hz": 20.0,
            "max_linear_x_mps": 0.35,
            "max_angular_z_rps": 1.2,
            "min_clearance_m": 0.28,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

    def _command_callback(self, message: Twist) -> None:
        self._gate.update_input(message, now=time.monotonic())

    def _motion_callback(self, message: Bool) -> None:
        self._gate.set_motion_allowed(bool(message.data), now=time.monotonic())

    def _estop_callback(self, message: Bool) -> None:
        self._gate.set_emergency_stop(bool(message.data))
        if message.data:
            self._publish_zero()

    def _stop_callback(self, _message: Twist) -> None:
        # A session manager's stop pulse immediately locks the gate. A later
        # fresh mapping status is required before teleop can be accepted.
        self._gate.set_motion_allowed(False, now=time.monotonic())
        self._gate.update_input(Twist(), now=time.monotonic())

    def _scan_callback(self, message: LaserScan) -> None:
        self._last_scan_time = time.monotonic()
        clearance = float(self.get_parameter("min_clearance_m").value)
        valid_ranges = [
            distance
            for distance in message.ranges
            if math.isfinite(distance)
            and message.range_min <= distance <= message.range_max
        ]
        self._scan_valid = bool(valid_ranges)
        self._obstacle_blocked = any(
            distance <= clearance for distance in valid_ranges
        )

    def _publish_command(self) -> None:
        now = time.monotonic()
        scan_timeout = float(self.get_parameter("scan_timeout_seconds").value)
        scan_ready = (
            self._last_scan_time is not None
            and self._scan_valid
            and now - self._last_scan_time <= scan_timeout
        )
        raw = self._gate.output(now=now)
        if not scan_ready:
            raw = Twist()
        blocked = self._obstacle_blocked
        command = Twist() if blocked else self._bounded(raw)
        self._cmd_pub.publish(command)

        state = (
            self._gate.motion_allowed,
            self._gate.emergency_stop,
            blocked,
            scan_ready,
        )
        if state != self._last_gate_state:
            self.get_logger().info(
                f"velocity gate: motion={state[0]} estop={state[1]} "
                f"obstacle={state[2]} scan_ready={state[3]}"
            )
            self._last_gate_state = state

    def _bounded(self, command: Twist) -> Twist:
        bounded = Twist()
        limit_x = abs(float(self.get_parameter("max_linear_x_mps").value))
        limit_z = abs(float(self.get_parameter("max_angular_z_rps").value))
        linear_x = float(command.linear.x)
        angular_z = float(command.angular.z)
        if not math.isfinite(linear_x) or not math.isfinite(angular_z):
            return Twist()
        bounded.linear.x = max(-limit_x, min(limit_x, linear_x))
        bounded.angular.z = max(-limit_z, min(limit_z, angular_z))
        return bounded

    def _publish_zero(self) -> None:
        self._cmd_pub.publish(Twist())

    def destroy_node(self) -> bool:
        self._publish_zero()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetyNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
