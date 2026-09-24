from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    navigation_share = Path(get_package_share_directory("rover_navigation"))
    params = str(navigation_share / "params" / "nav2_params.yaml")
    tf_remappings = [("/tf", "tf"), ("/tf_static", "tf_static")]
    lifecycle_nodes = [
        "controller_server",
        "smoother_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "waypoint_follower",
        "velocity_smoother",
    ]
    actions = [
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            parameters=[params],
            remappings=tf_remappings + [("cmd_vel", "cmd_vel_nav")],
            output="screen",
        ),
        Node(
            package="nav2_smoother",
            executable="smoother_server",
            name="smoother_server",
            parameters=[params],
            remappings=tf_remappings,
            output="screen",
        ),
        Node(
            package="nav2_planner",
            executable="planner_server",
            name="planner_server",
            parameters=[params],
            remappings=tf_remappings,
            output="screen",
        ),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            parameters=[params],
            remappings=tf_remappings + [("cmd_vel", "cmd_vel_candidate")],
            output="screen",
        ),
        Node(
            package="nav2_bt_navigator",
            executable="bt_navigator",
            name="bt_navigator",
            parameters=[params],
            remappings=tf_remappings,
            output="screen",
        ),
        Node(
            package="nav2_waypoint_follower",
            executable="waypoint_follower",
            name="waypoint_follower",
            parameters=[params],
            remappings=tf_remappings,
            output="screen",
        ),
        Node(
            package="nav2_velocity_smoother",
            executable="velocity_smoother",
            name="velocity_smoother",
            parameters=[params],
            remappings=tf_remappings + [("cmd_vel", "cmd_vel_nav"), ("cmd_vel_smoothed", "cmd_vel_candidate")],
            output="screen",
        ),
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="lifecycle_manager_navigation",
            parameters=[{"use_sim_time": False, "autostart": True, "node_names": lifecycle_nodes}],
            output="screen",
        ),
        Node(
            package="rover_safety",
            executable="safety_node",
            name="rover_safety",
            parameters=[str(Path(get_package_share_directory("rover_safety")) / "params" / "safety.yaml")],
            output="screen",
        ),
        Node(
            package="rover_navigation",
            executable="navigation_node",
            name="rover_navigation",
            parameters=[str(navigation_share / "params" / "navigation.yaml")],
            output="screen",
        ),
    ]
    return LaunchDescription(actions)
