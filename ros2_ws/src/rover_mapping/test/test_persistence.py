import json

import pytest

from rover_mapping.persistence import SessionStore


MAP_YAML = """\
image: map.pgm
resolution: 0.05
origin: [0.0, 0.0, 0.0]
occupied_thresh: 0.65
free_thresh: 0.196
negate: 0
"""
MAP_PGM = b"P5\n2 1\n255\n\xff\x00"
POSEGRAPH = b"pose_graph-v1"


def test_save_revision_can_be_loaded_and_writes_manifest(tmp_path):
    store = SessionStore(tmp_path)
    metadata = {"source": "test", "robot": "rover-1"}

    revision = store.save_revision(
        session_id="room-1",
        map_name="living-room",
        map_pgm=MAP_PGM,
        map_yaml=MAP_YAML,
        pose_graph=POSEGRAPH,
        metadata=metadata,
    )

    loaded = store.load_current("room-1")
    assert loaded["revision"] == revision
    assert loaded["revision_id"] == revision
    assert loaded["session_id"] == "room-1"
    assert loaded["map_name"] == "living-room"
    assert loaded["map_pgm_sha256"]
    assert loaded["metadata"] == metadata
    manifest_path = tmp_path / "sessions" / "room-1" / "revisions" / revision / "manifest.json"
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text())["schema_version"] == 1


def test_empty_revision_does_not_change_current_pointer(tmp_path):
    store = SessionStore(tmp_path)
    first_revision = store.save_revision(
        session_id="room-1",
        map_name="living-room",
        map_pgm=MAP_PGM,
        map_yaml=MAP_YAML,
        pose_graph=POSEGRAPH,
        metadata={},
    )

    with pytest.raises(ValueError):
        store.save_revision(
            session_id="room-1",
            map_name="living-room",
            map_pgm=b"",
            map_yaml=MAP_YAML,
            pose_graph=POSEGRAPH,
            metadata={},
        )

    assert store.load_current("room-1")["revision"] == first_revision


@pytest.mark.parametrize(
    ("session_id", "map_name"),
    [("../outside", "living-room"), ("room-1", "../../outside")],
)
def test_save_revision_rejects_path_traversal(session_id, map_name, tmp_path):
    store = SessionStore(tmp_path)

    with pytest.raises(ValueError):
        store.save_revision(
            session_id=session_id,
            map_name=map_name,
            map_pgm=MAP_PGM,
            map_yaml=MAP_YAML,
            pose_graph=POSEGRAPH,
            metadata={},
        )


def test_save_revision_preserves_posegraph_companion(tmp_path):
    store = SessionStore(tmp_path)
    revision = store.save_revision(
        "room-1",
        "living-room",
        MAP_PGM,
        MAP_YAML,
        POSEGRAPH,
        {},
        b"posegraph-data-v1",
    )

    paths = store.resolve_current_paths("room-1")
    assert paths.posegraph.is_file()
    assert paths.posegraph_data.read_bytes() == b"posegraph-data-v1"
    assert "posegraph.data" in store.load_current("room-1")["files"]



    store = SessionStore(tmp_path)
    revision = store.save_revision(
        session_id="room-1",
        map_name="living-room",
        map_pgm=MAP_PGM,
        map_yaml=MAP_YAML,
        pose_graph=POSEGRAPH,
        metadata={},
    )
    manifest_path = tmp_path / "sessions" / "room-1" / "revisions" / revision / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["map.pgm"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError):
        store.load_current("room-1")
