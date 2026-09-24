from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.models.assistant import VoiceAssistantRequest, VoiceAssistantResponse, VoiceStatus
from app.services.voice_status import VoiceStatusStore

router = APIRouter(prefix="/voice", tags=["voice"])


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _store(request: Request) -> VoiceStatusStore:
    store = getattr(request.app.state, "voice_status_store", None)
    if store is None:
        store = VoiceStatusStore(settings.voice_status_stale_seconds)
        request.app.state.voice_status_store = store
    return store


def _is_loopback(request: Request) -> bool:
    return request.client is not None and request.client.host in {"127.0.0.1", "::1"}


async def _auth(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=401, detail="voice gateway unauthorized")
    configured = settings.voice_gateway_token.get_secret_value() if settings.voice_gateway_token else ""
    provided = request.headers.get("X-Rover-Voice-Token", "")
    if not configured or not hmac.compare_digest(provided, configured):
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


@router.post("/tts", dependencies=[Depends(_auth)])
async def enqueue_tts(request: Request, payload: TtsRequest) -> dict[str, object]:
    snapshot = _store(request).current()
    if not snapshot.enabled or snapshot.state in {"assistant_unavailable", "audio_unavailable", "tts_error", "disabled"}:
        raise HTTPException(status_code=503, detail="tts_unavailable")
    accepted = _store(request).enqueue_tts(payload.text)
    return {"accepted": accepted, "queued": accepted}


@router.get("/tts/next", dependencies=[Depends(_auth)])
async def next_tts(request: Request) -> dict[str, str | None]:
    return {"text": _store(request).pop_tts()}


@router.post("/session", status_code=status.HTTP_410_GONE)
async def legacy_session() -> None:
    raise HTTPException(status_code=410, detail="legacy voice session endpoint removed")


@router.post("/command", status_code=status.HTTP_410_GONE)
async def legacy_command() -> None:
    raise HTTPException(status_code=410, detail="legacy voice command endpoint removed")
