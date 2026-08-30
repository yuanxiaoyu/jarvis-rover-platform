from dataclasses import replace

from rover_mapping.preflight import PreflightChecker, PreflightSnapshot


def healthy_snapshot() -> PreflightSnapshot:
    return PreflightSnapshot(
        publisher_counts={"/scan": 1, "/odom_raw": 1, "/imu": 1},
        stream_age_s={"/scan": 0.05, "/odom_raw": 0.03, "/imu": 0.04},
        tf_available={"base_footprint->laser_frame": True},
        duplicate_tf_publishers=0,
        duplicate_ekf_nodes=0,
        slam_backend_nodes=0,
        free_bytes=500_000_000,
        emergency_stop=False,
    )


def test_healthy_snapshot_passes() -> None:
    report = PreflightChecker(0.75, 100_000_000).check(healthy_snapshot())

    assert report.ok is True
    assert all(item.ok for item in report.checks.values())


def test_missing_scan_and_duplicate_ekf_fail() -> None:
    snapshot = replace(
        healthy_snapshot(),
        publisher_counts={"/scan": 0, "/odom_raw": 1, "/imu": 1},
        duplicate_ekf_nodes=1,
    )

    report = PreflightChecker(0.75, 100_000_000).check(snapshot)

    assert report.ok is False
    assert report.checks["/scan publisher"].ok is False
    assert report.checks["unique EKF"].ok is False


def test_stale_sensor_and_low_disk_fail() -> None:
    snapshot = replace(
        healthy_snapshot(),
        stream_age_s={"/scan": 2.0, "/odom_raw": 0.03, "/imu": 0.04},
        free_bytes=1,
    )

    report = PreflightChecker(0.75, 100_000_000).check(snapshot)

    assert report.ok is False
    assert report.checks["/scan fresh"].ok is False
    assert report.checks["disk space"].ok is False
