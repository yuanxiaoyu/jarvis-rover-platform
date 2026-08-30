import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "launch" / "mapping.launch.py"
BRINGUP = ROOT / "launch" / "bringup.launch.py"
EKF = ROOT / "params" / "ekf.yaml"
SLAM = ROOT.parents[0] / "rover_mapping" / "params" / "slam_toolbox_online_async.yaml"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _node_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(_source(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Node"
    ]


def _keyword(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def test_mapping_launch_has_required_runtime_nodes():
    source = _source(LAUNCH)
    assert source.count('executable="async_slam_toolbox_node"') == 1
    assert "cartographer_node" not in source
    assert "slam_gmapping" not in source
    assert source.count('executable="ekf_node"') == 1
    assert source.count('executable="mapping_node"') == 1
    assert source.count('executable="safety_node"') == 1
    assert source.count('executable="static_transform_publisher"') == 3


def test_mapping_launch_uses_runtime_arguments_and_share_paths():
    source = _source(LAUNCH)
    assert 'DeclareLaunchArgument("use_sim_time", default_value="false")' in source
    assert 'DeclareLaunchArgument("start_imu_filter", default_value="true")' in source
    assert 'DeclareLaunchArgument("session_dir", default_value="/workspace/data/maps")' in source
    assert "get_package_share_directory" in source
    assert "FindPackageShare" not in source
    assert "slam_params_file" in source
    assert "safety_params_file" in source


def test_mapping_launch_configures_imu_filter_and_sensor_topics():
    source = _source(LAUNCH)
    assert 'name="complementary_filter_node"' in source
    assert 'package="imu_complementary_filter"' in source
    assert 'executable="complementary_filter_node"' in source
    assert 'condition=IfCondition(start_imu_filter)' in source
    assert '("/imu/data_raw", "/imu")' in source
    assert '("/imu/data", "/imu/data")' in source
    assert 'parameters=[{"use_sim_time": use_sim_time}]' in source
    assert 'name="ekf_node"' in source
    assert 'name="async_slam_toolbox_node"' in source


def test_mapping_launch_has_exact_static_transforms():
    source = _source(LAUNCH)
    transforms = [
        ('"0",', '"0.05"', '"base_footprint"', '"base_link"'),
        ('"-0.0046412"', '"0.094079"', '"base_link"', '"laser_frame"'),
        ('"-0.002999"', '"-0.0030001"', '"0.031701"', '"base_link"', '"imu_frame"'),
    ]
    for expected in transforms:
        assert all(part in source for part in expected)


def test_mapping_launch_forwards_session_dir_to_mapping_node():
    source = _source(LAUNCH)
    assert '"session_dir": session_dir' in source
    assert 'mapping_share / "params" / "mapping.yaml"' in source


def test_bringup_does_not_duplicate_mapping_runtime_nodes():
    source = _source(BRINGUP)
    assert "mapping.launch.py" in source
    assert 'executable="mapping_node"' not in source
    assert 'executable="safety_node"' not in source
    assert 'executable="ekf_node"' not in source
    assert 'executable="static_transform_publisher"' not in source


def test_mapping_launch_defines_share_path_for_each_parameter_package():
    source = _source(LAUNCH)
    assert 'get_package_share_directory("rover_bringup")' in source
    assert 'get_package_share_directory("rover_mapping")' in source
    assert 'get_package_share_directory("rover_safety")' in source


def test_ekf_contract():
    source = _source(EKF)
    assert "frequency: 30.0" in source
    assert "sensor_timeout: 0.20" in source
    assert "two_d_mode: true" in source
    assert "odom0: /odom_raw" in source
    assert "imu0: /imu/data" in source


def test_slam_contract():
    source = _source(SLAM)
    assert "use_sim_time: false" in source
    assert "odom_frame: odom" in source
    assert "map_frame: map" in source
    assert "base_frame: base_footprint" in source
    assert "scan_topic: /scan" in source
