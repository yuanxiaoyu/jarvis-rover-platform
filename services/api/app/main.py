from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import api_router
from app.services.telemetry import telemetry_stream

app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    description="Rover backend scaffold with 2D mapping + reconstructed 3D metadata.",
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
def health() -> dict[str, str]:
    return {"status": "ok"}


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
