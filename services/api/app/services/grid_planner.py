from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.models.map import Coordinate2D, MapModel
from app.models.zone import Zone, ZoneType


class PathPlanningError(ValueError):
    pass


@dataclass(frozen=True)
class PlannedPath:
    waypoints: list[Coordinate2D]
    length_m: float
    explored_cells: int
    goal_reached: Coordinate2D


class OccupancyGridPlanner:
    """8-connected A* planner over a real ROS OccupancyGrid snapshot."""

    def __init__(self, map_model: MapModel, zones: list[Zone] | None = None, robot_radius_m: float = 0.20) -> None:
        grid = map_model.occupancy
        if not map_model.available or grid.data is None:
            raise PathPlanningError("真实 OccupancyGrid 尚不可用")
        if grid.width_cells * grid.height_cells != len(grid.data):
            raise PathPlanningError("OccupancyGrid 尺寸与数据长度不匹配")
        self.map = map_model
        self.grid = grid
        self.data = grid.data
        self.zones = zones or []
        self.radius_cells = max(0, math.ceil(robot_radius_m / grid.resolution_m_per_cell))
        self.width = grid.width_cells
        self.height = grid.height_cells
        self.resolution = grid.resolution_m_per_cell
        self._blocked = bytearray(self.width * self.height)
        self._build_collision_grid()

    def plan(self, start: Coordinate2D, goal: Coordinate2D) -> PlannedPath:
        start_cell = self._world_to_grid(start)
        requested_goal = self._world_to_grid(goal)
        if not self._inside(*start_cell):
            raise PathPlanningError("机器人位姿在地图范围之外")
        if not self._is_traversable(*start_cell, start_cell=start_cell):
            raise PathPlanningError("机器人当前位置不在已知可通行栅格中")
        goal_snap_cells = max(1, min(max(self.width, self.height), math.ceil(0.75 / self.resolution)))
        goal_cell = self._nearest_traversable(requested_goal, goal_snap_cells)
        if goal_cell is None:
            raise PathPlanningError("目标点附近没有可通行栅格")
        path_cells, cost, visited = self._a_star(start_cell, goal_cell)
        if path_cells is None:
            raise PathPlanningError("当前地图中不存在安全可达路径")
        waypoints = self._simplify(path_cells, start, self._grid_to_world(*goal_cell))
        return PlannedPath(waypoints, self._path_length(waypoints), visited, self._grid_to_world(*goal_cell))

    def next_frontier(self, start: Coordinate2D) -> PlannedPath:
        start_cell = self._world_to_grid(start)
        if not self._inside(*start_cell) or not self._is_traversable(*start_cell, start_cell=start_cell):
            raise PathPlanningError("机器人当前位置不在已知可通行栅格中")
        queue: list[tuple[float, tuple[int, int]]] = [(0.0, start_cell)]
        costs = {start_cell: 0.0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        visited = 0
        while queue:
            cost, current = heapq.heappop(queue)
            if cost != costs.get(current):
                continue
            visited += 1
            if current != start_cell and self._is_frontier(*current):
                cells = self._reconstruct(previous, current)
                waypoints = self._simplify(cells, start, self._grid_to_world(*current))
                return PlannedPath(waypoints, self._path_length(waypoints), visited, self._grid_to_world(*current))
            for neighbor, step_cost in self._neighbors(*current):
                if neighbor != start_cell and not self._is_traversable(*neighbor, start_cell=start_cell):
                    continue
                new_cost = cost + step_cost + self._zone_penalty(*neighbor)
                if new_cost < costs.get(neighbor, math.inf):
                    costs[neighbor] = new_cost
                    previous[neighbor] = current
                    heapq.heappush(queue, (new_cost, neighbor))
        raise PathPlanningError("地图上没有可达的未知区域边界")

    def _a_star(self, start: tuple[int, int], goal: tuple[int, int]):
        queue: list[tuple[float, float, tuple[int, int]]] = [(self._heuristic(start, goal), 0.0, start)]
        costs = {start: 0.0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        visited = 0
        while queue:
            _, cost, current = heapq.heappop(queue)
            if cost != costs.get(current):
                continue
            visited += 1
            if current == goal:
                return self._reconstruct(previous, current), cost, visited
            for neighbor, step_cost in self._neighbors(*current):
                if neighbor != start and not self._is_traversable(*neighbor, start_cell=start):
                    continue
                new_cost = cost + step_cost + self._zone_penalty(*neighbor)
                if new_cost < costs.get(neighbor, math.inf):
                    costs[neighbor] = new_cost
                    previous[neighbor] = current
                    heapq.heappush(queue, (new_cost + self._heuristic(neighbor, goal), new_cost, neighbor))
        return None, math.inf, visited

    def _neighbors(self, column: int, row: int):
        for dc, dr, multiplier in (
            (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
            (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2)),
        ):
            neighbor = (column + dc, row + dr)
            if not self._inside(*neighbor):
                continue
            if dc and dr:
                if not self._is_traversable(column + dc, row) or not self._is_traversable(column, row + dr):
                    continue
            yield neighbor, multiplier

    def _is_traversable(self, column: int, row: int, start_cell: tuple[int, int] | None = None) -> bool:
        if not self._inside(column, row):
            return False
        value = self.data[row * self.width + column]
        if start_cell == (column, row):
            return 0 <= value < 50
        return 0 <= value < 50 and self._blocked[row * self.width + column] == 0

    def _build_collision_grid(self) -> None:
        radius = self.radius_cells
        for row in range(self.height):
            for column in range(self.width):
                if self.data[row * self.width + column] >= 50:
                    self._block_disc(column, row, radius)
        # Keep the robot footprint inside the known map instead of routing its
        # center to a cell where the chassis would hang over the raster edge.
        for row in range(self.height):
            for column in range(self.width):
                if column < radius or row < radius or column >= self.width - radius or row >= self.height - radius:
                    self._blocked[row * self.width + column] = 1
        clearance = max(self.resolution * 0.5, radius * self.resolution)
        for zone in self.zones:
            if zone.type is ZoneType.KEEP_OUT and zone.nav2_keepout_enabled:
                self._block_zone_polygon(zone, clearance)
            elif zone.type is ZoneType.VIRTUAL_WALL and zone.nav2_virtual_wall_enabled and len(zone.points) >= 2:
                self._block_wall(zone.points[0], zone.points[1], clearance)

    def _block_disc(self, column: int, row: int, radius: int) -> None:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if dc * dc + dr * dr > radius * radius:
                    continue
                target_column, target_row = column + dc, row + dr
                if self._inside(target_column, target_row):
                    self._blocked[target_row * self.width + target_column] = 1

    def _block_zone_polygon(self, zone: Zone, clearance: float) -> None:
        min_column, min_row, max_column, max_row = self._grid_bounds(zone.points, clearance)
        for row in range(max(0, min_row), min(self.height, max_row + 1)):
            for column in range(max(0, min_column), min(self.width, max_column + 1)):
                point = self._grid_to_world(column, row)
                if self._inside_polygon(point, zone) or self._distance_to_polygon(point, zone) <= clearance:
                    self._blocked[row * self.width + column] = 1

    def _block_wall(self, start: Coordinate2D, end: Coordinate2D, clearance: float) -> None:
        min_column, min_row, max_column, max_row = self._grid_bounds([start, end], clearance)
        for row in range(max(0, min_row), min(self.height, max_row + 1)):
            for column in range(max(0, min_column), min(self.width, max_column + 1)):
                if self._distance_to_segment(self._grid_to_world(column, row), start, end) <= clearance:
                    self._blocked[row * self.width + column] = 1

    def _zone_penalty(self, column: int, row: int) -> float:
        point = self._grid_to_world(column, row)
        return 1.5 if any(zone.type is ZoneType.SLOW and self._inside_polygon(point, zone) for zone in self.zones) else 0.0

    def _is_frontier(self, column: int, row: int) -> bool:
        if not self._is_traversable(column, row):
            return False
        search = max(1, self.radius_cells + 1)
        return any(
            self._inside(column + dc, row + dr)
            and self.data[(row + dr) * self.width + column + dc] == -1
            for dc in range(-search, search + 1)
            for dr in range(-search, search + 1)
            if abs(dc) + abs(dr) <= search
        )

    def _nearest_traversable(self, cell: tuple[int, int], max_radius: int) -> tuple[int, int] | None:
        column, row = cell
        if self._inside(column, row) and self._is_traversable(column, row):
            return cell
        for radius in range(1, max_radius + 1):
            candidates = []
            for dc in range(-radius, radius + 1):
                for dr in (-radius, radius):
                    candidates.append((column + dc, row + dr))
            for dr in range(-radius + 1, radius):
                for dc in (-radius, radius):
                    candidates.append((column + dc, row + dr))
            candidates.sort(key=lambda candidate: (candidate[0] - column) ** 2 + (candidate[1] - row) ** 2)
            for candidate in candidates:
                if self._is_traversable(*candidate):
                    return candidate
        return None

    def _world_to_grid(self, point: Coordinate2D) -> tuple[int, int]:
        local_x, local_y = self._world_to_local(point)
        return (
            math.floor(local_x / self.resolution),
            math.floor(local_y / self.resolution),
        )

    def _grid_to_world(self, column: int, row: int) -> Coordinate2D:
        local_x = (column + 0.5) * self.resolution
        local_y = (row + 0.5) * self.resolution
        cosine, sine = math.cos(self.grid.origin.yaw_rad), math.sin(self.grid.origin.yaw_rad)
        return Coordinate2D(
            x=self.grid.origin.x + cosine * local_x - sine * local_y,
            y=self.grid.origin.y + sine * local_x + cosine * local_y,
        )

    def _world_to_local(self, point: Coordinate2D) -> tuple[float, float]:
        dx = point.x - self.grid.origin.x
        dy = point.y - self.grid.origin.y
        cosine, sine = math.cos(self.grid.origin.yaw_rad), math.sin(self.grid.origin.yaw_rad)
        return cosine * dx + sine * dy, -sine * dx + cosine * dy

    def _grid_bounds(self, points: list[Coordinate2D], padding_m: float) -> tuple[int, int, int, int]:
        local_points = [self._world_to_local(point) for point in points]
        return (
            math.floor((min(x for x, _ in local_points) - padding_m) / self.resolution),
            math.floor((min(y for _, y in local_points) - padding_m) / self.resolution),
            math.floor((max(x for x, _ in local_points) + padding_m) / self.resolution),
            math.floor((max(y for _, y in local_points) + padding_m) / self.resolution),
        )

    def _inside(self, column: int, row: int) -> bool:
        return 0 <= column < self.width and 0 <= row < self.height

    @staticmethod
    def _heuristic(first: tuple[int, int], second: tuple[int, int]) -> float:
        dx, dy = abs(first[0] - second[0]), abs(first[1] - second[1])
        return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)

    @staticmethod
    def _reconstruct(previous: dict[tuple[int, int], tuple[int, int]], current: tuple[int, int]) -> list[tuple[int, int]]:
        result = [current]
        while current in previous:
            current = previous[current]
            result.append(current)
        result.reverse()
        return result

    def _simplify(self, cells: list[tuple[int, int]], start: Coordinate2D, goal: Coordinate2D) -> list[Coordinate2D]:
        if not cells:
            return [start, goal]
        selected = [cells[0]]
        anchor = 0
        index = 1
        while index < len(cells):
            if not self._line_is_clear(cells[anchor], cells[index]):
                selected.append(cells[index - 1])
                anchor = index - 1
            index += 1
        if selected[-1] != cells[-1]:
            selected.append(cells[-1])
        waypoints = [start]
        waypoints.extend(self._grid_to_world(column, row) for column, row in selected[1:-1])
        waypoints.append(goal)
        return waypoints

    def _line_is_clear(self, start: tuple[int, int], goal: tuple[int, int]) -> bool:
        steps = max(abs(goal[0] - start[0]), abs(goal[1] - start[1]))
        if steps == 0:
            return True
        for step in range(1, steps + 1):
            fraction = step / steps
            column = round(start[0] + (goal[0] - start[0]) * fraction)
            row = round(start[1] + (goal[1] - start[1]) * fraction)
            if not self._is_traversable(column, row):
                return False
        return True

    @staticmethod
    def _path_length(waypoints: list[Coordinate2D]) -> float:
        return sum(
            math.hypot(second.x - first.x, second.y - first.y)
            for first, second in zip(waypoints, waypoints[1:])
        )

    def _inside_polygon(self, point: Coordinate2D, zone: Zone) -> bool:
        inside = False
        vertices = zone.points
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            if (first.y > point.y) != (second.y > point.y):
                cross_x = (second.x - first.x) * (point.y - first.y) / (second.y - first.y) + first.x
                if point.x < cross_x:
                    inside = not inside
        return inside

    @staticmethod
    def _distance_to_segment(point: Coordinate2D, start: Coordinate2D, end: Coordinate2D) -> float:
        dx, dy = end.x - start.x, end.y - start.y
        squared = dx * dx + dy * dy
        if squared == 0:
            return math.hypot(point.x - start.x, point.y - start.y)
        projection = max(0.0, min(1.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / squared))
        return math.hypot(point.x - (start.x + projection * dx), point.y - (start.y + projection * dy))

    def _distance_to_polygon(self, point: Coordinate2D, zone: Zone) -> float:
        return min(
            self._distance_to_segment(point, first, zone.points[(index + 1) % len(zone.points)])
            for index, first in enumerate(zone.points)
        )
