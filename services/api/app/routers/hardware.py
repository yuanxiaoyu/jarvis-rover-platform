from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.hardware import GimbalCommand, GimbalState, RadarScan
from app.services.camera import CameraService
from app.services.ros_runtime import RosRuntimeStore

router = APIRouter(tags=["hardware"])


def _runtime(request: Request) -> RosRuntimeStore:
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        runtime = RosRuntimeStore(enabled=settings.ros_bridge_enabled)
        request.app.state.ros_runtime = runtime
        runtime.start()
    return runtime


def _camera(request: Request) -> CameraService:
    camera = getattr(request.app.state, "camera_service", None)
    if camera is None:
        camera = CameraService(settings.camera_device, settings.camera_width, settings.camera_height, settings.camera_fps)
        request.app.state.camera_service = camera
    return camera


@router.get("/camera/status")
def camera_status(request: Request) -> dict[str, object]:
    return _camera(request).status()


@router.get("/camera/mjpeg")
async def camera_mjpeg(request: Request) -> StreamingResponse:
    camera = _camera(request)
    status = camera.status()
    if not status["available"]:
        raise HTTPException(status_code=503, detail=status["error"])

    async def body():
        async for frame in camera.frames():
            if await request.is_disconnected():
                break
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"

    return StreamingResponse(body(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})


@router.get("/radar", response_model=RadarScan)
def radar(request: Request) -> RadarScan:
    return _runtime(request).radar_scan()


@router.get("/gimbal", response_model=GimbalState)
def gimbal_status(request: Request) -> GimbalState:
    runtime = _runtime(request)
    state = runtime.gimbal_state()
    # Keep configured topic names visible even when ROS is unavailable.
    state.pan_topic = settings.gimbal_pan_topic
    state.tilt_topic = settings.gimbal_tilt_topic
    return state


@router.post("/gimbal", response_model=GimbalState)
def gimbal_command(request: Request, payload: GimbalCommand) -> GimbalState:
    if not payload.has_axis():
        raise HTTPException(status_code=422, detail="至少提供一个云台轴角度")
    if payload.pan_deg is not None and not settings.gimbal_pan_min_deg <= payload.pan_deg <= settings.gimbal_pan_max_deg:
        raise HTTPException(status_code=422, detail="水平角度超出安全范围")
    if payload.tilt_deg is not None and not settings.gimbal_tilt_min_deg <= payload.tilt_deg <= settings.gimbal_tilt_max_deg:
        raise HTTPException(status_code=422, detail="俯仰角度超出安全范围")
    try:
        state = _runtime(request).command_gimbal(payload.pan_deg, payload.tilt_deg)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    state.pan_topic = settings.gimbal_pan_topic
    state.tilt_topic = settings.gimbal_tilt_topic
    return state


@router.get("/hardware/status")
def hardware_status(request: Request) -> dict[str, object]:
    runtime = _runtime(request)
    return {
        "ros": {"enabled": settings.ros_bridge_enabled, "available": runtime.error is None, "error": runtime.error},
        "camera": _camera(request).status(),
        "radar": runtime.radar_scan().model_dump(mode="json"),
        "gimbal": runtime.gimbal_state().model_dump(mode="json"),
    }
