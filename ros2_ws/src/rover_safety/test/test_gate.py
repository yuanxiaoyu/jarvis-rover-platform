import math
from types import SimpleNamespace

from rover_safety.gate import GateConfig, GateInput, Velocity, evaluate, select_command_source


def make_input(**updates):
    scan = [2.0] * 360
    values = {
        "command": Velocity(0.1, 0.0),
        "command_age_s": 0.0,
        "scan_ranges": scan,
        "scan_angle_min": -math.pi,
        "scan_angle_increment": 2.0 * math.pi / len(scan),
        "scan_range_min": 0.1,
        "scan_range_max": 10.0,
        "scan_age_s": 0.0,
        "motion_allowed": True,
        "motion_heartbeat_age_s": 0.0,
        "emergency_stop": False,
        "emergency_stop_age_s": 0.0,
        "speed_scale": 1.0,
        "speed_scale_age_s": 0.0,
    }
    values.update(updates)
    return GateInput(**values)


def test_gate_allows_fresh_slow_command_in_clear_scan():
    result = evaluate(make_input())

    assert result.ready is True
    assert result.velocity == Velocity(0.1, 0.0)


def test_gate_fails_closed_without_fresh_motion_heartbeat():
    result = evaluate(make_input(motion_heartbeat_age_s=0.6))

    assert result.ready is False
    assert result.velocity == Velocity()


def test_gate_fails_closed_when_estop_is_active_or_unknown():
    for estop in (True, None):
        result = evaluate(make_input(emergency_stop=estop))
        assert result.ready is False
        assert result.velocity == Velocity()


def test_gate_stops_forward_motion_before_front_obstacle():
    scan = [2.0] * 360
    scan[175] = 0.3  # zero radians is the forward direction
    result = evaluate(make_input(scan_ranges=scan))

    assert result.ready is True
    assert result.velocity.linear_x == 0.0


def test_gate_stops_reverse_motion_before_rear_obstacle():
    scan = [2.0] * 360
    scan[0] = 0.3  # pi radians is behind the rover
    result = evaluate(make_input(command=Velocity(-0.1, 0.0), scan_ranges=scan))

    assert result.velocity.linear_x == 0.0


def test_gate_stops_on_stale_command_scan_or_empty_scan():
    for values in (
        {"command_age_s": 0.3},
        {"scan_age_s": 0.4},
        {"scan_ranges": []},
        {"scan_ranges": [math.inf] * 360},
    ):
        result = evaluate(make_input(**values))
        assert result.ready is False
        assert result.velocity == Velocity()


def test_gate_clamps_velocity_to_rover_limits():
    result = evaluate(make_input(command=Velocity(1.0, -2.0)), GateConfig())

    assert result.velocity == Velocity(0.18, -0.6)


def test_gate_applies_slow_zone_speed_scale_and_fails_closed_if_stale():
    result = evaluate(make_input(speed_scale=0.5, command=Velocity(0.1, 0.2)))
    stale = evaluate(make_input(speed_scale_age_s=0.6))

    assert result.velocity == Velocity(0.09, 0.2)
    assert stale.velocity == Velocity()


def test_command_source_arbitration_never_falls_back_to_teleop_during_exploration():
    assert select_command_source("exploring", True) == ("navigation", True)
    assert select_command_source("exploring", False) == ("navigation", False)
    assert select_command_source("starting", True) == ("navigation", False)
    assert select_command_source("paused", True) == ("navigation", False)


def test_command_source_allows_teleop_only_when_exploration_is_idle_or_complete():
    assert select_command_source("idle", False) == ("teleop", True)
    assert select_command_source("complete", False) == ("teleop", True)
    assert select_command_source("stopped", False) == (None, False)
    assert select_command_source("error", False) == ("navigation", False)
    assert select_command_source("unknown", True) == (None, False)


def test_safety_node_latches_estop_and_immediately_publishes_zero():
    import pytest

    pytest.importorskip("rclpy")
    from rover_safety.safety_node import SafetyNode
    from std_msgs.msg import Bool

    zero_publishes = []
    node = SimpleNamespace(
        _emergency_stop=False,
        _emergency_stop_latched=False,
        _emergency_received=0.0,
        _motion_allowed=True,
        _motion_received=0.0,
        _publish_zero_command=lambda: zero_publishes.append(True),
    )

    SafetyNode._on_emergency_stop(node, Bool(data=True))
    SafetyNode._on_emergency_stop(node, Bool(data=False))
    SafetyNode._on_motion_allowed(node, Bool(data=False))

    assert node._emergency_stop_latched is True
    assert node._emergency_stop is True
    assert node._motion_allowed is False
    assert len(zero_publishes) == 2
