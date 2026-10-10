# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Voice API: a mic's audio in, text for the composer's draft out.

GET    /voice                     whether this hub can transcribe, and at what rate
POST   /voice/sessions/{id}       a chunk of one open mic's audio; ``?final=true`` closes it
DELETE /voice/sessions/{id}       close a mic without transcribing what's left

The app sends raw 16 kHz mono 16-bit little-endian PCM a fraction of a second
at a time while the mic is on, and appends each text it gets back to the draft.
The id is the app's own random one per open mic. Plain HTTP rather than a
socket, so it goes through the same proxy and sign-in as every other route.
See ``app/services/voice.py``.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.schemas import VoiceHeard, VoiceStatus
from app.services import actor, voice

router = APIRouter(prefix="/voice", tags=["voice"])

# A chunk is normally under a second of audio (32 KB); this allows a minute,
# so a slow connection catching up isn't refused.
MAX_CHUNK_BYTES = 60 * voice.SAMPLE_RATE * 2

SessionId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{16,64}$", description="The app's id for one open mic")
]


@router.get("", response_model=VoiceStatus)
async def voice_status() -> VoiceStatus:
    """Whether a mic can be turned on against this hub."""
    state, detail = voice.state()
    return VoiceStatus(
        state=state,
        detail=detail,
        language=voice.LANGUAGE,
        sample_rate=voice.SAMPLE_RATE,
        model=voice.MOONSHINE,
    )


@router.post(
    "/sessions/{session_id}",
    response_model=VoiceHeard,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def hear(
    session_id: SessionId,
    request: Request,
    final: Annotated[bool, Query(description="The mic is being turned off")] = False,
) -> VoiceHeard:
    """Take a chunk of audio; return the text of any speech it finished."""
    declared = request.headers.get("content-length")
    if declared and int(declared) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="This chunk is longer than a minute of audio")
    audio = await request.body()
    if len(audio) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="This chunk is longer than a minute of audio")
    if len(audio) % 2:
        raise HTTPException(
            status_code=422, detail="Audio is 16-bit samples, so a chunk is an even number of bytes"
        )
    try:
        heard = await asyncio.to_thread(
            voice.feed, session_id, audio, final=final, caller=_caller(request)
        )
    except voice.VoiceWarming:
        # The model is loading: this chunk wasn't read, so the app sends it again.
        return VoiceHeard(ready=False)
    except voice.VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Voice isn't available: {exc}") from exc
    return VoiceHeard(texts=heard.texts, speaking=heard.speaking)


@router.delete("/sessions/{session_id}", status_code=204)
async def close(session_id: SessionId, request: Request) -> None:
    """Close a mic, dropping whatever it was in the middle of hearing."""
    voice.end(session_id, _caller(request))


def _caller(request: Request) -> str | None:
    """The signed-in caller a mic belongs to, or ``None`` on a hub with sign-in off."""
    principal = actor.current_principal(request)
    return principal.handle if principal else None
