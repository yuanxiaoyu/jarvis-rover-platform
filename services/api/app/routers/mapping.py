from fastapi import APIRouter, HTTPException, Request

from app.models.mapping import MappingCommandResult, MappingStatus, PoseRequest, SaveRequest, SessionRequest

router = APIRouter(prefix="/mapping", tags=["mapping"])


def _backend(request: Request):
    backend = getattr(request.app.state, "mapping_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable")
    return backend


def _check(result: MappingCommandResult) -> MappingCommandResult:
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.get("/status", response_model=MappingStatus)
async def mapping_status(request: Request) -> MappingStatus:
    return await _backend(request).status()


@router.post("/start", response_model=MappingCommandResult)
async def start_mapping(request: Request, payload: SessionRequest) -> MappingCommandResult:
    return _check(await _backend(request).start(payload.session_id))


@router.post("/pause", response_model=MappingCommandResult)
async def pause_mapping(request: Request) -> MappingCommandResult:
    return _check(await _backend(request).pause())


@router.post("/resume", response_model=MappingCommandResult)
async def resume_mapping(request: Request) -> MappingCommandResult:
    return _check(await _backend(request).resume())


@router.post("/stop", response_model=MappingCommandResult)
async def stop_mapping(request: Request) -> MappingCommandResult:
    return _check(await _backend(request).stop())


@router.post("/save", response_model=MappingCommandResult)
async def save_mapping(request: Request, payload: SaveRequest) -> MappingCommandResult:
    return _check(await _backend(request).save(payload.map_name))


@router.post("/load", response_model=MappingCommandResult)
async def load_mapping(request: Request, payload: PoseRequest) -> MappingCommandResult:
    return _check(await _backend(request).load(payload))
