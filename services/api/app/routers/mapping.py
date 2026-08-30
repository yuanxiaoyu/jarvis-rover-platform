"""REST endpoints for the mapping session lifecycle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.mapping import (
    MappingCommandResult,
    MappingStatus,
    PoseRequest,
    SaveRequest,
    SessionRequest,
)
from app.services.mapping_backend import MappingBackend

router = APIRouter(prefix="/mapping", tags=["mapping"])


def get_mapping_backend(request: Request) -> MappingBackend:
    backend = getattr(request.app.state, "mapping_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable")
    return backend


@router.get("", response_model=MappingStatus)
async def get_mapping_status(
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingStatus:
    return await _status_call(backend.status)


@router.post("/start", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def start_mapping(
    request: SessionRequest,
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(lambda: backend.start(request.session_id))


@router.post("/pause", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def pause_mapping(
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(backend.pause)


@router.post("/resume", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def resume_mapping(
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(backend.resume)


@router.post("/stop", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def stop_mapping(
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(backend.stop)


@router.post("/save", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def save_mapping(
    request: SaveRequest,
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(lambda: backend.save(request.map_name))


@router.post("/load", response_model=MappingCommandResult, status_code=status.HTTP_202_ACCEPTED)
async def load_mapping(
    request: PoseRequest,
    backend: MappingBackend = Depends(get_mapping_backend),
) -> MappingCommandResult:
    return await _command_call(lambda: backend.load(request))


async def _status_call(operation: Callable[[], Awaitable[MappingStatus]]) -> MappingStatus:
    try:
        return await operation()
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable") from exc


async def _command_call(
    operation: Callable[[], Awaitable[MappingCommandResult]],
) -> MappingCommandResult:
    try:
        result = await operation()
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="mapping backend is unavailable") from exc
    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.message or "mapping command rejected")
    return result
