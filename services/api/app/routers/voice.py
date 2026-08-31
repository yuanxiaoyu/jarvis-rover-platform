from __future__ import annotations

import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.config import settings
from app.models.assistant import VoiceAssistantRequest, VoiceAssistantResponse, VoiceStatus
from app.services.voice_status import VoiceStatusStore

router = APIRouter(prefix="/voice", tags=["voice"])


def _store(request: Request) -> VoiceStatusStore:
    store = getattr(request.app.state, "voice_status_store", None)
    if store is None:
        store = VoiceStatusStore(settings.voice_status_stale_seconds)
        request.app.state.voice_status_store = store
    return store


async def _auth(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=401, detail="voice gateway unauthorized")
    configured = settings.voice_gateway_token.get_secret_value() if settings.voice_gateway_token else ""
    if not configured or not hmac.compare_digest(request.headers.get("X-Rover-Voice-Token", ""), configured):
        raise HTTPException(status_code=401, detail="voice gateway unauthorized")


@router.post("/assistant", response_model=VoiceAssistantResponse, dependencies=[Depends(_auth)])
async def assistant(request: Request, payload: VoiceAssistantRequest) -> VoiceAssistantResponse:
    service = getattr(request.app.state, "assistant_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="assistant_unavailable")
    return await service.handle(payload)


@router.get("/status", response_model=VoiceStatus)
async def voice_status(request: Request) -> VoiceStatus:
    return _store(request).current()


@router.post("/heartbeat", response_model=VoiceStatus, dependencies=[Depends(_auth)])
async def heartbeat(request: Request, payload: VoiceStatus) -> VoiceStatus:
    _store(request).update(payload)
    return payload


@router.post("/session", status_code=status.HTTP_410_GONE)
async def legacy_session() -> None:
    raise HTTPException(status_code=410, detail="legacy voice session endpoint removed")


@router.post("/command", status_code=status.HTTP_410_GONE)
async def legacy_command() -> None:
    raise HTTPException(status_code=410, detail="legacy voice command endpoint removed")
