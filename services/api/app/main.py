from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import api_router
from app.services.assistant_provider import OpenAICompatibleAssistantProvider
from app.services.assistant_service import AssistantService
from app.services.mapping_backend import RosRuntimeMappingBackend
from app.services.camera import CameraService
from app.services.ros_runtime import RosRuntimeStore
from app.services.telemetry import telemetry_stream
from app.services.voice_status import VoiceStatusStore
from app.services.zone_store import ZoneStore


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    ros_runtime = getattr(application.state, "ros_runtime", None)
    created_ros_runtime = ros_runtime is None
    if ros_runtime is None:
        ros_runtime = RosRuntimeStore(
            enabled=settings.ros_bridge_enabled,
            mapping_session_dir=settings.mapping_session_dir,
            mapping_launch_command=settings.ros_mapping_launch_command,
        )
        ros_runtime.start()
        application.state.ros_runtime = ros_runtime
    if getattr(application.state, "camera_service", None) is None:
        application.state.camera_service = CameraService(
            settings.camera_device,
            settings.camera_width,
            settings.camera_height,
            settings.camera_fps,
        )

    backend = getattr(application.state, "mapping_backend", None)
    created_backend = backend is None
    if backend is None:
        backend = RosRuntimeMappingBackend(ros_runtime)
        application.state.mapping_backend = backend

    if getattr(application.state, "voice_status_store", None) is None:
        application.state.voice_status_store = VoiceStatusStore(settings.voice_status_stale_seconds)
    if getattr(application.state, "zone_store", None) is None:
        application.state.zone_store = ZoneStore(Path(settings.mapping_session_dir) / "zones.json")
    if hasattr(ros_runtime, "update_zones"):
        ros_runtime.update_zones(application.state.zone_store.list())

    assistant_service = getattr(application.state, "assistant_service", None)
    created_assistant = False
    if settings.ai_enabled and assistant_service is None:
        settings.validate_assistant_configuration()
        if settings.ai_api_key is None:  # guarded by validate_assistant_configuration
            raise RuntimeError("assistant configuration is incomplete")
        provider = OpenAICompatibleAssistantProvider(
            settings.ai_base_url,
            settings.ai_api_key,
            settings.ai_model,
            settings.ai_timeout_seconds,
            settings.ai_max_output_tokens,
            wire_api=settings.ai_wire_api,
        )
        assistant_service = AssistantService(
            provider,
            backend,
            settings.voice_confirmation_ttl_seconds,
            settings.voice_transcript_max_chars,
        )
        application.state.assistant_service = assistant_service
        created_assistant = True

    try:
        yield
    finally:
        if created_assistant and getattr(application.state, "assistant_service", None) is assistant_service:
            await assistant_service.close()
            del application.state.assistant_service
        if created_backend and getattr(application.state, "mapping_backend", None) is backend:
            await backend.close()
            del application.state.mapping_backend
        if created_ros_runtime and getattr(application.state, "ros_runtime", None) is ros_runtime:
            ros_runtime.close()
            del application.state.ros_runtime


app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    description="Rover backend with a fail-closed mapping and voice gateway.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    backend = getattr(request.app.state, "mapping_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable")
    try:
        mapping_status = await backend.status()
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable") from exc
    if mapping_status.state.value == "error_recoverable":
        raise HTTPException(status_code=503, detail="mapping runtime is unhealthy")
    return {"status": "ok", "mapping_state": mapping_status.state.value}


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        runtime = getattr(websocket.app.state, "ros_runtime", None)
        async for packet in telemetry_stream(settings.telemetry_interval_seconds, runtime):
            packet_payload = packet.model_dump(mode="json")
            await websocket.send_json({**packet_payload, "type": "robot.telemetry", "data": packet_payload})
            if runtime is not None:
                await websocket.send_json({"type": "sensor.snapshot", "data": runtime.sensor_snapshot().model_dump(mode="json")})
                await websocket.send_json({"type": "lidar.scan", "data": runtime.radar_scan().model_dump(mode="json")})
    except WebSocketDisconnect:
        return


static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
