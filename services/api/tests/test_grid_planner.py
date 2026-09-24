import math

import pytest

from app.models.map import GridOrigin, MapModel, MapSource, OccupancyGridMeta, Coordinate2D
from app.models.zone import Zone, ZoneType
from app.services.grid_planner import OccupancyGridPlanner, PathPlanningError


def make_map(width: int, height: int, data: list[int], resolution: float = 0.1) -> MapModel:
    return MapModel(
        map_id="test",
        name="test map",
        source=MapSource.MS200_TOF_2D,
        available=True,
        occupancy=OccupancyGridMeta(
            resolution_m_per_cell=resolution,
            width_cells=width,
            height_cells=height,
            origin=GridOrigin(),
            data=data,
        ),
    )


def test_astar_routes_around_an_occupied_wall():
    width, height = 30, 25
    cells = [0] * (width * height)
    for row in (*range(0, 8), *range(16, height)):
        cells[row * width + 15] = 100
    planner = OccupancyGridPlanner(make_map(width, height, cells), robot_radius_m=0.0)

    path = planner.plan(Coordinate2D(x=0.55, y=0.55), Coordinate2D(x=2.45, y=0.55))

    assert len(path.waypoints) >= 3
    assert path.length_m > 1.9
    assert path.goal_reached.x == pytest.approx(2.45)


def test_keepout_polygon_blocks_shortest_crossing():
    width, height = 30, 20
    zone = Zone(
        zone_id="keepout",
        name="restricted",
        type=ZoneType.KEEP_OUT,
        points=[
            Coordinate2D(x=1.1, y=0.6),
            Coordinate2D(x=1.4, y=0.6),
            Coordinate2D(x=1.4, y=1.4),
            Coordinate2D(x=1.1, y=1.4),
        ],
    )
    planner = OccupancyGridPlanner(make_map(width, height, [0] * (width * height)), [zone])

    path = planner.plan(Coordinate2D(x=0.55, y=0.95), Coordinate2D(x=2.45, y=0.95))

    assert all(not (1.1 <= point.x <= 1.4 and 0.6 <= point.y <= 1.4) for point in path.waypoints[1:-1])
    assert any(point.y < 0.4 or point.y > 1.6 for point in path.waypoints[1:-1])


def test_frontier_planner_returns_a_known_free_goal_near_unknown_cells():
    width, height = 25, 20
    cells = [-1] * (width * height)
    for row in range(height):
        for column in range(12):
            cells[row * width + column] = 0
    planner = OccupancyGridPlanner(make_map(width, height, cells), robot_radius_m=0.2)

    path = planner.next_frontier(Coordinate2D(x=0.55, y=0.55))

    assert path.waypoints
    assert path.goal_reached.x < 1.2
    assert cells[round(path.goal_reached.y / 0.1) * width + round(path.goal_reached.x / 0.1)] == 0


def test_unknown_cells_are_never_used_as_a_navigation_route():
    planner = OccupancyGridPlanner(make_map(20, 20, [-1] * 400))
    with pytest.raises(PathPlanningError, match="当前位置"):
        planner.plan(Coordinate2D(x=0.55, y=0.55), Coordinate2D(x=1.55, y=1.55))


def test_rotated_map_origin_is_used_for_world_grid_transforms_and_zone_clearance():
    width, height, resolution = 30, 20, 0.1
    origin = GridOrigin(x=2.0, y=-1.0, yaw_rad=math.pi / 2)
    # The world-space rectangle corresponds to a keepout strip across the
    # straight path through local grid cells at row 2.
    zone = Zone(
        zone_id="rotated-keepout",
        name="rotated restriction",
        type=ZoneType.KEEP_OUT,
        points=[
            Coordinate2D(x=1.9, y=0.2),
            Coordinate2D(x=1.9, y=0.5),
            Coordinate2D(x=1.5, y=0.5),
            Coordinate2D(x=1.5, y=0.2),
        ],
    )
    map_model = make_map(width, height, [0] * (width * height), resolution)
    map_model.occupancy.origin = origin
    planner = OccupancyGridPlanner(map_model, [zone], robot_radius_m=0.0)

    start = Coordinate2D(x=1.75, y=-0.75)
    goal = Coordinate2D(x=1.75, y=1.55)
    path = planner.plan(start, goal)

    assert path.goal_reached.x == pytest.approx(goal.x)
    assert path.goal_reached.y == pytest.approx(goal.y)
    assert path.length_m > 2.3
    assert all(not (1.5 <= point.x <= 1.9 and 0.2 <= point.y <= 0.5) for point in path.waypoints[1:-1])
