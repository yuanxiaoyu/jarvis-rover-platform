from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient

from app.main import app
from app.services.mapping_backend import InMemoryMappingBackend


@contextmanager
def client_with_backend() -> Iterator[TestClient]:
    backend = InMemoryMappingBackend()
    app.state.mapping_backend = backend
    try:
        with TestClient(app) as client:
            yield client
    finally:
        if getattr(app.state, "mapping_backend", None) is backend:
            del app.state.mapping_backend


def test_mapping_status_is_exposed():
    with client_with_backend() as client:
        response = client.get("/api/v1/mapping")

    assert response.status_code == 200
    assert response.json()["state"] == "idle"
    assert response.json()["motion_allowed"] is False


def test_start_requires_session_id_and_returns_accepted():
    with client_with_backend() as client:
        response = client.post(
            "/api/v1/mapping/start",
            json={"session_id": "room-1"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["state"] == "starting"


def test_pause_is_rejected_when_not_mapping():
    with client_with_backend() as client:
        response = client.post("/api/v1/mapping/pause")

    assert response.status_code == 409
    assert response.json()["detail"]


def test_load_requires_explicit_pose():
    with client_with_backend() as client:
        response = client.post("/api/v1/mapping/load", json={"session_id": "room-1"})

    assert response.status_code == 422


def test_invalid_session_id_is_rejected_by_validation():
    with client_with_backend() as client:
        response = client.post(
            "/api/v1/mapping/start",
            json={"session_id": "../outside"},
        )

    assert response.status_code == 422
