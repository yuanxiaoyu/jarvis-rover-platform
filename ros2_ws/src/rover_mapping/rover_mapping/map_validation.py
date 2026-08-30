"""Validate a robot pose against an occupancy-grid PGM map."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


def validate_pose_in_map(map_yaml: str, pgm: bytes, pose: Pose2D) -> bool:
    """Return whether ``pose`` falls on a known free pixel in an occupancy map."""
    try:
        config = _parse_yaml(map_yaml)
        image_name = config.get("image")
        if not isinstance(image_name, str) or not image_name.strip():
            return False
        resolution = float(config["resolution"])
        if not math.isfinite(resolution) or resolution <= 0:
            return False
        origin = config.get("origin", [0.0, 0.0, 0.0])
        if not isinstance(origin, (list, tuple)) or len(origin) != 3:
            return False
        ox, oy, origin_yaw = (float(value) for value in origin)
        occupied_thresh = float(config["occupied_thresh"])
        free_thresh = float(config["free_thresh"])
        negate = int(config.get("negate", 0))
        if not all(math.isfinite(value) for value in (ox, oy, origin_yaw, occupied_thresh, free_thresh)):
            return False
        if not 0 <= free_thresh <= 1 or not 0 <= occupied_thresh <= 1:
            return False
        if negate not in (0, 1):
            return False
        width, height, max_value, magic, payload_offset = _parse_pgm_header(pgm)
        if max_value <= 0 or not all(math.isfinite(float(value)) for value in (pose.x, pose.y, pose.yaw)):
            return False
        # Convert world coordinates to the map's local metric frame. The map
        # origin is the lower-left corner, while PGM rows are top-to-bottom.
        dx = float(pose.x) - ox
        dy = float(pose.y) - oy
        cos_yaw = math.cos(origin_yaw)
        sin_yaw = math.sin(origin_yaw)
        local_x = cos_yaw * dx + sin_yaw * dy
        local_y = -sin_yaw * dx + cos_yaw * dy
        pixel_x = math.floor(local_x / resolution)
        pixel_y_from_bottom = math.floor(local_y / resolution)
        if not (0 <= pixel_x < width and 0 <= pixel_y_from_bottom < height):
            return False
        row = height - 1 - pixel_y_from_bottom
        gray_value = _pixel_at(
            pgm,
            magic,
            payload_offset,
            row * width + pixel_x,
            width * height,
            max_value,
        )
        unknown_value = 205 * max_value / 255
        if abs(gray_value - unknown_value) <= max(1.0, max_value / 255):
            return False
        gray = gray_value / max_value
        occupancy = 1.0 - gray if negate == 0 else gray
        # Unknown and occupied pixels are both unsafe; only strictly free
        # values satisfy map_server's free-space threshold semantics.
        return occupancy < free_thresh
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError):
        return False


def _parse_yaml(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ValueError("map YAML must be a string")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _parse_simple_yaml(text)
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError("map YAML root must be a mapping")
    return loaded


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, raw_value = (part.strip() for part in line.split(":", 1))
        if not key:
            continue
        if raw_value.startswith("[") and raw_value.endswith("]"):
            value: Any = [
                _scalar(item.strip()) for item in raw_value[1:-1].split(",") if item.strip()
            ]
        else:
            value = _scalar(raw_value)
        result[key] = value
    return result


def _scalar(value: str) -> Any:
    if (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(value, 10)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_pgm_header(data: bytes) -> tuple[int, int, int, bytes, int]:
    if not isinstance(data, bytes):
        raise ValueError("PGM must be bytes")
    tokens, payload_offset = _pgm_tokens(data, 4)
    magic, width_text, height_text, max_text = tokens
    if magic not in (b"P5", b"P2"):
        raise ValueError("only P5 and P2 PGM are supported")
    width = int(width_text)
    height = int(height_text)
    max_value = int(max_text)
    if width <= 0 or height <= 0 or not 0 < max_value <= 65535:
        raise ValueError("invalid PGM dimensions or max value")
    return width, height, max_value, magic, payload_offset


def _pixel_at(
    data: bytes,
    magic: bytes,
    payload_offset: int,
    pixel_index: int,
    pixel_count: int,
    max_value: int,
) -> int:
    if magic == b"P5":
        bytes_per_sample = 1 if max_value < 256 else 2
        expected_size = pixel_count * bytes_per_sample
        if len(data) - payload_offset != expected_size:
            raise ValueError("invalid P5 pixel data")
        offset = payload_offset + pixel_index * bytes_per_sample
        if bytes_per_sample == 1:
            return data[offset]
        return data[offset] * 256 + data[offset + 1]

    seen = 0
    index = payload_offset
    length = len(data)
    selected: int | None = None
    while index < length:
        while index < length and data[index] in b" \t\r\n":
            index += 1
        if index < length and data[index] == ord("#"):
            newline = data.find(b"\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if index >= length:
            break
        start = index
        while index < length and data[index] not in b" \t\r\n#":
            index += 1
        try:
            value = int(data[start:index])
        except ValueError as exc:
            raise ValueError("invalid P2 pixel data") from exc
        if not 0 <= value <= max_value:
            raise ValueError("invalid P2 pixel data")
        if seen == pixel_index:
            selected = value
        seen += 1
    if seen != pixel_count or selected is None:
        raise ValueError("invalid P2 pixel data")
    return selected


def _parse_pgm(data: bytes) -> tuple[int, int, int, list[int]]:
    if not isinstance(data, bytes):
        raise ValueError("PGM must be bytes")
    tokens, payload_offset = _pgm_tokens(data, 4)
    magic, width_text, height_text, max_text = tokens
    if magic not in (b"P5", b"P2"):
        raise ValueError("only P5 and P2 PGM are supported")
    width = int(width_text)
    height = int(height_text)
    max_value = int(max_text)
    if width <= 0 or height <= 0 or not 0 < max_value <= 65535:
        raise ValueError("invalid PGM dimensions or max value")
    count = width * height
    if magic == b"P2":
        values = [int(token) for token in re.findall(rb"\S+", data[payload_offset:])]
        if len(values) != count or any(value < 0 or value > max_value for value in values):
            raise ValueError("invalid P2 pixel data")
        return width, height, max_value, values
    bytes_per_sample = 1 if max_value < 256 else 2
    payload = data[payload_offset:]
    expected_size = count * bytes_per_sample
    if len(payload) != expected_size:
        raise ValueError("invalid P5 pixel data")
    if bytes_per_sample == 1:
        values = list(payload)
    else:
        values = [payload[i] * 256 + payload[i + 1] for i in range(0, len(payload), 2)]
    return width, height, max_value, values


def _pgm_tokens(data: bytes, count: int) -> tuple[list[bytes], int]:
    tokens: list[bytes] = []
    index = 0
    length = len(data)
    while len(tokens) < count:
        while index < length and data[index] in b" \t\r\n":
            index += 1
        if index < length and data[index] == ord("#"):
            newline = data.find(b"\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if index >= length:
            raise ValueError("truncated PGM header")
        start = index
        while index < length and data[index] not in b" \t\r\n#":
            index += 1
        tokens.append(data[start:index])
    # Consume exactly one separator after max value. Whitespace after the
    # header is technically a separator, but P5 pixel data may itself begin
    # with whitespace, so consuming one byte preserves it correctly.
    if index >= length or data[index] not in b" \t\r\n":
        raise ValueError("missing PGM payload separator")
    separator = data[index]
    index += 1
    if separator == ord("\r") and index < length and data[index] == ord("\n"):
        index += 1
    return tokens, index
