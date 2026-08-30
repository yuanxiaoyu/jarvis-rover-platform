from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    use_keepout = LaunchConfiguration("use_keepout")
    use_virtual_walls = LaunchConfiguration("use_virtual_walls")

    mapping_launch = PathJoinSubstitution(
        [FindPackageShare("rover_bringup"), "launch", "mapping.launch.py"]
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_keepout", default_value="true"),
            DeclareLaunchArgument("use_virtual_walls", default_value="true"),
            IncludeLaunchDescription(PythonLaunchDescriptionSource(mapping_launch)),
            Node(package="rover_bringup", executable="bringup_node", name="bringup"),
            Node(
                package="rover_navigation",
                executable="navigation_node",
                name="navigation_node",
                parameters=[
                    {"use_keepout": use_keepout, "use_virtual_walls": use_virtual_walls},
                    "/workspace/ros2_ws/src/rover_navigation/params/navigation.yaml",
                ],
            ),
            Node(package="rover_ai_bridge", executable="ai_bridge_node", name="ai_bridge_node"),
            Node(
                package="rover_voice_bridge",
                executable="voice_bridge_node",
                name="voice_bridge_node",
            ),
        ]
    )
