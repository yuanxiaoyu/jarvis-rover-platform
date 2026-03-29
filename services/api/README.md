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
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Endpoints

- `GET /health`
- `GET /api/v1/system/snapshot`
- `GET|PUT /api/v1/map`
- `GET|POST|DELETE /api/v1/zones`
- `GET|POST|PATCH /api/v1/tasks`
- `POST /api/v1/missions/navigate`
- `POST /api/v1/missions/ai-command`
- `POST /api/v1/missions/whole-home-garbage-scan`
- `POST /api/v1/voice/session`
- `POST /api/v1/voice/command`
- `GET|POST /api/v1/garbage/detections`
- `GET /api/v1/sensors`
- `WS /ws/telemetry`

## 垃圾发现上报

新增了一条与“整屋扫描+发现垃圾”场景配套的报告链路。语音指令会触发专门的扫描任务，任务执行过程中视觉算法可通过 `POST /api/v1/garbage/detections` 回传垃圾位置信息、语义描述和抓拍照片。API 会把检测结果写入状态存储，并在开启自动上报时同步到 `OpenClaw` webhook。

相关环境变量：

- `ROVER_OPENCLAW_ENABLED`：是否启用 OpenClaw 上报，默认 `true`
- `ROVER_OPENCLAW_WEBHOOK_URL`：OpenClaw 实例提供的 webhook 地址
- `ROVER_OPENCLAW_TIMEOUT_SECONDS`：上报超时时间，默认 `5.0`
- `ROVER_OPENCLAW_REPORT_TARGET`：OpenClaw 侧目标通道标识，默认 `feishu`

上报 payload 包括：发现时间、任务 ID、房间标签、描述、置信度和图片 URL。OpenClaw 接到该 webhook 后，再将图片和文本转发到已经绑定的飞书群或应用。
