import rclpy
from rclpy.node import Node


class VoiceBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("rover_voice_bridge")
        self.declare_parameter("adapter", "mock")
        self.declare_parameter("wake_word", "贾维斯")
        self.declare_parameter("enable_wake_word", False)
        self.declare_parameter("enable_asr", False)
        self.declare_parameter("enable_tts", False)
        self.declare_parameter("whole_home_scan_intent", "whole_home_garbage_scan")
        self.declare_parameter("whole_home_scan_phrase_hint", "扫描整个房屋，发现有垃圾请拍照告诉我")
        self.declare_parameter("forward_command_api_path", "/api/v1/voice/command")
        self.get_logger().info(
            "rover_voice_bridge ready with optional sherpa-onnx path and whole-home garbage scan intent."
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceBridgeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
