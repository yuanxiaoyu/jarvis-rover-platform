from rover_bringup.timestamp import NANOSECONDS_PER_SECOND, normalize_stamp


def test_normalize_stamp_preserves_a_timestamp_within_the_skew_limit():
    source = 1_790_181_007 * NANOSECONDS_PER_SECOND - 250_000_000

    normalized, adjusted = normalize_stamp(source, 1_790_181_007 * NANOSECONDS_PER_SECOND, 2 * NANOSECONDS_PER_SECOND)

    assert normalized == source
    assert adjusted is False


def test_normalize_stamp_replaces_an_old_device_clock_with_receive_time():
    old_source = 1_790_126_406 * NANOSECONDS_PER_SECOND
    now = 1_790_181_007 * NANOSECONDS_PER_SECOND

    normalized, adjusted = normalize_stamp(old_source, now, 2 * NANOSECONDS_PER_SECOND)

    assert normalized == now
    assert adjusted is True


def test_normalize_stamp_rejects_negative_skew_limit():
    try:
        normalize_stamp(0, 0, -1)
    except ValueError as exc:
        assert str(exc) == "max_skew_ns must be non-negative"
    else:
        raise AssertionError("negative skew limits must be rejected")
