from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image

from rover_vision.vision_utils import (
    build_capture_relative_path,
    build_capture_url,
    build_detection_summary,
    is_garbage_label,
    load_label_map_csv,
    map_detection_label,
    normalize_labels,
    persist_detection_metadata,
    PersistedCapture,
)


try:
    import numpy as np
except ImportError:  # pragma: no cover - optional runtime dependency
    np = None

try:
    from PIL import Image as PILImage
    from PIL import ImageDraw
except ImportError:  # pragma: no cover - optional runtime dependency
    PILImage = None
    ImageDraw = None

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - optional runtime dependency
    YOLO = None


@dataclass(slots=True)
class DetectionCandidate:
    label: str
    raw_label: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None


class GarbageDetectionNode(Node):
    def __init__(self) -> None:
        super().__init__("garbage_detection_node")
        self.declare_parameter("enabled", False)
        self.declare_parameter("detector_backend", "ultralytics")
        self.declare_parameter("model_path", "/workspace/models/yolo/taco_pi_best.pt")
        self.declare_parameter("dataset_profile", "taco")
        self.declare_parameter("label_map_csv", "")
        self.declare_parameter("image_transport", "compressed")
        self.declare_parameter("compressed_image_topic", "/camera/image/compressed")
        self.declare_parameter("raw_image_topic", "/camera/image_raw")
        self.declare_parameter("api_base_url", "http://127.0.0.1:8000")
        self.declare_parameter("system_snapshot_path", "/api/v1/system/snapshot")
        self.declare_parameter("detection_post_path", "/api/v1/garbage/detections")
        self.declare_parameter("whole_home_task_type", "whole_home_scan")
        self.declare_parameter("capture_dir", "/tmp/rover_captures")
        self.declare_parameter("capture_base_url", "")
        self.declare_parameter("room_label_fallback", "unknown_room")
        self.declare_parameter("min_confidence", 0.35)
        self.declare_parameter(
            "allowed_labels",
            [
                "can",
                "bottle",
                "plastic bag + wrapper",
                "plastic bag",
                "bag",
                "paper",
                "carton",
                "cup",
                "litter",
                "other",
                "plastic",
                "wrapper",
                "cigarette",
                "food waste",
                "glass",
                "metal",
                "bottle cap",
                "lid",
                "易拉罐",
                "饮料瓶",
                "塑料袋",
            ],
        )
        self.declare_parameter("report_cooldown_seconds", 15.0)
        self.declare_parameter("active_task_refresh_seconds", 2.0)
        self.declare_parameter("save_annotated_capture", True)
        self.declare_parameter("save_sidecar_json", True)
        self.declare_parameter("pi_mode", True)
        self.declare_parameter("frame_stride", 6)
        self.declare_parameter("max_image_dim", 640)
        self.declare_parameter("model_input_size", 640)
        self.declare_parameter("mock_detections_enabled", False)
        self.declare_parameter("mock_detection_label", "bottle")

        self.enabled = self.get_parameter("enabled").value
        self.detector_backend = self.get_parameter("detector_backend").value
        self.model_path = self.get_parameter("model_path").value
        self.dataset_profile = self.get_parameter("dataset_profile").value
        self.label_map_csv = self.get_parameter("label_map_csv").value
        self.image_transport = self.get_parameter("image_transport").value
        self.api_base_url = self.get_parameter("api_base_url").value.rstrip("/")
        self.system_snapshot_path = self.get_parameter("system_snapshot_path").value
        self.detection_post_path = self.get_parameter("detection_post_path").value
        self.whole_home_task_type = self.get_parameter("whole_home_task_type").value
        self.capture_dir = Path(self.get_parameter("capture_dir").value)
        self.capture_base_url = self.get_parameter("capture_base_url").value
        self.room_label_fallback = self.get_parameter("room_label_fallback").value
        self.min_confidence = float(self.get_parameter("min_confidence").value)
        self.allowed_labels = normalize_labels(self.get_parameter("allowed_labels").value)
        self.report_cooldown_seconds = float(self.get_parameter("report_cooldown_seconds").value)
        self.save_annotated_capture = bool(self.get_parameter("save_annotated_capture").value)
        self.save_sidecar_json = bool(self.get_parameter("save_sidecar_json").value)
        self.pi_mode = bool(self.get_parameter("pi_mode").value)
        self.frame_stride = max(1, int(self.get_parameter("frame_stride").value))
        self.max_image_dim = int(self.get_parameter("max_image_dim").value)
        self.model_input_size = int(self.get_parameter("model_input_size").value)
        self.mock_detections_enabled = bool(self.get_parameter("mock_detections_enabled").value)
        self.mock_detection_label = self.get_parameter("mock_detection_label").value
        self.label_map = load_label_map_csv(self.label_map_csv)
        self.active_task_id: str | None = None
        self.last_reported_at: datetime | None = None
        self.frame_counter = 0
        self.model = self._load_detector()

        if self.image_transport == "compressed":
            topic = self.get_parameter("compressed_image_topic").value
            self.create_subscription(CompressedImage, topic, self._on_compressed_image, 10)
        else:
            topic = self.get_parameter("raw_image_topic").value
            self.create_subscription(Image, topic, self._on_raw_image, 10)

        refresh_seconds = float(self.get_parameter("active_task_refresh_seconds").value)
        self.create_timer(refresh_seconds, self._refresh_active_task)

        self.get_logger().info(
            f"garbage_detection_node ready: enabled={self.enabled}, backend={self.detector_backend}, "
            f"transport={self.image_transport}, topic={topic}, dataset_profile={self.dataset_profile}, "
            f"pi_mode={self.pi_mode}"
        )

    def _load_detector(self) -> Any | None:
        if self.detector_backend != "ultralytics":
            self.get_logger().info("garbage_detection_node running without ultralytics backend.")
            return None

        missing = []
        if YOLO is None:
            missing.append("ultralytics")
        if np is None:
            missing.append("numpy")
        if PILImage is None:
            missing.append("pillow")

        if missing:
            self.get_logger().warning(
                f"ultralytics backend unavailable, missing runtime deps: {', '.join(missing)}. "
                "Set detector_backend=mock for scaffold verification."
            )
            return None

        try:
            return YOLO(self.model_path)
        except Exception as exc:  # pragma: no cover - model load depends on environment
            self.get_logger().warning(f"Failed to load YOLO model from {self.model_path}: {exc}")
            return None

    def _refresh_active_task(self) -> None:
        if not self.enabled:
            self.active_task_id = None
            return

        endpoint = f"{self.api_base_url}{self.system_snapshot_path}"
        try:
            with urlopen(endpoint, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network depends on runtime
            self.get_logger().debug(f"Failed to refresh active task from API: {exc}")
            return

        tasks = payload.get("tasks", [])
        next_task = next(
            (
                task for task in tasks
                if task.get("type") == self.whole_home_task_type and task.get("status") in {"pending", "running"}
            ),
            None,
        )
        self.active_task_id = next_task.get("task_id") if next_task else None

    def _on_compressed_image(self, msg: CompressedImage) -> None:
        image = self._decode_compressed_image(msg)
        if image is not None:
            self._handle_frame(image)

    def _on_raw_image(self, msg: Image) -> None:
        image = self._decode_raw_image(msg)
        if image is not None:
            self._handle_frame(image)

    def _decode_compressed_image(self, msg: CompressedImage):
        if PILImage is None:
            self.get_logger().warning("Pillow not installed; cannot decode compressed images.")
            return None
        try:
            from io import BytesIO

            return PILImage.open(BytesIO(bytes(msg.data))).convert("RGB")
        except Exception as exc:
            self.get_logger().warning(f"Failed to decode compressed image: {exc}")
            return None

    def _decode_raw_image(self, msg: Image):
        if PILImage is None or np is None:
            self.get_logger().warning("Pillow/numpy not installed; cannot decode raw images.")
            return None

        try:
            channels = 3
            array = np.frombuffer(msg.data, dtype=np.uint8)
            image = array.reshape((msg.height, msg.width, channels))
            if msg.encoding.lower() == "rgb8":
                return PILImage.fromarray(image, mode="RGB")
            return PILImage.fromarray(image[:, :, ::-1], mode="RGB")
        except Exception as exc:
            self.get_logger().warning(f"Failed to decode raw image: {exc}")
            return None

    def _handle_frame(self, image) -> None:
        if not self.enabled or not self.active_task_id:
            return

        self.frame_counter += 1
        if self.frame_counter % self.frame_stride != 0:
            return

        if self._cooldown_active():
            return

        image = self._prepare_image(image)
        detection = self._detect(image)
        if detection is None:
            return

        persisted = self._persist_capture(image, detection)
        payload = self._build_detection_payload(detection, persisted.image_path)
        self._post_detection(payload)

    def _prepare_image(self, image):
        if PILImage is None:
            return image
        if not self.pi_mode:
            return image

        width, height = image.size
        longest_edge = max(width, height)
        if longest_edge <= self.max_image_dim:
            return image

        scale = self.max_image_dim / float(longest_edge)
        resized = image.resize((int(width * scale), int(height * scale)))
        return resized

    def _cooldown_active(self) -> bool:
        if self.last_reported_at is None:
            return False
        elapsed = datetime.now(timezone.utc) - self.last_reported_at
        return elapsed.total_seconds() < self.report_cooldown_seconds

    def _detect(self, image) -> DetectionCandidate | None:
        if self.mock_detections_enabled:
            mapped = map_detection_label(self.mock_detection_label, self.label_map)
            return DetectionCandidate(label=mapped, raw_label=self.mock_detection_label, confidence=0.99)

        if self.model is None or np is None:
            return None

        try:
            results = self.model.predict(
                source=np.array(image),
                verbose=False,
                conf=self.min_confidence,
                imgsz=self.model_input_size,
            )
        except Exception as exc:  # pragma: no cover - runtime inference depends on environment
            self.get_logger().warning(f"YOLO inference failed: {exc}")
            return None

        best_candidate: DetectionCandidate | None = None
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            for box in boxes:
                confidence = float(box.conf[0])
                class_index = int(box.cls[0])
                raw_label = str(names.get(class_index, class_index)).lower()
                label = map_detection_label(raw_label, self.label_map)
                if label.lower() == "background":
                    continue
                if confidence < self.min_confidence or not is_garbage_label(label, self.allowed_labels):
                    continue
                bbox = tuple(float(value) for value in box.xyxy[0].tolist())
                candidate = DetectionCandidate(label=label, raw_label=raw_label, confidence=confidence, bbox=bbox)
                if best_candidate is None or candidate.confidence > best_candidate.confidence:
                    best_candidate = candidate

        return best_candidate

    def _persist_capture(self, image, detection: DetectionCandidate) -> PersistedCapture:
        capture_relative_path = build_capture_relative_path(self.active_task_id or "no-task", detection.label)
        image_path = self.capture_dir / capture_relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)

        snapshot = image.copy()
        if self.save_annotated_capture and detection.bbox and ImageDraw is not None:
            drawer = ImageDraw.Draw(snapshot)
            x1, y1, x2, y2 = detection.bbox
            drawer.rectangle((x1, y1, x2, y2), outline="red", width=4)
            drawer.text((x1, max(0.0, y1 - 24.0)), f"{detection.label} {detection.confidence:.2f}", fill="red")
        snapshot.save(image_path, format="JPEG", quality=92)

        metadata_path = None
        if self.save_sidecar_json:
            metadata_path = image_path.with_suffix(".json")
            persist_detection_metadata(
                metadata_path,
                {
                    "task_id": self.active_task_id,
                    "label": detection.label,
                    "raw_label": detection.raw_label,
                    "confidence": detection.confidence,
                    "bbox": detection.bbox,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "image_path": image_path.as_posix(),
                },
            )

        return PersistedCapture(image_path=image_path, metadata_path=metadata_path)

    def _build_detection_payload(self, detection: DetectionCandidate, image_path: Path) -> dict[str, Any]:
        summary = build_detection_summary(detection.label, detection.confidence, self.room_label_fallback)
        relative_path = image_path.relative_to(self.capture_dir)
        image_url = build_capture_url(relative_path, self.capture_base_url)
        return {
            "task_id": self.active_task_id,
            "room_label": self.room_label_fallback,
            "image_url": image_url,
            "summary": summary,
            "confidence": detection.confidence,
            "source": "rover_vision_yolo",
            "auto_report": True,
        }

    def _post_detection(self, payload: dict[str, Any]) -> None:
        endpoint = f"{self.api_base_url}{self.detection_post_path}"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3.0) as response:
                response.read()
        except (HTTPError, URLError) as exc:  # pragma: no cover - network depends on runtime
            self.get_logger().warning(f"Failed to report garbage detection to API: {exc}")
            return

        self.last_reported_at = datetime.now(timezone.utc)
        self.get_logger().info(
            f"Garbage detection reported for task {self.active_task_id}: {payload['summary']} -> {payload['image_url']}"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GarbageDetectionNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
