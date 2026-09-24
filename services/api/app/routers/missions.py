import asyncio
from fastapi import APIRouter, HTTPException, Request

from app.models.mapping import MappingCommandResult, SessionRequest
from app.models.mission import AiCommandRequest, MissionMode, MissionState, NavigateRequest
from app.state import MISSION_STATE

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("/navigate", response_model=MissionState)
def navigate_to_zone(request: NavigateRequest) -> MissionState:
    raise HTTPException(
        status_code=503,
        detail="Nav2 path execution is unavailable; use /api/v1/navigation/plan for a collision-checked preview",
    )


@router.post("/ai-command", response_model=MissionState)
def submit_ai_command(request: AiCommandRequest) -> MissionState:
    raise HTTPException(status_code=503, detail="任务执行器未连接；请使用助手对话接口进行安全的自然语言交互")


def _runtime(request: Request):
    runtime = getattr(request.app.state, "ros_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="ROS runtime is unavailable")
    return runtime


@router.get("/exploration/status", response_model=MissionState)
def exploration_status(request: Request) -> MissionState:
    runtime = _runtime(request)
    if not hasattr(runtime, "mission_state"):
        return MISSION_STATE
    return runtime.mission_state()


@router.post("/exploration/start", response_model=MappingCommandResult)
async def start_exploration(request: Request, payload: SessionRequest) -> MappingCommandResult:
    runtime = _runtime(request)
    if not hasattr(runtime, "start_exploration"):
        raise HTTPException(status_code=503, detail="autonomous exploration runtime is unavailable")
    zones = getattr(request.app.state, "zone_store", None)
    zone_list = zones.list() if zones is not None else []
    result = await asyncio.to_thread(runtime.start_exploration, payload.session_id, zone_list)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.post("/exploration/pause", response_model=MappingCommandResult)
async def pause_exploration(request: Request) -> MappingCommandResult:
    result = await asyncio.to_thread(_runtime(request).pause_mapping)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.post("/exploration/resume", response_model=MappingCommandResult)
async def resume_exploration(request: Request) -> MappingCommandResult:
    result = await asyncio.to_thread(_runtime(request).resume_mapping)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.post("/exploration/stop", response_model=MappingCommandResult)
async def stop_exploration(request: Request) -> MappingCommandResult:
    result = await asyncio.to_thread(_runtime(request).stop_mapping)
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result
