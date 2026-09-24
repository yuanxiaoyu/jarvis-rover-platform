from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from app.models.zone import Zone


class ZoneStore:
    """Small atomic JSON store for user-defined map regions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._zones: dict[str, Zone] | None = None

    def list(self) -> list[Zone]:
        with self._lock:
            self._load()
            return [zone.model_copy(deep=True) for zone in self._zones.values()]

    def get(self, zone_id: str) -> Zone | None:
        with self._lock:
            self._load()
            zone = self._zones.get(zone_id)
            return zone.model_copy(deep=True) if zone else None

    def create(self, zone: Zone) -> Zone:
        with self._lock:
            self._load()
            if zone.zone_id in self._zones:
                raise ValueError("zone_id already exists")
            self._zones[zone.zone_id] = zone.model_copy(deep=True)
            self._persist()
            return self._zones[zone.zone_id].model_copy(deep=True)

    def update(self, zone_id: str, zone: Zone) -> Zone | None:
        with self._lock:
            self._load()
            if zone_id not in self._zones:
                return None
            if zone.zone_id != zone_id and zone.zone_id in self._zones:
                raise ValueError("zone_id already exists")
            if zone.zone_id != zone_id:
                del self._zones[zone_id]
            self._zones[zone_id] = zone.model_copy(deep=True)
            self._persist()
            return zone.model_copy(deep=True)

    def delete(self, zone_id: str) -> bool:
        with self._lock:
            self._load()
            if zone_id not in self._zones:
                return False
            del self._zones[zone_id]
            self._persist()
            return True

    def _load(self) -> None:
        if self._zones is not None:
            return
        if not self.path.exists():
            self._zones = {}
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("stored zones must be a JSON array")
        zones = [Zone.model_validate(item) for item in payload]
        self._zones = {zone.zone_id: zone for zone in zones}
        if len(self._zones) != len(zones):
            raise ValueError("stored zone ids are not unique")

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump([zone.model_dump(mode="json") for zone in self._zones.values()], output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
