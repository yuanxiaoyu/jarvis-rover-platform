from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.assistant import VoiceAssistantRequest, VoiceAssistantResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    transcript: str = Field(min_length=1, max_length=1000)


@router.post("/chat", response_model=VoiceAssistantResponse)
async def chat(request: Request, payload: ChatRequest) -> VoiceAssistantResponse:
    service = getattr(request.app.state, "assistant_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="assistant_unavailable")
    session_id = payload.session_id or f"web-{uuid4().hex[:12]}"
    voice_request = VoiceAssistantRequest(
        session_id=session_id,
        turn_id=f"turn-{uuid4().hex[:12]}",
        transcript=payload.transcript,
        source="web-text",
    )
    result = await service.handle(voice_request)
    # Queue only the bounded assistant reply. A host-local voice service may
    # consume it through /voice/tts/next; the browser never receives a secret.
    if result.state in {"completed", "awaiting_confirmation", "executed", "rejected"}:
        status_store = getattr(request.app.state, "voice_status_store", None)
        if status_store is not None:
            status_store.enqueue_tts(result.reply_text)
    return result
