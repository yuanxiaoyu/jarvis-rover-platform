import math

from app.models.map import Coordinate2D, GridOrigin
from app.models.zone import Zone, ZoneType
from app.services.navigation_map import overlay_restricted_zones, slow_zone_scale_at


def test_keepout_overlay_marks_only_navigation_copy_as_lethal():
    zone = Zone(
        zone_id="blocked",
        name="Blocked",
        type=ZoneType.KEEP_OUT,
        points=[
            Coordinate2D(x=0.3, y=0.3),
            Coordinate2D(x=0.6, y=0.3),
            Coordinate2D(x=0.6, y=0.6),
            Coordinate2D(x=0.3, y=0.6),
        ],
    )
    source = [0] * 100

    navigation = overlay_restricted_zones(source, 10, 10, 0.1, GridOrigin(), [zone], clearance_m=0.0)

    assert source == [0] * 100
    assert navigation[4 * 10 + 4] == 100
    assert navigation[0] == 0


def test_virtual_wall_overlay_respects_rotated_grid_origin():
    zone = Zone(
        zone_id="wall",
        name="Wall",
        type=ZoneType.VIRTUAL_WALL,
        points=[Coordinate2D(x=1.8, y=-0.2), Coordinate2D(x=1.8, y=0.2)],
        nav2_virtual_wall_enabled=True,
    )

    navigation = overlay_restricted_zones(
        [0] * 200, 20, 10, 0.1, GridOrigin(x=2.0, y=-1.0, yaw_rad=math.pi / 2), [zone], clearance_m=0.0,
    )

    # World x=1.8 maps to local y=0.2, so the wall crosses row two.
    assert any(navigation[2 * 20 + column] == 100 for column in range(10))


def test_slow_zone_limits_only_points_inside_its_polygon():
    zone = Zone(
        zone_id="slow",
        name="Slow",
        type=ZoneType.SLOW,
        points=[
            Coordinate2D(x=0.5, y=0.5),
            Coordinate2D(x=1.5, y=0.5),
            Coordinate2D(x=1.5, y=1.5),
            Coordinate2D(x=0.5, y=1.5),
        ],
    )

    assert slow_zone_scale_at(1.0, 1.0, [zone]) == 0.5
    assert slow_zone_scale_at(2.0, 2.0, [zone]) == 1.0
