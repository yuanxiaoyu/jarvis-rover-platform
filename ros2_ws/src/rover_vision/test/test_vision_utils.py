from datetime import datetime, timezone
from pathlib import Path

from rover_vision.vision_utils import (
    build_capture_relative_path,
    build_capture_url,
    build_detection_summary,
    is_garbage_label,
    load_label_map_csv,
    map_detection_label,
    normalize_labels,
)


def test_normalize_and_match_labels():
    labels = normalize_labels([" Bottle ", "cup", "", "CAN"])
    assert labels == {"bottle", "cup", "can"}
    assert is_garbage_label("bottle", labels)
    assert not is_garbage_label("person", labels)


def test_build_capture_paths_and_summary():
    captured_at = datetime(2026, 3, 29, 12, 30, 45, tzinfo=timezone.utc)
    relative = build_capture_relative_path("task-1234", "drink bottle", captured_at)
    assert relative == Path("2026/03/29/task-1234/123045_drink_bottle.jpg")
    assert build_capture_url(relative, "https://files.example.com/captures") == (
        "https://files.example.com/captures/2026/03/29/task-1234/123045_drink_bottle.jpg"
    )
    assert "客厅" in build_detection_summary("bottle", 0.87, "客厅")


def test_load_and_apply_label_map(tmp_path):
    csv_path = tmp_path / "map.csv"
    csv_path.write_text("Clear plastic bottle,Bottle\nGarbage bag,Plastic bag + wrapper\n", encoding="utf-8")
    label_map = load_label_map_csv(csv_path)
    assert map_detection_label("clear plastic bottle", label_map) == "Bottle"
    assert map_detection_label("Garbage bag", label_map) == "Plastic bag + wrapper"
