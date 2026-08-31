# Rover API

This service provides the FastAPI control plane for the rover platform:

- REST API for maps, mapping sessions, semantic zones, tasks, voice commands, and sensors;
- a WebSocket telemetry stream for frontend and integration testing;
- Pydantic models aligned to MS200 TOF lidar 2D mapping constraints;
- an optional background rclpy bridge for the real mapping-session service.

The API does not model true volumetric scans. A future 3D view is reconstructed from occupancy geometry and semantic zones.

## Run locally without ROS

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ROVER_ROS_BRIDGE_ENABLED=false uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

When the bridge is disabled, the API uses a deterministic in-memory backend and never sends commands to a robot.

## Run with the ROS mapping runtime

The production runtime sets:

```dotenv
ROS_DOMAIN_ID=20
ROVER_ROS_BRIDGE_ENABLED=true
ROVER_ROS_BRIDGE_REQUIRED=true
ROVER_ROS_SERVICE_TIMEOUT_SECONDS=10
```

If `ROVER_ROS_BRIDGE_REQUIRED=true`, API startup fails when `/mapping/command` cannot be reached; it never silently falls back to a fake backend.

## Endpoints

- `GET /health`
- `GET /api/v1/system/snapshot`
- `GET|PUT /api/v1/map`
- `GET|POST|DELETE /api/v1/zones`
- `GET|POST|PATCH /api/v1/tasks`
- `GET /api/v1/mapping`
- `POST /api/v1/mapping/start`
- `POST /api/v1/mapping/pause`
- `POST /api/v1/mapping/resume`
- `POST /api/v1/mapping/stop`
- `POST /api/v1/mapping/save`
- `POST /api/v1/mapping/load`
- `POST /api/v1/missions/navigate`
- `POST /api/v1/missions/ai-command`
- `POST /api/v1/voice/assistant` (loopback plus `X-Rover-Voice-Token`)
- `GET /api/v1/voice/status`
- `POST /api/v1/voice/heartbeat` (host service only)
- `GET /api/v1/sensors`
- `WS /ws/telemetry`

`202` means the mapping command was accepted by the session worker, not that motion has already started. Poll `GET /api/v1/mapping` until the state is stable. `409` is a state conflict, `422` is invalid request data, and `503` means the ROS bridge/service is unavailable.

A load request must contain `session_id`, `x`, `y`, `yaw`, and `match_type` (`2` for `START_AT_GIVEN_POSE`, `3` for `LOCALIZE_AT_POSE`). The server validates the model and the ROS mapping node validates the saved map and free-space pose again.

## Mapping model assumptions

- Mapping source is a 2D occupancy grid from the MS200 TOF lidar.
- A pose graph and map are saved as versioned revisions under the configured session directory.
- The 3D view is reconstructed from occupancy geometry and semantic-zone metadata.
- `WS /ws/telemetry` remains a lightweight/mock telemetry stream until a dedicated ROS map stream is enabled.
# Voice gateway

The authenticated local gateway is available at `/api/v1/voice/assistant`, `/api/v1/voice/status`, and `/api/v1/voice/heartbeat`. It accepts only loopback requests with `X-Rover-Voice-Token`; AI configuration uses `ROVER_AI_BASE_URL`, `ROVER_AI_MODEL`, and protected `ROVER_AI_API_KEY`.
