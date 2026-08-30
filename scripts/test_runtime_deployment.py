from pathlib import Path

import pytest

from runtime_deployment import (
    DeploymentConfigError,
    parse_env_file,
    render_unit,
    validate_runtime_env,
)


def test_parse_env_file_does_not_execute_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ROS_DOMAIN_ID=20\n"
        "ROVER_ROS_BRIDGE_ENABLED=true\n"
        "ROVER_ROS_BRIDGE_REQUIRED=true\n"
        "DANGEROUS=$(touch SHOULD_NOT_EXIST)\n"
        "# ignored=wrong\n",
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values["ROS_DOMAIN_ID"] == "20"
    assert values["DANGEROUS"] == "$(touch SHOULD_NOT_EXIST)"
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_validate_runtime_env_requires_domain_20_and_required_bridge():
    values = {
        "ROS_DOMAIN_ID": "30",
        "ROVER_ROS_BRIDGE_ENABLED": "false",
        "ROVER_ROS_BRIDGE_REQUIRED": "false",
    }

    with pytest.raises(DeploymentConfigError, match="ROS_DOMAIN_ID"):
        validate_runtime_env(values)


def test_validate_runtime_env_rejects_compose_profiles():
    values = {
        "ROS_DOMAIN_ID": "20",
        "ROVER_ROS_BRIDGE_ENABLED": "true",
        "ROVER_ROS_BRIDGE_REQUIRED": "true",
        "COMPOSE_PROFILES": "hardware,micro-ros-agent",
    }

    with pytest.raises(DeploymentConfigError, match="profile"):
        validate_runtime_env(values)


def test_render_unit_replaces_repo_dir_without_shell_evaluation(tmp_path):
    template = (
        "WorkingDirectory=@REPO_DIR@\n"
        "ExecStart=/usr/bin/docker compose --project-directory @REPO_DIR@ "
        "up --no-build rover-runtime\n"
    )

    rendered = render_unit(template, tmp_path)

    assert f"WorkingDirectory={tmp_path}" in rendered
    assert "@REPO_DIR@" not in rendered


def test_render_unit_rejects_whitespace_in_repo_dir():
    with pytest.raises(DeploymentConfigError, match="path"):
        render_unit("@REPO_DIR@", Path("/tmp/rover project"))


UNIT = Path(__file__).parents[1] / "deploy" / "jarvis-rover-runtime.service"
CHECK = Path(__file__).with_name("check_runtime_prerequisites.sh")
INSTALL = Path(__file__).with_name("install_rover_runtime_service.sh")
UNINSTALL = Path(__file__).with_name("uninstall_rover_runtime_service.sh")
ENTRYPOINT = Path(__file__).parents[1] / "docker" / "entrypoint.sh"
VERIFY_GRAPH = Path(__file__).with_name("verify_ros_graph.sh")
MEASURE_BASELINE = Path(__file__).with_name("measure_ros_baseline.sh")
COMPOSE = Path(__file__).parents[1] / "compose.yaml"
DOCKERFILE = Path(__file__).parents[1] / "docker" / "Dockerfile.runtime"
API_PYPROJECT = Path(__file__).parents[1] / "services" / "api" / "pyproject.toml"
API_SETUP = Path(__file__).parents[1] / "services" / "api" / "setup.py"
ROS_ROOT = Path(__file__).parents[1] / "ros2_ws" / "src"
SMOKE = Path(__file__).with_name("real_machine_smoke_test.sh")
MAKEFILE = Path(__file__).parents[1] / "Makefile"


def test_unit_manages_only_the_runtime_service():
    text = UNIT.read_text(encoding="utf-8")
    assert "Description=Jarvis Rover runtime" in text
    assert "After=docker.service network-online.target" in text
    assert "Requires=docker.service" in text
    assert "WantedBy=multi-user.target" in text
    assert "up --no-build" in text
    assert "rover-runtime" in text
    assert "--profile" not in text
    assert "yahboom-hardware" not in text
    assert "micro-ros-agent" not in text
    assert "docker compose down" not in text
    assert "/api/v1/mapping/start" not in text
    assert "/api/v1/mapping/resume" not in text


def test_unit_has_restart_and_safe_stop_policy():
    text = UNIT.read_text(encoding="utf-8")
    assert "Restart=on-failure" in text
    assert "TimeoutStopSec=45" in text
    assert "ExecStop=" in text
    assert "stop --timeout 30 rover-runtime" in text
    assert "COMPOSE_PROFILES=" in text


def test_prerequisite_checker_is_strict_and_does_not_start_services():
    text = CHECK.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "docker compose" in text
    assert "config" in text
    assert "ROS_DOMAIN_ID" in text
    assert "enable --now" not in text
    assert "compose up" not in text
    assert "compose start" not in text


def test_installer_checks_before_installing_and_never_enables_profiles():
    text = INSTALL.read_text(encoding="utf-8")
    assert "check_runtime_prerequisites.sh" in text
    assert '[[ -f "$CHECKER" ]]' in text
    assert '[[ -x "$CHECKER" ]]' not in text
    assert "docker compose" in text and "build rover-runtime" in text
    assert "daemon-reload" in text
    assert "enable --now jarvis-rover-runtime.service" in text
    assert "micro-ros-agent" not in text
    assert "mapping/start" not in text
    assert "mapping/resume" not in text


def test_uninstaller_does_not_delete_data_or_use_compose_down():
    text = UNINSTALL.read_text(encoding="utf-8")
    assert "disable --now jarvis-rover-runtime.service" in text
    assert "daemon-reload" in text
    assert "docker compose down" not in text
    assert "rm -rf" not in text
    assert "/workspace/data" not in text


def test_runtime_waits_for_mapping_service_before_starting_api():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    runtime = text[text.index("  runtime)"):]
    assert "ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS" in runtime
    assert "mapping service" in runtime.lower()
    assert "ros2 service list" in runtime
    assert runtime.index("mapping_pid=") < runtime.index("uvicorn")
    assert "mapping launch failed before API startup" in runtime


def test_compose_passes_startup_timeout_to_runtime():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "ROVER_MAPPING_STARTUP_TIMEOUT_SECONDS" in text
    assert "ROVER_RUNTIME_EVIDENCE_DIR" in text


def test_runtime_image_uses_non_editable_api_install():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "pip install --no-cache-dir /workspace/services/api" in text
    assert "pip install --no-cache-dir -e /workspace/services/api" not in text


def test_api_project_declares_setuptools_package_discovery():
    text = API_PYPROJECT.read_text(encoding="utf-8")
    assert "[tool.setuptools.packages.find]" in text
    assert 'where = ["."]' in text


def test_api_project_has_a_buildable_setuptools_fallback():
    text = API_SETUP.read_text(encoding="utf-8")
    assert "find_packages" in text
    assert 'name="rover-api"' in text


def test_runtime_image_builds_only_stage_one_ros_packages():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--packages-select rover_interfaces rover_mapping rover_safety rover_bringup" in text
    assert "colcon build --symlink-install\"" not in text


def test_stage_one_python_packages_use_ament_python_build_type():
    for package in ("rover_mapping", "rover_safety", "rover_bringup"):
        package_xml = (ROS_ROOT / package / "package.xml").read_text(encoding="utf-8")
        assert "<build_type>ament_python</build_type>" in package_xml


def test_safety_node_formats_state_change_log_before_logging():
    safety_node = (ROS_ROOT / "rover_safety" / "rover_safety" / "safety_node.py").read_text(
        encoding="utf-8"
    )
    assert 'self.get_logger().info("velocity gate: motion=%s' not in safety_node
    assert 'f"velocity gate: motion={state[0]}' in safety_node
    assert 'f"obstacle={state[2]} scan_ready={state[3]}"' in safety_node


def test_bringup_stage_one_does_not_require_unbuilt_stage_two_packages():
    package_xml = (ROS_ROOT / "rover_bringup" / "package.xml").read_text(encoding="utf-8")
    for package in ("rover_ai_bridge", "rover_navigation", "rover_voice_bridge"):
        assert f"<exec_depend>{package}</exec_depend>" not in package_xml


def test_entrypoint_initializes_ros_trace_variable_before_sourcing_setup():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    setup_index = text.index("source /opt/ros/humble/setup.bash")
    assert text.index("set +u", 0, setup_index) >= 0
    assert text.index("set -u", setup_index) > setup_index


def test_ros_scripts_disable_nounset_while_sourcing_setup():
    for script in (VERIFY_GRAPH, MEASURE_BASELINE):
        text = script.read_text(encoding="utf-8")
        setup_index = text.index("source /opt/ros/humble/setup.bash")
        assert text.index("set +u", 0, setup_index) >= 0
        assert text.index("set -u", setup_index) > setup_index


def test_ros_scripts_define_required_helpers():
    text = VERIFY_GRAPH.read_text(encoding="utf-8")
    assert "fail()" in text
    assert "errors=$((errors + 1))" in text


def test_graph_check_retries_ros_node_discovery_without_relaxing_counts():
    text = VERIFY_GRAPH.read_text(encoding="utf-8")
    assert "for _attempt in {1..5}" in text
    assert "ros2 node list --no-daemon --spin-time 2" in text
    assert "slam_toolbox" in text


def test_graph_check_allows_missing_map_tf_only_while_idle():
    text = VERIFY_GRAPH.read_text(encoding="utf-8")
    assert "mapping/status" in text
    assert 'mapping_state" == "0"' in text
    assert "return 1" in text
    assert "map -> odom is expected after mapping starts" in text
    assert "map -> odom" in text


def test_graph_check_idle_tf_warning_does_not_mark_graph_failed():
    text = VERIFY_GRAPH.read_text(encoding="utf-8")
    check_tf = text[text.index("check_tf() {"):text.index("mapping_status=")]
    assert 'fail "TF unavailable' not in check_tf
    assert "if ! grep -q \"At time\"" in check_tf
    assert "if ((rc != 0))" not in check_tf
    assert 'if ! check_tf odom base_footprint; then' in text
    assert 'if ! check_tf map odom; then' in text


def test_graph_check_retries_transient_tf_discovery():
    text = VERIFY_GRAPH.read_text(encoding="utf-8")
    check_tf = text[text.index("check_tf() {"):text.index("mapping_status=")]
    assert "for _attempt in {1..3}" in check_tf
    assert check_tf.count("tf2_echo") == 1


    probe = (Path(__file__).with_name("ros_graph_probe.py")).read_text(encoding="utf-8")
    assert "self.subscriptions =" not in probe
    assert "self._subscriptions =" in probe


def test_smoke_test_sources_ros_environment_for_cli_commands():
    text = SMOKE.read_text(encoding="utf-8")
    assert "source /opt/ros/humble/setup.bash" in text
    assert "source /workspace/ros2_ws/install/setup.bash" in text


def test_smoke_test_checks_locked_initial_state_and_never_starts_mapping():
    text = SMOKE.read_text(encoding="utf-8")
    assert "curl -fsS" in text
    assert "/api/v1/mapping" in text
    assert "motion_allowed" in text
    assert '"idle"' in text
    assert "mapping/start" not in text
    assert "mapping/resume" not in text
    assert "cmd_vel" in text
    assert "measure_ros_baseline.sh" in text
    assert "verify_ros_graph.sh" in text


def test_makefile_exposes_explicit_runtime_targets():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "runtime-prerequisites:" in text
    assert "runtime-install:" in text
    assert "runtime-uninstall:" in text
    assert "runtime-smoke:" in text
