import rclpy
from rclpy.node import Node


class AiBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_ai_bridge")
        self.declare_parameter("planner_mode", "structured_intent")
        self.declare_parameter("api_base_url", "http://127.0.0.1:8001")
        self.get_logger().info("rover_ai_bridge ready to turn AI prompts into task plans.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AiBridgeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
