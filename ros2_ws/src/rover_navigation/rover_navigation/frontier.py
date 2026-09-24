"""Frontier selection over a live occupancy grid, independent of ROS runtime."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FrontierGrid:
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    data: Sequence[int]


@dataclass(frozen=True)
class Frontier:
    column: int
    row: int
    x: float
    y: float
    size: int
    distance_m: float
    exclusion_points: tuple[tuple[float, float], ...]


def find_frontiers(
    grid: FrontierGrid,
    robot_x: float,
    robot_y: float,
    excluded: set[tuple[int, int]] | None = None,
    *,
    min_cluster_cells: int = 2,
    min_distance_m: float = 0.3,
    excluded_world: Sequence[tuple[float, float]] = (),
    exclusion_radius_m: float = 0.28,
) -> list[Frontier]:
    """Return reachable-looking free/unknown boundaries ordered by travel distance.

    Nav2 remains responsible for collision-checked reachability and execution;
    goals rejected by Nav2 are excluded by the exploration node before retry.
    """
    if grid.width <= 0 or grid.height <= 0 or grid.resolution <= 0:
        return []
    if len(grid.data) != grid.width * grid.height:
        return []
    excluded = excluded or set()
    excluded_cells = set(excluded)
    exclusion_radius = max(0.0, exclusion_radius_m) + grid.resolution * math.sqrt(2.0) / 2.0
    for world_x, world_y in excluded_world:
        center_column, center_row = world_to_grid(grid, world_x, world_y)
        radius_cells = math.ceil(exclusion_radius / grid.resolution)
        for row in range(center_row - radius_cells, center_row + radius_cells + 1):
            for column in range(center_column - radius_cells, center_column + radius_cells + 1):
                if not (0 <= column < grid.width and 0 <= row < grid.height):
                    continue
                cell_x, cell_y = grid_to_world(grid, column, row)
                if math.hypot(cell_x - world_x, cell_y - world_y) <= exclusion_radius:
                    excluded_cells.add((column, row))
    candidates: set[tuple[int, int]] = set()
    for row in range(grid.height):
        for column in range(grid.width):
            if not _is_free(grid, column, row):
                continue
            if (column, row) in excluded_cells:
                continue
            if not _has_unknown_neighbor(grid, column, row):
                continue
            x, y = grid_to_world(grid, column, row)
            if math.hypot(x - robot_x, y - robot_y) >= min_distance_m:
                candidates.add((column, row))

    frontiers: list[Frontier] = []
    while candidates:
        seed = candidates.pop()
        cluster = [seed]
        queue = deque([seed])
        while queue:
            column, row = queue.popleft()
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if dc == 0 and dr == 0:
                        continue
                    neighbor = (column + dc, row + dr)
                    if neighbor in candidates:
                        candidates.remove(neighbor)
                        cluster.append(neighbor)
                        queue.append(neighbor)
        if len(cluster) < min_cluster_cells:
            continue
        mean_column = sum(cell[0] for cell in cluster) / len(cluster)
        mean_row = sum(cell[1] for cell in cluster) / len(cluster)

        def representative_key(cell: tuple[int, int]) -> tuple[float, float, int, int]:
            world_x, world_y = grid_to_world(grid, cell[0], cell[1])
            return (
                (cell[0] - mean_column) ** 2 + (cell[1] - mean_row) ** 2,
                math.hypot(world_x - robot_x, world_y - robot_y),
                cell[1],
                cell[0],
            )

        column, row = min(
            cluster,
            key=representative_key,
        )
        x, y = grid_to_world(grid, column, row)
        frontiers.append(
            Frontier(
                column=column,
                row=row,
                x=x,
                y=y,
                size=len(cluster),
                distance_m=math.hypot(x - robot_x, y - robot_y),
                exclusion_points=tuple(
                    grid_to_world(grid, cell_column, cell_row)
                    for cell_column, cell_row in sorted(cluster)
                ),
            )
        )
    return sorted(
        frontiers,
        key=lambda frontier: (
            frontier.distance_m / math.sqrt(frontier.size),
            frontier.distance_m,
            frontier.row,
            frontier.column,
        ),
    )


def grid_to_world(grid: FrontierGrid, column: int, row: int) -> tuple[float, float]:
    local_x = (column + 0.5) * grid.resolution
    local_y = (row + 0.5) * grid.resolution
    cosine = math.cos(grid.origin_yaw)
    sine = math.sin(grid.origin_yaw)
    return (
        grid.origin_x + cosine * local_x - sine * local_y,
        grid.origin_y + sine * local_x + cosine * local_y,
    )


def world_to_grid(grid: FrontierGrid, world_x: float, world_y: float) -> tuple[int, int]:
    dx, dy = world_x - grid.origin_x, world_y - grid.origin_y
    cosine = math.cos(grid.origin_yaw)
    sine = math.sin(grid.origin_yaw)
    local_x = cosine * dx + sine * dy
    local_y = -sine * dx + cosine * dy
    return math.floor(local_x / grid.resolution), math.floor(local_y / grid.resolution)


def _is_free(grid: FrontierGrid, column: int, row: int) -> bool:
    return 0 <= column < grid.width and 0 <= row < grid.height and 0 <= grid.data[row * grid.width + column] < 50


def _has_unknown_neighbor(grid: FrontierGrid, column: int, row: int) -> bool:
    return any(
        0 <= column + dc < grid.width
        and 0 <= row + dr < grid.height
        and grid.data[(row + dr) * grid.width + column + dc] == -1
        for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1))
    )
