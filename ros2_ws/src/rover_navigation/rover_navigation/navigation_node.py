from __future__ import annotations

import json
import math
import time

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Imu
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener

from rover_navigation.frontier import Frontier, FrontierGrid, find_frontiers


NAV2_LIFECYCLE_NODES = (
    "controller_server",
    "smoother_server",
    "planner_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
)
_LIFECYCLE_ACTIVE = 3


def missing_nav2_lifecycle_nodes(states: dict[str, int | None]) -> tuple[str, ...]:
    """List Nav2 servers that are not active yet, even if action endpoints exist."""
    return tuple(name for name in NAV2_LIFECYCLE_NODES if states.get(name) != _LIFECYCLE_ACTIVE)


class NavigationNode(Node):
    """Nav2 action client and frontier exploration state machine."""

    def __init__(self) -> None:
        super().__init__("rover_navigation")
        self.declare_parameter("map_topic", "/navigation/map")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("navigate_action", "/navigate_to_pose")
        self.declare_parameter("safety_ready_topic", "/rover_safety/ready")
        self.declare_parameter("map_timeout_s", 5.0)
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("imu_timeout_s", 0.5)
        self.declare_parameter("startup_timeout_s", 45.0)
        self.declare_parameter("goal_timeout_s", 30.0)
        self.declare_parameter("cancel_timeout_s", 2.0)
        self.declare_parameter("max_failed_frontiers", 40)

        self._grid: FrontierGrid | None = None
        self._grid_received = 0.0
        self._imu_received = 0.0
        self._safety_ready = False
        self._safety_received = 0.0
        self._safety_message = "等待安全门控状态"
        self._nav2_lifecycle_clients = {
            name: self.create_client(GetState, f"/{name}/get_state")
            for name in NAV2_LIFECYCLE_NODES
        }
        self._nav2_lifecycle_states: dict[str, int | None] = {name: None for name in NAV2_LIFECYCLE_NODES}
        self._nav2_lifecycle_received = {name: 0.0 for name in NAV2_LIFECYCLE_NODES}
        self._nav2_lifecycle_pending: set[str] = set()
        self._nav2_lifecycle_poll_at = 0.0
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._action_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action").value),
        )
        self._status_pub = self.create_publisher(String, "/rover_navigation/status", 10)
        self._motion_pub = self.create_publisher(Bool, "/rover_navigation/motion_allowed", 10)
        self._estop_pub = self.create_publisher(Bool, "/rover_navigation/emergency_stop", 10)
        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            OccupancyGrid,
            str(self.get_parameter("map_topic").value),
            self._on_map,
            map_qos,
        )
        self.create_subscription(Bool, str(self.get_parameter("safety_ready_topic").value), self._on_safety_ready, 10)
        self.create_subscription(String, "/rover_safety/status", self._on_safety_status, 10)
        self.create_subscription(Imu, str(self.get_parameter("imu_topic").value), self._on_imu, 10)
        self.create_service(Trigger, "/rover_navigation/start_exploration", self._start)
        self.create_service(Trigger, "/rover_navigation/pause_exploration", self._pause)
        self.create_service(Trigger, "/rover_navigation/resume_exploration", self._resume)
        self.create_service(Trigger, "/rover_navigation/stop_exploration", self._stop)

        self._state = "idle"
        self._message = "待命"
        self._state_since = time.monotonic()
        self._stop_latched = False
        self._goal_handle = None
        self._goal_result_future = None
        self._goal_pending = False
        self._cancel_pending = False
        self._cancel_when_accepted = False
        self._cancel_started = 0.0
        self._skip_active_on_cancel = False
        self._active_frontier: Frontier | None = None
        self._excluded: set[tuple[float, float]] = set()
        self._completed = 0
        self._failed = 0
        self._remaining = 0
        self._goal_started = 0.0
        self._tick_timer = self.create_timer(0.1, self._tick)
        self._status_timer = self.create_timer(0.25, self._publish_status)
        self.get_logger().info("Frontier exploration is ready; all motion is sent through the Nav2 action server.")

    def _on_map(self, message: OccupancyGrid) -> None:
        info = message.info
        expected = int(info.width) * int(info.height)
        if expected < 1 or expected > 1_000_000 or len(message.data) != expected or info.resolution <= 0:
            return
        orientation = info.origin.orientation
        yaw = math.atan2(
            2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
        )
        self._grid = FrontierGrid(
            width=int(info.width),
            height=int(info.height),
            resolution=float(info.resolution),
            origin_x=float(info.origin.position.x),
            origin_y=float(info.origin.position.y),
            origin_yaw=yaw,
            data=tuple(int(value) for value in message.data),
        )
        self._grid_received = time.monotonic()

    def _on_safety_ready(self, message: Bool) -> None:
        self._safety_ready = bool(message.data)
        self._safety_received = time.monotonic()

    def _on_imu(self, message: Imu) -> None:
        orientation = message.orientation
        quaternion_norm = math.sqrt(
            orientation.x * orientation.x + orientation.y * orientation.y
            + orientation.z * orientation.z + orientation.w * orientation.w
        )
        self._imu_received = time.monotonic() if math.isfinite(quaternion_norm) and quaternion_norm > 1e-3 else 0.0

    def _on_safety_status(self, message: String) -> None:
        self._safety_message = str(message.data)

    def _start(self, _request, response):
        if self._state in {"starting", "exploring", "paused", "stopping"} \
                or self._goal_handle is not None or self._goal_pending or self._cancel_pending:
            response.success = False
            response.message = "自主探索任务已在运行"
            return response
        self._excluded.clear()
        self._completed = 0
        self._failed = 0
        self._remaining = 0
        self._active_frontier = None
        self._goal_handle = None
        self._goal_pending = False
        self._cancel_pending = False
        self._cancel_when_accepted = False
        self._stop_latched = False
        self._set_state("starting", "等待 Nav2、SLAM 地图与安全门控就绪")
        response.success = True
        response.message = "自主探索已排队，完成预检后开始移动"
        return response

    def _pause(self, _request, response):
        if self._state not in {"starting", "exploring"}:
            response.success = False
            response.message = "当前没有可暂停的自主探索任务"
            return response
        self._set_state("paused", "自主探索已暂停")
        self._cancel_goal()
        response.success = True
        response.message = "已暂停导航并关闭运动许可"
        return response

    def _resume(self, _request, response):
        if self._state != "paused":
            response.success = False
            response.message = "自主探索不在暂停状态"
            return response
        self._set_state("starting", "恢复前重新检查导航与安全状态")
        self._state_since = time.monotonic()
        response.success = True
        response.message = "自主探索正在恢复预检"
        return response

    def _stop(self, _request, response):
        self._stop_latched = True
        self._set_state("stopped", "用户已停止自主探索")
        self._cancel_goal()
        response.success = True
        response.message = "已取消 Nav2 目标并关闭运动许可"
        return response

    def _tick(self) -> None:
        now = time.monotonic()
        self._refresh_nav2_lifecycle_states(now)
        self._publish_interlocks(now)

        if (self._cancel_pending or self._cancel_when_accepted) and self._cancel_started \
                and now - self._cancel_started > float(self.get_parameter("cancel_timeout_s").value):
            result_future = self._goal_result_future
            if result_future is None or not result_future.done():
                self._fail_cancel("Nav2 取消目标未确认；运动许可已锁止")

        if self._state not in {"starting", "exploring"}:
            return
        startup_elapsed = now - self._state_since
        if not self._map_fresh(now):
            if self._state == "exploring":
                self._fail("SLAM 地图停止更新，已取消导航")
            elif startup_elapsed > float(self.get_parameter("startup_timeout_s").value):
                self._fail("等待 SLAM 地图超时")
            return
        if not self._safety_fresh(now):
            if self._state == "exploring":
                self._fail(f"{self._safety_message}；已取消导航")
            elif startup_elapsed > float(self.get_parameter("startup_timeout_s").value):
                self._fail(f"安全预检失败：{self._safety_message}")
            return
        if not self._imu_fresh(now):
            if self._state == "exploring":
                self._fail("IMU 数据停止或无效，已取消导航并停车")
            elif startup_elapsed > float(self.get_parameter("startup_timeout_s").value):
                self._fail("等待有效 IMU 数据超时")
            return
        lifecycle_missing = self._nav2_lifecycle_missing(now)
        action_ready = self._action_client.server_is_ready()
        if lifecycle_missing or not action_ready:
            if lifecycle_missing:
                reason = "Nav2 生命周期节点未激活: " + ", ".join(lifecycle_missing)
            else:
                reason = "Nav2 NavigateToPose action 未就绪"
            if self._state == "exploring":
                self._fail(reason + "；已取消导航并停车")
            elif startup_elapsed > float(self.get_parameter("startup_timeout_s").value):
                self._fail("Nav2 启动预检失败：" + reason)
            return

        pose = self._robot_pose()
        if pose is None:
            if self._state == "exploring":
                self._fail("map 到 base_footprint 位姿丢失，已取消导航")
            elif startup_elapsed > float(self.get_parameter("startup_timeout_s").value):
                self._fail("等待有效 map 位姿超时")
            return
        if self._state == "starting":
            self._set_state("exploring", "正在选择可达的未知区域边界")
        if self._goal_handle is not None or self._goal_pending or self._cancel_pending:
            if (
                self._goal_started
                and now - self._goal_started > float(self.get_parameter("goal_timeout_s").value)
                and not self._skip_active_on_cancel
            ):
                self._skip_active_on_cancel = True
                self._message = "前沿导航超时，正在取消该目标并尝试其他区域"
                self._cancel_goal()
                self._publish_interlocks(now)
            return
        if self._failed >= int(self.get_parameter("max_failed_frontiers").value):
            self._set_state("complete", "已达到不可达前沿重试上限；未探索区域仍保留在地图中")
            return
        grid = self._grid
        assert grid is not None
        frontiers = find_frontiers(grid, pose[0], pose[1], excluded_world=tuple(self._excluded))
        self._remaining = len(frontiers)
        if not frontiers:
            summary = f"探索结束：完成 {self._completed} 个前沿，跳过 {self._failed} 个不可达前沿"
            self._set_state("complete", summary)
            return
        self._send_goal(frontiers[0], pose)

    def _refresh_nav2_lifecycle_states(self, now: float) -> None:
        if now - self._nav2_lifecycle_poll_at < 0.5:
            return
        self._nav2_lifecycle_poll_at = now
        for name, client in self._nav2_lifecycle_clients.items():
            if name in self._nav2_lifecycle_pending:
                continue
            if not client.service_is_ready():
                self._nav2_lifecycle_states[name] = None
                self._nav2_lifecycle_received[name] = 0.0
                continue
            self._nav2_lifecycle_pending.add(name)
            future = client.call_async(GetState.Request())
            future.add_done_callback(lambda completed, node_name=name: self._on_nav2_lifecycle_state(completed, node_name))

    def _on_nav2_lifecycle_state(self, future, node_name: str) -> None:
        self._nav2_lifecycle_pending.discard(node_name)
        try:
            response = future.result()
            self._nav2_lifecycle_states[node_name] = int(response.current_state.id)
        except Exception as exc:
            self._nav2_lifecycle_states[node_name] = None
            self.get_logger().warning(f"Could not read Nav2 lifecycle state for {node_name}: {exc}")
        self._nav2_lifecycle_received[node_name] = time.monotonic()

    def _nav2_lifecycle_missing(self, now: float) -> tuple[str, ...]:
        states = {
            name: state if now - self._nav2_lifecycle_received[name] <= 1.0 else None
            for name, state in self._nav2_lifecycle_states.items()
        }
        return missing_nav2_lifecycle_nodes(states)

    def _send_goal(self, frontier: Frontier, pose: tuple[float, float, float]) -> None:
        goal = NavigateToPose.Goal()
        target = PoseStamped()
        target.header.frame_id = str(self.get_parameter("map_frame").value)
        target.header.stamp = self.get_clock().now().to_msg()
        target.pose.position.x = frontier.x
        target.pose.position.y = frontier.y
        yaw = math.atan2(frontier.y - pose[1], frontier.x - pose[0])
        target.pose.orientation.z = math.sin(yaw / 2.0)
        target.pose.orientation.w = math.cos(yaw / 2.0)
        goal.pose = target
        self._active_frontier = frontier
        self._goal_pending = True
        self._goal_started = time.monotonic()
        self._message = "Nav2 正在前往下一个探索前沿"
        try:
            future = self._action_client.send_goal_async(goal, feedback_callback=self._on_feedback)
            future.add_done_callback(lambda completed: self._on_goal_response(completed, frontier))
        except Exception as exc:
            self._exclude(frontier, f"Nav2 目标请求失败: {exc}")
            self._clear_active(frontier)

    def _on_goal_response(self, future, frontier: Frontier) -> None:
        self._goal_pending = False
        try:
            handle = future.result()
        except Exception as exc:
            if self._state == "exploring":
                self._exclude(frontier, f"Nav2 目标请求失败: {exc}")
            self._clear_active(frontier)
            return
        if not handle.accepted:
            if self._state == "exploring":
                self._exclude(frontier, "Nav2 拒绝了该探索前沿")
            self._clear_active(frontier)
            return
        self._goal_handle = handle
        try:
            self._goal_result_future = handle.get_result_async()
            self._goal_result_future.add_done_callback(lambda completed: self._on_goal_result(completed, frontier))
        except Exception as exc:
            self._fail(f"无法监视 Nav2 目标结果: {exc}")
            return
        self._publish_interlocks()
        if self._goal_handle is handle and (self._state != "exploring" or self._cancel_when_accepted):
            self._request_goal_cancel(handle)

    def _on_goal_result(self, future, frontier: Frontier) -> None:
        if self._active_frontier != frontier:
            return
        timed_out = self._skip_active_on_cancel
        self._clear_active(frontier)
        if self._state in {"paused", "stopped", "stopping", "error"}:
            return
        try:
            result = future.result()
        except Exception as exc:
            self._exclude(frontier, f"Nav2 结果不可用: {exc}")
            return
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self._excluded.add((frontier.x, frontier.y))
            self._completed += 1
            self._message = f"已到达探索前沿，完成 {self._completed} 个，继续扩展地图"
        elif timed_out:
            self._exclude(frontier, "前沿导航超时，已跳过并继续尝试其他区域")
        else:
            self._exclude(frontier, "Nav2 无法到达该前沿，正在尝试其他区域")

    def _on_feedback(self, _feedback) -> None:
        return

    def _exclude(self, frontier: Frontier, message: str) -> None:
        self._excluded.add((frontier.x, frontier.y))
        self._excluded.update(getattr(frontier, "exclusion_points", ()))
        self._failed += 1
        self._message = message

    def _clear_active(self, frontier: Frontier) -> None:
        if self._active_frontier != frontier:
            return
        self._goal_handle = None
        self._goal_result_future = None
        self._goal_pending = False
        self._cancel_pending = False
        self._cancel_when_accepted = False
        self._cancel_started = 0.0
        self._skip_active_on_cancel = False
        self._active_frontier = None
        self._goal_started = 0.0
        self._publish_interlocks()

    def _cancel_goal(self) -> None:
        handle = self._goal_handle
        if handle is not None:
            self._request_goal_cancel(handle)
        elif self._goal_pending:
            self._cancel_when_accepted = True
            self._cancel_started = time.monotonic()

    def _request_goal_cancel(self, handle) -> None:
        if self._cancel_pending or self._goal_handle is not handle:
            return
        self._cancel_pending = True
        self._cancel_started = time.monotonic()
        try:
            future = handle.cancel_goal_async()
            future.add_done_callback(lambda completed: self._on_cancel_response(completed, handle))
        except Exception as exc:
            self.get_logger().error(f"Failed to cancel Nav2 goal: {exc}")
            self._fail_cancel("Nav2 目标取消失败；运动许可已锁止")

    def _on_cancel_response(self, future, handle) -> None:
        if self._goal_handle is not handle:
            return
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().error(f"Nav2 cancel response failed: {exc}")
            self._fail_cancel("Nav2 目标取消响应失败；运动许可已锁止")
            return
        if not response.goals_canceling:
            result_future = self._goal_result_future
            if result_future is not None and result_future.done():
                return
            self._fail_cancel("Nav2 未确认取消目标；运动许可已锁止")

    def _fail_cancel(self, message: str) -> None:
        self._cancel_pending = False
        self._cancel_started = 0.0
        self._stop_latched = True
        self._set_state("error", message)

    def _fail(self, message: str) -> None:
        self._stop_latched = True
        self._set_state("error", message)
        self._cancel_goal()

    def _map_fresh(self, now: float) -> bool:
        return self._grid is not None and now - self._grid_received <= float(self.get_parameter("map_timeout_s").value)

    def _safety_fresh(self, now: float) -> bool:
        return self._safety_ready and now - self._safety_received <= 0.5

    def _imu_fresh(self, now: float) -> bool:
        return self._imu_received > 0.0 and now - self._imu_received <= float(self.get_parameter("imu_timeout_s").value)

    def _robot_pose(self) -> tuple[float, float, float] | None:
        try:
            transform = self._tf_buffer.lookup_transform(
                str(self.get_parameter("map_frame").value),
                str(self.get_parameter("base_frame").value),
                rclpy.time.Time(),
            )
            translation = transform.transform.translation
            rotation = transform.transform.rotation
            yaw = math.atan2(
                2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
                1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z),
            )
            return float(translation.x), float(translation.y), yaw
        except Exception:
            return None

    def _set_state(self, state: str, message: str) -> None:
        self._state = state
        self._message = message
        self._state_since = time.monotonic()
        self._publish_interlocks()
        self._publish_status()

    def _publish_interlocks(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        motion = Bool()
        motion.data = (
            self._state == "exploring"
            and self._goal_handle is not None
            and not self._cancel_pending
            and not self._cancel_when_accepted
            and self._safety_fresh(now)
            and self._imu_fresh(now)
            and self._map_fresh(now)
        )
        self._motion_pub.publish(motion)
        emergency = Bool()
        emergency.data = self._stop_latched or self._state == "error"
        self._estop_pub.publish(emergency)

    def _publish_status(self) -> None:
        target = self._active_frontier
        payload = {
            "state": self._state,
            "message": self._message,
            "current_target": {"x": target.x, "y": target.y} if target else None,
            "completed_frontiers": self._completed,
            "failed_frontiers": self._failed,
            "remaining_frontiers": self._remaining,
            "updated_at": time.time(),
        }
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"))
        self._status_pub.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = NavigationNode()
    try:
        rclpy.spin(node)
    finally:
        try:
            node._stop_latched = True
            node._set_state("stopped", "导航节点正在关闭")
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
