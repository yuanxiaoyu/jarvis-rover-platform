import rclpy
from rclpy.node import Node


class BringupNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_bringup")
        self.get_logger().info("Rover bringup scaffold active.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BringupNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()

