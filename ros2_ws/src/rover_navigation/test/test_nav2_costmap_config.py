from pathlib import Path

import yaml


def test_local_costmap_dimensions_use_integer_ros_parameters():
    params_file = Path(__file__).resolve().parents[1] / "params" / "nav2_params.yaml"
    params = yaml.safe_load(params_file.read_text(encoding="utf-8"))
    local_costmap = params["local_costmap"]["local_costmap"]["ros__parameters"]

    assert type(local_costmap["width"]) is int
    assert type(local_costmap["height"]) is int


def test_nav2_uses_the_ekf_slam_odom_frame_and_filtered_odometry_topic():
    navigation_dir = Path(__file__).resolve().parents[1]
    source_dir = navigation_dir.parent
    nav2 = yaml.safe_load((navigation_dir / "params" / "nav2_params.yaml").read_text(encoding="utf-8"))
    ekf = yaml.safe_load((source_dir / "rover_bringup" / "params" / "ekf.yaml").read_text(encoding="utf-8"))
    slam = yaml.safe_load(
        (source_dir / "rover_mapping" / "params" / "slam_toolbox_online_async.yaml").read_text(encoding="utf-8")
    )

    odom_frame = ekf["rover_ekf"]["ros__parameters"]["odom_frame"]
    slam_params = slam["slam_toolbox"]["ros__parameters"]
    controller_params = nav2["controller_server"]["ros__parameters"]
    bt_params = nav2["bt_navigator"]["ros__parameters"]
    smoother_params = nav2["velocity_smoother"]["ros__parameters"]
    local_costmap = nav2["local_costmap"]["local_costmap"]["ros__parameters"]

    assert slam_params["odom_frame"] == odom_frame
    assert local_costmap["global_frame"] == odom_frame
    assert nav2["behavior_server"]["ros__parameters"]["global_frame"] == odom_frame
    assert controller_params["odom_topic"] == "/odometry/filtered"
    assert bt_params["odom_topic"] == "/odometry/filtered"
    assert smoother_params["odom_topic"] == "/odometry/filtered"


def test_exploration_freshness_uses_the_live_hardware_imu_stream():
    navigation_dir = Path(__file__).resolve().parents[1]
    params = yaml.safe_load((navigation_dir / "params" / "navigation.yaml").read_text(encoding="utf-8"))

    assert params["/**"]["ros__parameters"]["imu_topic"] == "/imu"


def test_stalled_frontier_is_skipped_after_a_bounded_navigation_timeout():
    navigation_dir = Path(__file__).resolve().parents[1]
    params = yaml.safe_load((navigation_dir / "params" / "navigation.yaml").read_text(encoding="utf-8"))

    assert 0 < params["/**"]["ros__parameters"]["goal_timeout_s"] <= 30.0
