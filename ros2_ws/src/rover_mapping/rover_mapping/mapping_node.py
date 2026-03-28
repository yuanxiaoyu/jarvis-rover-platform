import rclpy
from rclpy.node import Node


class MappingNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_mapping")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("map_topic", "/map")
        self.declare_parameter("session_dir", "/workspace/data/maps")
        self.get_logger().info("rover_mapping ready for 2D lidar mapping + 3D semantic reconstruction.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MappingNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
