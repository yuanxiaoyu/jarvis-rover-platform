from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_navigation = LaunchConfiguration("enable_navigation")
    bringup_share = Path(get_package_share_directory("rover_bringup"))
    mapping_share = Path(get_package_share_directory("rover_mapping"))
    navigation_share = Path(get_package_share_directory("rover_navigation"))

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("session_dir", default_value="/workspace/data/maps"),
            DeclareLaunchArgument("enable_navigation", default_value="false"),
            Node(
                package="rover_bringup",
                executable="sensor_stamp_relay",
                name="rover_sensor_stamp_relay",
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="imu_complementary_filter",
                executable="complementary_filter_node",
                name="imu_complementary_filter",
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[("imu/data_raw", "/imu_normalized"), ("imu/data", "/imu/data")],
                output="screen",
            ),
            Node(
                package="robot_localization",
                executable="ekf_node",
                name="rover_ekf",
                parameters=[str(bringup_share / "params" / "ekf.yaml"), {"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_footprint_to_base_link",
                arguments=["0", "0", "0.05", "0", "0", "0", "base_footprint", "base_link"],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_link_to_laser_frame",
                arguments=["-0.0046412", "0", "0.094079", "0", "0", "0", "base_link", "laser_frame"],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_link_to_imu_frame",
                arguments=["-0.002999", "-0.0030001", "0.031701", "0", "0", "0", "base_link", "imu_frame"],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                parameters=[str(mapping_share / "params" / "slam_toolbox_online_async.yaml"), {"use_sim_time": use_sim_time}],
                output="screen",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(str(navigation_share / "launch" / "navigation.launch.py")),
                condition=IfCondition(enable_navigation),
            ),
        ]
    )
