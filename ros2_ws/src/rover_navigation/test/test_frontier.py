import math
from pathlib import Path
from types import SimpleNamespace

from rover_navigation.frontier import FrontierGrid, find_frontiers


def half_known_map(width=30, height=20, resolution=0.1):
    data = [-1] * (width * height)
    for row in range(2, height - 2):
        for column in range(2, width // 2):
            data[row * width + column] = 0
        data[row * width + 1] = 100
    for column in range(2, width // 2):
        data[width + column] = 100
        data[(height - 2) * width + column] = 100
    return FrontierGrid(width, height, resolution, 0.0, 0.0, 0.0, data)


def map_with_two_separate_frontiers():
    width, height = 40, 26
    data = [-1] * (width * height)
    for row in range(2, 20):
        for column in range(2, 15):
            data[row * width + column] = 0
        data[row * width + 1] = 100
    for column in range(2, 15):
        data[width + column] = 100
        data[20 * width + column] = 100

    for row in range(5, 23):
        for column in range(26, 33):
            data[row * width + column] = 0
        data[row * width + 25] = 100
    for column in range(26, 33):
        data[4 * width + column] = 100
        data[23 * width + column] = 100
    return FrontierGrid(width, height, 0.1, 0.0, 0.0, 0.0, data)


def test_frontier_targets_known_free_cells_at_unknown_boundary():
    grid = half_known_map()

    candidates = find_frontiers(grid, 0.55, 0.55)

    assert candidates
    goal = candidates[0]
    assert grid.data[goal.row * grid.width + goal.column] == 0
    assert goal.column == grid.width // 2 - 1
    assert goal.size > 1


def test_frontier_exclusion_prevents_retrying_failed_or_visited_goal():
    grid = half_known_map()
    candidates = find_frontiers(grid, 0.55, 0.55)
    excluded = {(candidate.x, candidate.y) for candidate in candidates}

    remaining = find_frontiers(grid, 0.55, 0.55, excluded_world=excluded)
    assert all(
        math.hypot(candidate.x - x, candidate.y - y) > 0.28
        for candidate in remaining
        for x, y in excluded
    )


def test_failed_frontier_excludes_its_whole_cluster_and_keeps_other_regions():
    import pytest

    pytest.importorskip("rclpy")
    from rover_navigation.navigation_node import NavigationNode

    grid = map_with_two_separate_frontiers()
    frontiers = find_frontiers(grid, 0.55, 0.55)
    failed = frontiers[0]
    assert failed.column == 14

    node = SimpleNamespace(_excluded=set(), _failed=0, _message="")
    NavigationNode._exclude(node, failed, "Nav2 无法到达该前沿")
    remaining = find_frontiers(grid, 0.55, 0.55, excluded_world=tuple(node._excluded))

    assert remaining
    assert all(frontier.column != failed.column for frontier in remaining)
    assert remaining[0].column == 32
    assert node._failed == 1


def test_goal_timeout_skips_one_frontier_and_keeps_exploration_active():
    import time

    import pytest

    pytest.importorskip("rclpy")
    from action_msgs.msg import GoalStatus
    from rover_navigation.navigation_node import NavigationNode

    class CompletedFuture:
        def result(self):
            return SimpleNamespace(status=GoalStatus.STATUS_CANCELED)

    grid = map_with_two_separate_frontiers()
    frontier = find_frontiers(grid, 0.55, 0.55)[0]
    failure_messages = []
    cancel_requests = []
    parameter_values = {"goal_timeout_s": 1.0, "max_failed_frontiers": 40}
    node = SimpleNamespace(
        _state="exploring",
        _state_since=time.monotonic() - 5.0,
        _goal_handle=object(),
        _goal_result_future=CompletedFuture(),
        _goal_pending=False,
        _cancel_pending=False,
        _cancel_when_accepted=False,
        _cancel_started=0.0,
        _active_frontier=frontier,
        _goal_started=time.monotonic() - 5.0,
        _skip_active_on_cancel=False,
        _grid=grid,
        _excluded=set(),
        _completed=0,
        _failed=0,
        _remaining=1,
        _message="Nav2 正在前往下一个探索前沿",
        _refresh_nav2_lifecycle_states=lambda _now: None,
        _publish_interlocks=lambda *_args: None,
        _map_fresh=lambda _now: True,
        _safety_fresh=lambda _now: True,
        _imu_fresh=lambda _now: True,
        _nav2_lifecycle_missing=lambda _now: (),
        _action_client=SimpleNamespace(server_is_ready=lambda: True),
        _robot_pose=lambda: (0.55, 0.55, 0.0),
        get_parameter=lambda name: SimpleNamespace(value=parameter_values[name]),
        _cancel_goal=lambda: cancel_requests.append(True),
        _fail=lambda message: (failure_messages.append(message), setattr(node, "_state", "error")),
    )
    node._clear_active = lambda selected: NavigationNode._clear_active(node, selected)
    node._exclude = lambda selected, message: NavigationNode._exclude(node, selected, message)
    node._on_goal_result = lambda future, selected: NavigationNode._on_goal_result(node, future, selected)

    NavigationNode._tick(node)
    NavigationNode._tick(node)
    NavigationNode._on_goal_result(node, node._goal_result_future, frontier)

    assert not failure_messages
    assert cancel_requests == [True]
    assert node._state == "exploring"
    assert node._failed == 1
    assert set(frontier.exclusion_points).issubset(node._excluded)
    remaining = find_frontiers(grid, 0.55, 0.55, excluded_world=tuple(node._excluded))
    assert remaining
    assert remaining[0].column == 32


def test_frontier_uses_rotated_map_origin_for_world_goals():
    data = [-1] * (12 * 10)
    for row in range(2, 8):
        for column in range(2, 6):
            data[row * 12 + column] = 0
        data[row * 12 + 1] = 100
    for column in range(2, 6):
        data[12 + column] = 100
        data[8 * 12 + column] = 100
    grid = FrontierGrid(12, 10, 0.1, 2.0, -1.0, math.pi / 2, data)

    frontier = find_frontiers(grid, 1.5, -0.65, min_distance_m=0.05)[0]

    assert frontier.column == 5
    assert abs(frontier.x - (2.0 - (frontier.row + 0.5) * 0.1)) < 1e-6
    assert abs(frontier.y - (-1.0 + (frontier.column + 0.5) * 0.1)) < 1e-6


def test_nav2_bt_plugins_cover_default_humble_navigation_tree():
    params = Path(__file__).resolve().parents[1] / "params" / "nav2_params.yaml"
    contents = params.read_text(encoding="utf-8")

    for plugin in (
        "nav2_rate_controller_bt_node",
        "nav2_pipeline_sequence_bt_node",
        "nav2_round_robin_node_bt_node",
        "nav2_remove_passed_goals_action_bt_node",
    ):
        assert f"- {plugin}" in contents


def test_pause_during_goal_acceptance_does_not_cancel_a_goal_that_already_finished():
    import pytest

    pytest.importorskip("rclpy")
    from action_msgs.msg import GoalStatus
    from rover_navigation.navigation_node import NavigationNode

    class CompletedFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

        def done(self):
            return True

        def add_done_callback(self, callback):
            callback(self)

    class Handle:
        accepted = True

        def __init__(self):
            self.cancel_count = 0

        def get_result_async(self):
            return CompletedFuture(SimpleNamespace(status=GoalStatus.STATUS_SUCCEEDED))

        def cancel_goal_async(self):
            self.cancel_count += 1
            return CompletedFuture(SimpleNamespace(goals_canceling=[]))

    frontier = SimpleNamespace(column=2, row=3, x=0.5, y=0.5)
    handle = Handle()
    node = SimpleNamespace(
        _state="paused",
        _goal_pending=True,
        _cancel_when_accepted=True,
        _cancel_pending=False,
        _cancel_started=1.0,
        _goal_started=1.0,
        _goal_handle=None,
        _goal_result_future=None,
        _active_frontier=frontier,
        _skip_active_on_cancel=False,
        _completed=0,
        _failed=0,
        _remaining=0,
        _excluded=set(),
        _publish_interlocks=lambda: None,
    )
    node._clear_active = lambda selected: NavigationNode._clear_active(node, selected)
    node._on_goal_result = lambda future, selected: NavigationNode._on_goal_result(node, future, selected)
    node._request_goal_cancel = lambda selected: NavigationNode._request_goal_cancel(node, selected)

    NavigationNode._on_goal_response(node, CompletedFuture(handle), frontier)

    assert node._completed == 0
    assert node._goal_handle is None
    assert node._cancel_pending is False
    assert handle.cancel_count == 0


def test_navigation_requires_fresh_imu_before_motion():
    import pytest

    pytest.importorskip("rclpy")
    from rover_navigation.navigation_node import NavigationNode

    node = SimpleNamespace(
        _imu_received=10.0,
        get_parameter=lambda _name: SimpleNamespace(value=0.5),
    )

    assert NavigationNode._imu_fresh(node, 10.4) is True
    assert NavigationNode._imu_fresh(node, 10.51) is False


def test_action_visibility_is_not_enough_until_all_nav2_lifecycle_nodes_are_active():
    import pytest

    pytest.importorskip("rclpy")
    from rover_navigation.navigation_node import NAV2_LIFECYCLE_NODES, missing_nav2_lifecycle_nodes

    states = {name: 3 for name in NAV2_LIFECYCLE_NODES}
    states["controller_server"] = 2
    states["planner_server"] = 2

    assert missing_nav2_lifecycle_nodes(states) == ("controller_server", "planner_server")

    states["controller_server"] = 3
    states["planner_server"] = 3
    assert missing_nav2_lifecycle_nodes(states) == ()
