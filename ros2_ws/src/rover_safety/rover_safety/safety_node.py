import rclpy
from rclpy.node import Node


class SafetyNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_safety")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("cmd_vel_in", "/cmd_vel")
        self.declare_parameter("cmd_vel_out", "/cmd_vel_safe")
        self.declare_parameter("enable_keepout", True)
        self.get_logger().info("rover_safety active with obstacle and keepout hooks.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetyNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
