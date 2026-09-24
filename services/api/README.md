# Rover API (Scaffold)

This service provides a FastAPI backend scaffold for rover control-plane features:

- REST API for map, semantic zones, tasks, voice commands, and sensor snapshots
- WebSocket mock telemetry stream for frontend and integration testing
- Data models aligned to **MS200 TOF lidar 2D mapping** constraints

## Mapping model assumptions

- Mapping source is 2D occupancy/grid from MS200 TOF lidar
- "3D view" is represented as reconstructed layers from occupancy geometry + semantic zones metadata
- This API does not model true volumetric scans

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Endpoints

- `GET /health`
- `GET /api/v1/system/snapshot`
- `GET|PUT /api/v1/map`
- `GET|POST|DELETE /api/v1/zones`
- `GET|POST|PATCH /api/v1/tasks`
- `POST /api/v1/missions/navigate`
- `POST /api/v1/missions/ai-command`
- `POST /api/v1/voice/assistant` (loopback + gateway token)
- `GET /api/v1/voice/status`
- `POST /api/v1/voice/heartbeat` (loopback + gateway token)
- Legacy `/api/v1/voice/session` and `/api/v1/voice/command` return `410 Gone`
- `GET /api/v1/sensors`
- `WS /ws/telemetry`
