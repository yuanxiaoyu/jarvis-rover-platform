from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    use_sim_time = LaunchConfiguration("use_sim_time")
    start_imu_filter = LaunchConfiguration("start_imu_filter")
    session_dir = LaunchConfiguration("session_dir")
    slam_params_file = LaunchConfiguration("slam_params_file")

    bringup_share = Path(get_package_share_directory("rover_bringup"))
    mapping_share = Path(get_package_share_directory("rover_mapping"))
    safety_share = Path(get_package_share_directory("rover_safety"))
    ekf_params_file = str(bringup_share / "params" / "ekf.yaml")
    safety_params_file = str(safety_share / "params" / "safety.yaml")
    default_slam_params_file = str(
        mapping_share / "params" / "slam_toolbox_online_async.yaml"
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("start_imu_filter", default_value="true"),
            DeclareLaunchArgument("session_dir", default_value="/workspace/data/maps"),
            DeclareLaunchArgument(
                "slam_params_file", default_value=default_slam_params_file
            ),
            Node(
                package="imu_complementary_filter",
                executable="complementary_filter_node",
                name="complementary_filter_node",
                condition=IfCondition(start_imu_filter),
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[
                    ("/imu/data_raw", "/imu"),
                    ("/imu/data", "/imu/data"),
                ],
                output="screen",
            ),
            Node(
                package="robot_localization",
                executable="ekf_node",
                name="ekf_node",
                parameters=[ekf_params_file, {"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="static_transform_publisher_base_footprint_to_base_link",
                arguments=[
                    "0",
                    "0",
                    "0.05",
                    "0",
                    "0",
                    "0",
                    "base_footprint",
                    "base_link",
                ],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="static_transform_publisher_base_link_to_laser_frame",
                arguments=[
                    "-0.0046412",
                    "0",
                    "0.094079",
                    "0",
                    "0",
                    "0",
                    "base_link",
                    "laser_frame",
                ],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="static_transform_publisher_base_link_to_imu_frame",
                arguments=[
                    "-0.002999",
                    "-0.0030001",
                    "0.031701",
                    "0",
                    "0",
                    "0",
                    "base_link",
                    "imu_frame",
                ],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="async_slam_toolbox_node",
                parameters=[slam_params_file, {"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="rover_mapping",
                executable="mapping_node",
                name="mapping_node",
                parameters=[
                    str(mapping_share / "params" / "mapping.yaml"),
                    {"session_dir": session_dir},
                ],
                output="screen",
            ),
            Node(
                package="rover_safety",
                executable="safety_node",
                name="safety_node",
                parameters=[safety_params_file],
                output="screen",
            ),
        ]
    )
