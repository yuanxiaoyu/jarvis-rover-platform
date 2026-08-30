from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import api_router
from app.services.mapping_backend import InMemoryMappingBackend, RosMappingBackend
from app.services.ros_bridge import RosMappingBridge
from app.services.telemetry import telemetry_stream


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    existing_backend = getattr(application.state, "mapping_backend", None)
    backend = existing_backend
    created_backend = backend is None
    if backend is None:
        if settings.ros_bridge_enabled:
            bridge = RosMappingBridge(
                command_service=settings.ros_command_service,
                status_topic=settings.ros_status_topic,
                service_timeout_seconds=settings.ros_service_timeout_seconds,
                status_timeout_seconds=settings.ros_status_timeout_seconds,
            )
            try:
                await bridge.start()
            except RuntimeError:
                if settings.ros_bridge_required:
                    raise
                backend = InMemoryMappingBackend()
            else:
                backend = RosMappingBackend(bridge)
        else:
            backend = InMemoryMappingBackend()
        application.state.mapping_backend = backend
    try:
        yield
    finally:
        if created_backend and backend is not None:
            await backend.close()
            if getattr(application.state, "mapping_backend", None) is backend:
                del application.state.mapping_backend


app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    description="Rover backend with a ROS-backed mapping session lifecycle.",
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
        async for packet in telemetry_stream(settings.telemetry_interval_seconds):
            await websocket.send_json(packet.model_dump(mode="json"))
    except WebSocketDisconnect:
        return


static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
