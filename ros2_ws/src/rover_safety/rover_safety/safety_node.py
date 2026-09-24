from __future__ import annotations

import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String

from rover_safety.gate import GateConfig, GateInput, Velocity, evaluate, select_command_source


class SafetyNode(Node):
    """Fail-closed gate between Nav2 and the Yahboom base command topic."""

    def __init__(self) -> None:
        super().__init__("rover_safety")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("cmd_vel_in", "/cmd_vel_candidate")
        self.declare_parameter("teleop_cmd_vel_in", "/cmd_vel_teleop")
        self.declare_parameter("cmd_vel_out", "/cmd_vel")
        self.declare_parameter("motion_allowed_topic", "/rover_navigation/motion_allowed")
        self.declare_parameter("emergency_stop_topic", "/rover_navigation/emergency_stop")
        self.declare_parameter("ready_topic", "/rover_safety/ready")
        self.declare_parameter("speed_scale_topic", "/rover_navigation/speed_scale")
        self.declare_parameter("min_clearance_m", 0.28)
        self.declare_parameter("robot_radius_m", 0.22)
        self.declare_parameter("max_linear_mps", 0.18)
        self.declare_parameter("max_angular_rps", 0.6)
        self.declare_parameter("heartbeat_timeout_s", 0.5)
        self.declare_parameter("scan_timeout_s", 0.35)
        self.declare_parameter("command_timeout_s", 0.25)

        self._config = GateConfig(
            scan_timeout_s=float(self.get_parameter("scan_timeout_s").value),
            command_timeout_s=float(self.get_parameter("command_timeout_s").value),
            heartbeat_timeout_s=float(self.get_parameter("heartbeat_timeout_s").value),
            robot_radius_m=float(self.get_parameter("robot_radius_m").value),
            clearance_margin_m=max(
                0.0,
                float(self.get_parameter("min_clearance_m").value)
                - float(self.get_parameter("robot_radius_m").value),
            ),
            max_linear_mps=float(self.get_parameter("max_linear_mps").value),
            max_angular_rps=float(self.get_parameter("max_angular_rps").value),
        )
        self._scan: tuple[tuple[float, ...], float, float, float, float, float] | None = None
        self._scan_received = 0.0
        self._command = Velocity()
        self._command_received = 0.0
        self._teleop_command = Velocity()
        self._teleop_command_received = 0.0
        self._exploration_state = "starting"
        self._exploration_status_received = 0.0
        self._motion_allowed = False
        self._motion_received = 0.0
        self._emergency_stop: bool | None = None
        self._emergency_stop_latched = False
        self._emergency_received = 0.0
        self._speed_scale: float | None = None
        self._speed_scale_received = 0.0
        self._last_reason = "等待传感器与安全状态"
        self._output_exclusive = False

        self._cmd_pub = self.create_publisher(Twist, str(self.get_parameter("cmd_vel_out").value), 10)
        self._ready_pub = self.create_publisher(Bool, str(self.get_parameter("ready_topic").value), 10)
        self._status_pub = self.create_publisher(String, "/rover_safety/status", 10)
        self.create_subscription(LaserScan, str(self.get_parameter("scan_topic").value), self._on_scan, 10)
        self.create_subscription(Twist, str(self.get_parameter("cmd_vel_in").value), self._on_command, 10)
        self.create_subscription(
            Twist,
            str(self.get_parameter("teleop_cmd_vel_in").value),
            self._on_teleop_command,
            10,
        )
        self.create_subscription(String, "/rover_navigation/status", self._on_exploration_status, 10)
        self.create_subscription(
            Bool,
            str(self.get_parameter("motion_allowed_topic").value),
            self._on_motion_allowed,
            10,
        )
        self.create_subscription(
            Bool,
            str(self.get_parameter("emergency_stop_topic").value),
            self._on_emergency_stop,
            10,
        )
        self.create_subscription(
            Float32,
            str(self.get_parameter("speed_scale_topic").value),
            self._on_speed_scale,
            10,
        )
        self.create_timer(0.05, self._publish_gated_command)
        self.get_logger().info("Fail-closed velocity gate active; output remains zero until all heartbeats are fresh.")

    def _on_scan(self, message: LaserScan) -> None:
        self._scan = (
            tuple(message.ranges),
            float(message.angle_min),
            float(message.angle_increment),
            float(message.range_min),
            float(message.range_max),
            time.monotonic(),
        )
        self._scan_received = self._scan[-1]

    def _on_command(self, message: Twist) -> None:
        self._command = Velocity(float(message.linear.x), float(message.angular.z))
        self._command_received = time.monotonic()

    def _on_teleop_command(self, message: Twist) -> None:
        self._teleop_command = Velocity(float(message.linear.x), float(message.angular.z))
        self._teleop_command_received = time.monotonic()

    def _on_exploration_status(self, message: String) -> None:
        try:
            payload = json.loads(message.data)
            state = payload.get("state") if isinstance(payload, dict) else None
            if state not in {"idle", "starting", "exploring", "paused", "stopping", "complete", "stopped", "error"}:
                raise ValueError("unknown exploration state")
        except (TypeError, ValueError, json.JSONDecodeError):
            state = "error"
        self._exploration_state = state
        self._exploration_status_received = time.monotonic()

    def _on_motion_allowed(self, message: Bool) -> None:
        was_allowed = self._motion_allowed
        self._motion_allowed = bool(message.data)
        self._motion_received = time.monotonic()
        if was_allowed and not self._motion_allowed:
            self._publish_zero_command()

    def _on_emergency_stop(self, message: Bool) -> None:
        was_stopped = self._emergency_stop is True
        self._emergency_stop_latched = self._emergency_stop_latched or bool(message.data)
        self._emergency_stop = self._emergency_stop_latched
        self._emergency_received = time.monotonic()
        if self._emergency_stop and not was_stopped:
            self._publish_zero_command()

    def _on_speed_scale(self, message: Float32) -> None:
        self._speed_scale = float(message.data)
        self._speed_scale_received = time.monotonic()

    def _output_is_exclusive(self) -> bool:
        output_topic = str(self.get_parameter("cmd_vel_out").value)
        try:
            publishers = self.get_publishers_info_by_topic(output_topic)
            subscribers = self.get_subscriptions_info_by_topic(output_topic)
        except Exception as exc:
            self._last_reason = f"无法检查底盘速度链路: {exc}"
            self._output_exclusive = False
            return False
        self._output_exclusive = (
            len(publishers) == 1
            and publishers[0].node_name == self.get_name()
            and any(item.node_name == "YB_Car_Node" for item in subscribers)
        )
        if len(publishers) != 1:
            self._last_reason = f"底盘速度口需要安全节点独占；当前有 {len(publishers)} 个发布者"
        elif publishers[0].node_name != self.get_name():
            self._last_reason = "安全节点不是底盘速度口的唯一发布者"
        elif not any(item.node_name == "YB_Car_Node" for item in subscribers):
            self._last_reason = "YB_Car_Node 未订阅安全速度出口"
        else:
            self._last_reason = "安全速度出口已连接"
        return self._output_exclusive

    def _publish_gated_command(self) -> None:
        now = time.monotonic()
        state_age = (now - self._exploration_status_received) if self._exploration_status_received else float("inf")
        state = self._exploration_state if state_age <= self._config.heartbeat_timeout_s else "unknown"
        source, motion_allowed = select_command_source(state, self._motion_allowed)
        if source == "navigation":
            command = self._command
            command_received = self._command_received
            motion_heartbeat_age = (now - self._motion_received) if self._motion_received else float("inf")
        elif source == "teleop":
            command = self._teleop_command
            command_received = self._teleop_command_received
            # An idle/complete navigation status is the time-limited manual-mode permit.
            motion_heartbeat_age = state_age
        else:
            command = Velocity()
            command_received = 0.0
            motion_allowed = False
            motion_heartbeat_age = float("inf")
        scan = self._scan
        if scan is None:
            scan_ranges: tuple[float, ...] = ()
            angle_min = angle_increment = range_min = range_max = 0.0
        else:
            scan_ranges, angle_min, angle_increment, range_min, range_max, _received = scan
        result = evaluate(
            GateInput(
                command=command,
                command_age_s=(now - command_received) if command_received else float("inf"),
                scan_ranges=scan_ranges,
                scan_angle_min=angle_min,
                scan_angle_increment=angle_increment,
                scan_range_min=range_min,
                scan_range_max=range_max,
                scan_age_s=(now - self._scan_received) if self._scan_received else float("inf"),
                motion_allowed=motion_allowed,
                motion_heartbeat_age_s=motion_heartbeat_age,
                emergency_stop=self._emergency_stop,
                emergency_stop_age_s=(now - self._emergency_received) if self._emergency_received else float("inf"),
                speed_scale=self._speed_scale if self._speed_scale is not None else 0.0,
                speed_scale_age_s=(now - self._speed_scale_received) if self._speed_scale_received else float("inf"),
            ),
            self._config,
        )

        exclusive = self._output_is_exclusive()
        ready = (
            exclusive
            and self._scan_received > 0
            and now - self._scan_received <= self._config.scan_timeout_s
            and self._scan_has_valid_measurement()
            and self._emergency_stop is False
            and self._emergency_received > 0
            and now - self._emergency_received <= self._config.heartbeat_timeout_s
            and self._speed_scale is not None
            and 0.0 < self._speed_scale <= 1.0
            and now - self._speed_scale_received <= self._config.heartbeat_timeout_s
        )
        if not exclusive:
            result = type(result)(Velocity(), False, "底盘 /cmd_vel 必须只有安全节点一个发布者")
        self._last_reason = result.reason

        output = Twist()
        output.linear.x = result.velocity.linear_x
        output.angular.z = result.velocity.angular_z
        self._cmd_pub.publish(output)
        ready_message = Bool()
        ready_message.data = ready
        self._ready_pub.publish(ready_message)
        self._publish_preflight_status(now, ready, exclusive)

    def _publish_preflight_status(self, now: float, ready: bool, exclusive: bool) -> None:
        if ready:
            reason = "安全门控就绪"
        elif self._scan_received <= 0 or now - self._scan_received > self._config.scan_timeout_s:
            reason = "等待新鲜雷达数据"
        elif not self._scan_has_valid_measurement():
            reason = "等待有效雷达测距"
        elif self._emergency_stop is None or now - self._emergency_received > self._config.heartbeat_timeout_s:
            reason = "急停状态心跳不可用"
        elif self._emergency_stop:
            reason = "急停已触发"
        elif self._speed_scale is None or now - self._speed_scale_received > self._config.heartbeat_timeout_s:
            reason = "等待区域限速心跳"
        elif not 0.0 < self._speed_scale <= 1.0:
            reason = "机器人 map 位姿无效，无法计算区域限速"
        elif not exclusive:
            reason = self._last_reason
        else:
            reason = "等待安全状态稳定"
        message = String()
        message.data = reason
        self._status_pub.publish(message)

    def _scan_has_valid_measurement(self) -> bool:
        scan = self._scan
        if scan is None:
            return False
        ranges, angle_min, angle_increment, range_min, range_max, _received = scan
        if not all(math.isfinite(value) for value in (angle_min, angle_increment, range_min, range_max)):
            return False
        if range_min < 0.0 or range_max <= range_min or angle_increment == 0.0:
            return False
        return any(math.isfinite(distance) and range_min <= distance <= range_max for distance in ranges)

    def _publish_zero_command(self) -> None:
        output = Twist()
        self._cmd_pub.publish(output)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetyNode()
    try:
        rclpy.spin(node)
    finally:
        try:
            node._publish_zero_command()
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
