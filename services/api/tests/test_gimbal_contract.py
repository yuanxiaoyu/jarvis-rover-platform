import pytest
from pydantic import ValidationError

from app.models.hardware import GimbalCommand


@pytest.mark.parametrize("angle", [-90, -60, 0, 20])
def test_gimbal_tilt_accepts_yahboom_safe_angles(angle: int) -> None:
    assert GimbalCommand(tilt_deg=angle).tilt_deg == angle


@pytest.mark.parametrize("angle", [-91, 21, 45, 90])
def test_gimbal_tilt_rejects_angles_outside_yahboom_safe_range(angle: int) -> None:
    with pytest.raises(ValidationError):
        GimbalCommand(tilt_deg=angle)
