from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    use_keepout = LaunchConfiguration("use_keepout")
    use_virtual_walls = LaunchConfiguration("use_virtual_walls")
    use_garbage_detection = LaunchConfiguration("use_garbage_detection")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_keepout", default_value="true"),
            DeclareLaunchArgument("use_virtual_walls", default_value="true"),
            DeclareLaunchArgument("use_garbage_detection", default_value="false"),
            Node(package="rover_bringup", executable="bringup_node", name="bringup"),
            Node(package="rover_mapping", executable="mapping_node", name="mapping_node"),
            Node(
                package="rover_navigation",
                executable="navigation_node",
                name="navigation_node",
                parameters=[
                    {"use_keepout": use_keepout, "use_virtual_walls": use_virtual_walls},
                    "/workspace/ros2_ws/src/rover_navigation/params/navigation.yaml",
                ],
            ),
            Node(package="rover_safety", executable="safety_node", name="safety_node"),
            Node(package="rover_ai_bridge", executable="ai_bridge_node", name="ai_bridge_node"),
            Node(package="rover_voice_bridge", executable="voice_bridge_node", name="voice_bridge_node"),
            Node(
                package="rover_vision",
                executable="garbage_detection_node",
                name="garbage_detection_node",
                condition=IfCondition(use_garbage_detection),
                parameters=["/workspace/ros2_ws/src/rover_vision/params/vision.yaml"],
            ),
        ]
    )
