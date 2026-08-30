"""Durable, crash-safe storage for mapping session revisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FILE_NAMES = ("map.pgm", "map.yaml", "posegraph")
_OPTIONAL_FILE_NAMES = ("posegraph.data",)


@dataclass(frozen=True)
class RevisionPaths(Mapping[str, Path]):
    """Paths belonging to one revision directory."""

    directory: Path
    map_pgm: Path
    map_yaml: Path
    posegraph: Path
    posegraph_data: Path
    manifest: Path

    @property
    def pose_graph(self) -> Path:
        """Compatibility alias for the public pose graph terminology."""
        return self.posegraph

    def __getitem__(self, key: str) -> Path:
        values = {
            "directory": self.directory,
            "map.pgm": self.map_pgm,
            "map.yaml": self.map_yaml,
            "posegraph": self.posegraph,
            "pose_graph": self.posegraph,
            "posegraph.data": self.posegraph_data,
            "manifest.json": self.manifest,
            "map_pgm": self.map_pgm,
            "map_yaml": self.map_yaml,
        }
        try:
            return values[key]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self):
        return iter(("directory", "map.pgm", "map.yaml", "posegraph", "posegraph.data", "manifest.json"))

    def __len__(self) -> int:
        return 6


class SessionStore:
    """Store immutable map revisions and an atomically replaced current pointer."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def revision_paths(self, session_id: str, revision: str) -> RevisionPaths:
        _validate_component(session_id, "session_id")
        _validate_component(revision, "revision")
        directory = self.root / "sessions" / session_id / "revisions" / revision
        return RevisionPaths(
            directory=directory,
            map_pgm=directory / "map.pgm",
            map_yaml=directory / "map.yaml",
            posegraph=directory / "posegraph",
            posegraph_data=directory / "posegraph.data",
            manifest=directory / "manifest.json",
        )

    def resolve_current_paths(self, session_id: str) -> RevisionPaths:
        """Resolve the current pointer without allowing it to escape the store."""
        _validate_component(session_id, "session_id")
        current_path = self.root / "sessions" / session_id / "current.json"
        try:
            pointer = _read_json(current_path)
            revision = pointer.get("revision_id", pointer.get("revision"))
            if pointer.get("session_id") != session_id:
                raise ValueError("current pointer session mismatch")
            _validate_component(revision, "revision")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"invalid current pointer for {session_id!r}") from exc
        return self.revision_paths(session_id, revision)

    def save_revision(
        self,
        session_id: str,
        map_name: str,
        map_pgm: bytes,
        map_yaml: str,
        pose_graph: bytes,
        metadata: Mapping[str, Any] | None = None,
        posegraph_data: bytes | None = None,
    ) -> str:
        """Persist a complete revision and make it current only after validation."""
        _validate_component(session_id, "session_id")
        _validate_component(map_name, "map_name")
        if not isinstance(map_pgm, bytes) or not map_pgm:
            raise ValueError("map_pgm must be non-empty bytes")
        if not isinstance(map_yaml, str) or not map_yaml:
            raise ValueError("map_yaml must be a non-empty string")
        if not isinstance(pose_graph, bytes) or not pose_graph:
            raise ValueError("pose_graph must be non-empty bytes")
        if posegraph_data is not None and (
            not isinstance(posegraph_data, bytes) or not posegraph_data
        ):
            raise ValueError("posegraph_data must be non-empty bytes when supplied")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ValueError("metadata must be a mapping")

        # UUIDs satisfy the component contract and make retries collision-free.
        revision = str(uuid.uuid4())
        session_dir = self.root / "sessions" / session_id
        revisions_dir = session_dir / "revisions"
        staging = revisions_dir / f".staging-{uuid.uuid4()}"
        final_paths = self.revision_paths(session_id, revision)
        created_final = False
        pointer_replaced = False
        try:
            staging.mkdir(parents=True, exist_ok=False)
            _write_durable(staging / "map.pgm", map_pgm)
            _write_durable(staging / "map.yaml", map_yaml.encode("utf-8"))
            _write_durable(staging / "posegraph", pose_graph)
            if posegraph_data is not None:
                _write_durable(staging / "posegraph.data", posegraph_data)
            files = {}
            for file_name in _FILE_NAMES + tuple(
                name for name in _OPTIONAL_FILE_NAMES if (staging / name).is_file()
            ):
                file_path = staging / file_name
                size, digest = _file_digest(file_path)
                files[file_name] = {
                    "sha256": digest,
                    "size": size,
                }
            # Validate serializability before exposing the revision.
            manifest = {
                "schema_version": 1,
                "session_id": session_id,
                "map_name": map_name,
                "revision": revision,
                "revision_id": revision,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "files": files,
                "metadata": dict(metadata),
            }
            manifest_bytes = _json_bytes(manifest)
            manifest_tmp = staging / f".manifest-{uuid.uuid4()}"
            _write_durable(manifest_tmp, manifest_bytes)
            os.replace(manifest_tmp, staging / "manifest.json")
            _fsync_directory(staging)
            _fsync_directory(revisions_dir)
            os.replace(staging, final_paths.directory)
            created_final = True
            _fsync_directory(revisions_dir)

            pointer = {
                "schema_version": 1,
                "session_id": session_id,
                "map_name": map_name,
                "revision": revision,
                "revision_id": revision,
                "map_pgm_sha256": files["map.pgm"]["sha256"],
            }
            pointer_tmp = session_dir / f".current-{uuid.uuid4()}"
            try:
                _write_durable(pointer_tmp, _json_bytes(pointer))
                os.replace(pointer_tmp, session_dir / "current.json")
                pointer_replaced = True
                _fsync_directory(session_dir)
            finally:
                pointer_tmp.unlink(missing_ok=True)
            return revision
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if created_final and not pointer_replaced:
                shutil.rmtree(final_paths.directory, ignore_errors=True)
                if revisions_dir.exists():
                    _fsync_directory(revisions_dir)
            raise

    def load_current(self, session_id: str) -> dict[str, Any]:
        """Load and verify the current revision, raising ValueError on corruption."""
        _validate_component(session_id, "session_id")
        session_dir = self.root / "sessions" / session_id
        current_path = session_dir / "current.json"
        try:
            pointer = _read_json(current_path)
            if pointer.get("schema_version") != 1:
                raise ValueError("unsupported current pointer schema")
            if pointer.get("session_id") != session_id:
                raise ValueError("current pointer session mismatch")
            revision = pointer.get("revision_id", pointer.get("revision"))
            map_name = pointer["map_name"]
            _validate_component(revision, "revision")
            _validate_component(map_name, "map_name")
            paths = self.revision_paths(session_id, revision)
            manifest = _read_json(paths.manifest)
            if manifest.get("schema_version") != 1:
                raise ValueError("unsupported manifest schema")
            if manifest.get("session_id") != session_id:
                raise ValueError("manifest identity mismatch")
            manifest_revision = manifest.get("revision_id", manifest.get("revision"))
            if manifest_revision != revision:
                raise ValueError("manifest identity mismatch")
            if manifest.get("map_name") != map_name:
                raise ValueError("manifest map mismatch")
            files = manifest["files"]
            if not isinstance(files, dict):
                raise ValueError("manifest files must be an object")
            for name in _FILE_NAMES + tuple(
                name for name in _OPTIONAL_FILE_NAMES if name in files
            ):
                entry = files[name]
                if not isinstance(entry, dict):
                    raise ValueError(f"invalid file entry for {name}")
                expected = entry.get("sha256")
                expected_size = entry.get("size")
                if (
                    not isinstance(expected, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected)
                    or not isinstance(expected_size, int)
                    or expected_size <= 0
                ):
                    raise ValueError(f"invalid file metadata for {name}")
                size, actual = _file_digest(paths[name])
                if size != expected_size or actual != expected:
                    raise ValueError(f"hash mismatch for {name}")
            if pointer.get("map_pgm_sha256") != files["map.pgm"]["sha256"]:
                raise ValueError("current map hash mismatch")
            result = dict(manifest)
            result["revision_id"] = revision
            result["revision"] = revision
            result["map_pgm_sha256"] = files["map.pgm"]["sha256"]
            return result
        except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("invalid"):
                raise
            raise ValueError(f"corrupt current revision for {session_id!r}") from exc


def _validate_component(value: str, name: str) -> None:
    if not isinstance(value, str) or _COMPONENT_RE.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")


def _file_digest(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _write_durable(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
