from geometry_msgs.msg import Twist

from rover_safety.gate import CommandGate


def twist(x: float, z: float) -> Twist:
    message = Twist()
    message.linear.x = x
    message.angular.z = z
    return message


def test_gate_outputs_zero_until_mapping_allows_motion():
    gate = CommandGate(timeout_s=0.25)
    gate.update_input(twist(0.4, 0.2), now=10.0)

    assert gate.output(now=10.1).linear.x == 0.0
    gate.set_motion_allowed(True)
    assert gate.output(now=10.2).linear.x == 0.4


def test_stale_input_and_estop_output_zero():
    gate = CommandGate(timeout_s=0.25)
    gate.set_motion_allowed(True)
    gate.update_input(twist(0.4, 0.2), now=10.0)

    assert gate.output(now=10.3).linear.x == 0.0
    gate.update_input(twist(0.4, 0.2), now=11.0)
    gate.set_emergency_stop(True)
    assert gate.output(now=11.01).angular.z == 0.0


def test_clear_estop_does_not_enable_motion_by_itself():
    gate = CommandGate(timeout_s=0.25)
    gate.set_emergency_stop(True)
    gate.set_emergency_stop(False)

    assert gate.output(now=1.0).linear.x == 0.0


def test_stale_command_locks_motion_without_recent_input():
    gate = CommandGate(timeout_s=0.25)
    gate.set_motion_allowed(True)
    gate.update_input(twist(0.4, 0.2), now=10.0)

    assert gate.output(now=10.3).linear.x == 0.0


def test_output_is_a_copy_of_the_input():
    gate = CommandGate(timeout_s=0.25)
    command = twist(0.4, 0.2)
    gate.update_input(command, now=10.0)
    gate.set_motion_allowed(True)

    output = gate.output(now=10.1)
    output.linear.x = 0.0

    assert gate.output(now=10.2).linear.x == 0.4


def test_motion_permission_expires_without_fresh_status():
    gate = CommandGate(timeout_s=1.0, motion_timeout_s=0.5)
    gate.set_motion_allowed(True, now=10.0)
    gate.update_input(twist(0.4, 0.2), now=10.0)

    assert gate.output(now=10.4).linear.x == 0.4
    assert gate.output(now=10.6).linear.x == 0.0


def test_reenable_requires_a_new_command_after_lock():
    gate = CommandGate(timeout_s=0.25)
    gate.set_motion_allowed(True)
    gate.update_input(twist(0.4, 0.2), now=10.0)
    gate.set_motion_allowed(False, now=10.1)
    gate.set_motion_allowed(True, now=10.2)

    assert gate.output(now=10.2).linear.x == 0.0
    gate.update_input(twist(0.2, 0.1), now=10.3)
    assert gate.output(now=10.3).linear.x == 0.2
