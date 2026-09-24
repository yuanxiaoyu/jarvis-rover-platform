"""Passive ROS diagnostics node for the host-local voice service."""

import rclpy
from rclpy.node import Node


class VoiceBridgeNode(Node):
    """Expose configuration diagnostics without handling audio or commands."""

    def __init__(self) -> None:
        super().__init__("rover_voice_bridge")
        self.declare_parameter("adapter", "host_gateway_passive")
        self.declare_parameter("wake_word", "贾维斯")
        self.declare_parameter("enable_wake_word", False)
        self.declare_parameter("enable_asr", False)
        self.declare_parameter("enable_tts", False)
        self.get_logger().info("rover_voice_bridge is passive; audio and gateway stay outside ROS.")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
