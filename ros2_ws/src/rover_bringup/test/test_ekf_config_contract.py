from pathlib import Path

import yaml


PACKAGE_DIR = Path(__file__).resolve().parents[1]


def test_ekf_parameters_target_the_node_started_by_mapping_launch():
    parameters = yaml.safe_load((PACKAGE_DIR / "params" / "ekf.yaml").read_text())
    launch_source = (PACKAGE_DIR / "launch" / "mapping.launch.py").read_text()

    assert "rover_ekf" in parameters
    assert 'name="rover_ekf"' in launch_source
