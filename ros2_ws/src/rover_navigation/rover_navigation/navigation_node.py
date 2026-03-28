import rclpy
from rclpy.node import Node


class NavigationNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_navigation")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("goal_topic", "/goal_pose")
        self.declare_parameter("use_keepout", True)
        self.declare_parameter("use_virtual_walls", True)
        self.get_logger().info("rover_navigation ready to translate semantic tasks into Nav2 goals.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = NavigationNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
