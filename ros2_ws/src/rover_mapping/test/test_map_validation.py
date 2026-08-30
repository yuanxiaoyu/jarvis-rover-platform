from rover_mapping.map_validation import Pose2D, validate_pose_in_map


MAP_YAML = """\
image: map.pgm
resolution: 1.0
origin: [0.0, 0.0, 0.0]
occupied_thresh: 0.65
free_thresh: 0.196
negate: 0
"""


def test_validate_pose_in_map_accepts_free_white_pixel():
    pgm = b"P5\n2 1\n255\n\xff\x00"

    assert validate_pose_in_map(MAP_YAML, pgm, Pose2D(0.1, 0.1, 0.0)) is True


def test_validate_pose_in_map_rejects_occupied_black_pixel():
    pgm = b"P5\n2 1\n255\n\x00\xff"

    assert validate_pose_in_map(MAP_YAML, pgm, Pose2D(0.1, 0.1, 0.0)) is False


def test_validate_pose_in_map_rejects_out_of_bounds_pose():
    pgm = b"P5\n2 1\n255\n\xff\xff"

    assert validate_pose_in_map(MAP_YAML, pgm, Pose2D(2.1, 0.1, 0.0)) is False


def test_validate_pose_in_map_supports_p2_and_rotated_origin():
    map_yaml = """\
image: map.pgm
resolution: 1.0
origin: [10.0, 20.0, 1.5707963267948966]
occupied_thresh: 0.65
free_thresh: 0.196
negate: 0
"""
    pgm = b"P2\n2 1\n255\n255 0\n"

    assert validate_pose_in_map(map_yaml, pgm, Pose2D(10.0, 20.5, 0.0)) is True
    assert validate_pose_in_map(map_yaml, pgm, Pose2D(10.0, 19.5, 0.0)) is False


def test_validate_pose_in_map_rejects_unknown_gray_pixel():
    pgm = b"P5\n1 1\n255\n\xcd"

    assert validate_pose_in_map(MAP_YAML, pgm, Pose2D(0.1, 0.1, 0.0)) is False
