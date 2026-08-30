from scripts.ros_graph_probe import hz_from_timestamps, unique_control_path


def test_hz_from_timestamps_uses_monotonic_sample_window():
    assert hz_from_timestamps([1.0, 1.1, 1.2, 1.3]) == 10.0


def test_hz_from_timestamps_returns_none_for_invalid_window():
    assert hz_from_timestamps([]) is None
    assert hz_from_timestamps([1.0]) is None
    assert hz_from_timestamps([1.0, 1.0]) is None


def test_unique_control_path_requires_one_final_publisher():
    assert unique_control_path(final_publishers=1, input_publishers=2) is True
    assert unique_control_path(final_publishers=2, input_publishers=1) is False
    assert unique_control_path(final_publishers=0, input_publishers=1) is False
