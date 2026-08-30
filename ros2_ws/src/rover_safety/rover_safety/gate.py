"""Pure velocity gating rules used by the ROS safety node."""

from __future__ import annotations

from geometry_msgs.msg import Twist


class CommandGate:
    """Allow a recent command only while the runtime explicitly permits motion."""

    def __init__(self, timeout_s: float, motion_timeout_s: float | None = None) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if motion_timeout_s is not None and motion_timeout_s <= 0:
            raise ValueError("motion_timeout_s must be positive")
        self.timeout_s = timeout_s
        self.motion_timeout_s = motion_timeout_s
        self._input: Twist | None = None
        self._input_time: float | None = None
        self._motion_allowed = False
        self._motion_allowed_time: float | None = None
        self._emergency_stop = False

    def update_input(self, command: Twist, *, now: float) -> None:
        if self._emergency_stop:
            return
        self._input = _copy_twist(command)
        self._input_time = float(now)

    def set_motion_allowed(self, allowed: bool, *, now: float | None = None) -> None:
        self._motion_allowed = bool(allowed) and not self._emergency_stop
        self._motion_allowed_time = None if now is None else float(now)
        if not self._motion_allowed:
            self._input = None
            self._input_time = None

    def set_emergency_stop(self, active: bool) -> None:
        self._emergency_stop = bool(active)
        self._motion_allowed = False if self._emergency_stop else self._motion_allowed
        self._motion_allowed_time = None if self._emergency_stop else self._motion_allowed_time
        # Entering or leaving an e-stop invalidates the previous command.
        self._input = None
        self._input_time = None

    @property
    def motion_allowed(self) -> bool:
        return self._motion_allowed

    @property
    def emergency_stop(self) -> bool:
        return self._emergency_stop

    def output(self, *, now: float) -> Twist:
        if not self._motion_allowed or self._emergency_stop:
            return Twist()
        if (
            self._motion_allowed_time is not None
            and self.motion_timeout_s is not None
            and (float(now) - self._motion_allowed_time < 0.0
                 or float(now) - self._motion_allowed_time > self.motion_timeout_s)
        ):
            return Twist()
        if self._input is None or self._input_time is None:
            return Twist()
        age = float(now) - self._input_time
        if age < 0.0 or age > self.timeout_s:
            return Twist()
        return _copy_twist(self._input)


def _copy_twist(command: Twist) -> Twist:
    result = Twist()
    result.linear.x = command.linear.x
    result.linear.y = command.linear.y
    result.linear.z = command.linear.z
    result.angular.x = command.angular.x
    result.angular.y = command.angular.y
    result.angular.z = command.angular.z
    return result
