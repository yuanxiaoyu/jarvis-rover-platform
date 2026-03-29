from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


def normalize_labels(labels: Iterable[str]) -> set[str]:
    return {label.strip().lower() for label in labels if label.strip()}


def normalize_label(label: str) -> str:
    return label.strip().lower()


def is_garbage_label(label: str, allowed_labels: set[str]) -> bool:
    return normalize_label(label) in allowed_labels


def load_label_map_csv(csv_path: str | Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    path = Path(csv_path)
    if not path.exists():
        return mapping

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            source, target = row[0].strip(), row[1].strip()
            if not source or not target:
                continue
            mapping[normalize_label(source)] = target
    return mapping


def map_detection_label(label: str, label_map: dict[str, str]) -> str:
    if not label_map:
        return label
    return label_map.get(normalize_label(label), label)


def build_detection_summary(label: str, confidence: float, room_label: str) -> str:
    percent = round(confidence * 100, 1)
    return f"{room_label} 发现疑似垃圾目标：{label}，置信度 {percent}%"


def build_capture_relative_path(task_id: str, label: str, captured_at: datetime | None = None) -> Path:
    timestamp = captured_at or datetime.now(timezone.utc)
    safe_task = task_id or "no-task"
    safe_label = label.replace(" ", "_").replace("/", "_")
    return Path(timestamp.strftime("%Y/%m/%d")) / safe_task / f"{timestamp.strftime('%H%M%S')}_{safe_label}.jpg"


def build_capture_url(capture_path: Path, capture_base_url: str) -> str:
    if capture_base_url.strip():
        return f"{capture_base_url.rstrip('/')}/{quote(capture_path.as_posix())}"
    return capture_path.as_posix()


@dataclass(slots=True)
class PersistedCapture:
    image_path: Path
    metadata_path: Path | None


def persist_detection_metadata(
    metadata_path: Path,
    payload: dict[str, object],
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
