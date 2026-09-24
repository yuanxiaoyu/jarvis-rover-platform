from __future__ import annotations

import math

from app.models.map import GridOrigin
from app.models.zone import Zone, ZoneType


def overlay_restricted_zones(
    data: list[int],
    width: int,
    height: int,
    resolution: float,
    origin: GridOrigin,
    zones: list[Zone],
    clearance_m: float = 0.22,
) -> list[int]:
    """Return a navigation-only grid with keepout polygons/walls marked lethal."""
    if width <= 0 or height <= 0 or resolution <= 0 or len(data) != width * height:
        return list(data)
    output = list(data)
    for zone in zones:
        if zone.type is ZoneType.KEEP_OUT and zone.nav2_keepout_enabled:
            _mark_polygon(output, width, height, resolution, origin, zone, clearance_m)
        elif zone.type is ZoneType.VIRTUAL_WALL and zone.nav2_virtual_wall_enabled and len(zone.points) >= 2:
            _mark_wall(output, width, height, resolution, origin, zone.points[0], zone.points[1], clearance_m)
    return output


def slow_zone_scale_at(x: float, y: float, zones: list[Zone], scale: float = 0.5) -> float:
    for zone in zones:
        if zone.type is ZoneType.SLOW and _inside_polygon(x, y, zone.points):
            return scale
    return 1.0


def _mark_polygon(output, width, height, resolution, origin, zone, clearance):
    local = [_world_to_local(point.x, point.y, origin) for point in zone.points]
    effective_clearance = clearance + resolution * math.sqrt(2.0) / 2.0
    _raster_bounds(output, width, height, resolution, origin, local, effective_clearance,
                   lambda x, y: _inside_polygon(x, y, zone.points)
                   or _distance_to_polygon(x, y, zone.points) <= effective_clearance)


def _mark_wall(output, width, height, resolution, origin, start, end, clearance):
    local = [_world_to_local(start.x, start.y, origin), _world_to_local(end.x, end.y, origin)]
    effective_clearance = clearance + resolution * math.sqrt(2.0) / 2.0
    _raster_bounds(output, width, height, resolution, origin, local, effective_clearance,
                   lambda x, y: _distance_to_segment(x, y, start.x, start.y, end.x, end.y) <= effective_clearance)


def _raster_bounds(output, width, height, resolution, origin, local_points, clearance, blocked):
    min_column = max(0, math.floor((min(x for x, _ in local_points) - clearance) / resolution))
    max_column = min(width - 1, math.ceil((max(x for x, _ in local_points) + clearance) / resolution))
    min_row = max(0, math.floor((min(y for _, y in local_points) - clearance) / resolution))
    max_row = min(height - 1, math.ceil((max(y for _, y in local_points) + clearance) / resolution))
    for row in range(min_row, max_row + 1):
        for column in range(min_column, max_column + 1):
            local_x, local_y = (column + 0.5) * resolution, (row + 0.5) * resolution
            cosine, sine = math.cos(origin.yaw_rad), math.sin(origin.yaw_rad)
            x = origin.x + cosine * local_x - sine * local_y
            y = origin.y + sine * local_x + cosine * local_y
            if blocked(x, y):
                output[row * width + column] = 100


def _world_to_local(x: float, y: float, origin: GridOrigin) -> tuple[float, float]:
    dx, dy = x - origin.x, y - origin.y
    cosine, sine = math.cos(origin.yaw_rad), math.sin(origin.yaw_rad)
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _inside_polygon(x: float, y: float, points) -> bool:
    inside = False
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        if (first.y > y) != (second.y > y):
            cross_x = (second.x - first.x) * (y - first.y) / (second.y - first.y) + first.x
            if x < cross_x:
                inside = not inside
    return inside


def _distance_to_polygon(x: float, y: float, points) -> float:
    return min(
        _distance_to_segment(x, y, first.x, first.y, points[(index + 1) % len(points)].x,
                             points[(index + 1) % len(points)].y)
        for index, first in enumerate(points)
    )


def _distance_to_segment(x, y, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(x - x1, y - y1)
    projection = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_squared))
    return math.hypot(x - x1 - projection * dx, y - y1 - projection * dy)
