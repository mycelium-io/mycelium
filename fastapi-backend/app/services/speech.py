# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading notifications aloud: text in, a speech server's audio out.

The operator runs an OpenAI-style text-to-speech server and names it in
``voice.speech_url`` (``VOICE_SPEECH_URL``). The app asks the hub
(``POST /voice/speech``) and the hub asks that server, so a page served over
https can use a server on plain http, the server needs no CORS headers, and
its key stays on the hub. The address only ever comes from the hub's own
setting: the route takes text, never a URL, so a caller can't point the hub
at anything else. Mycelium ships no speech model.
"""

from __future__ import annotations

import httpx

from app.config import settings

#: The longest text one request may ask for. The app sends a sentence at a
#: time, so this is well past what it needs.
MAX_TEXT = 1000

#: How long the speech server has to answer.
TIMEOUT_S = 30.0

#: The most audio one answer may carry: minutes of speech, far past a sentence.
MAX_AUDIO_BYTES = 10 * 1024 * 1024

#: The path an OpenAI-style server takes speech requests at.
SPEECH_PATH = "/audio/speech"

#: How the hub reaches the server; tests replace it with a mock transport.
_transport: httpx.AsyncBaseTransport | None = None


class SpeechUnavailable(RuntimeError):
    """No speech server is set on this hub, or its address isn't one."""


class SpeechFailed(RuntimeError):
    """The speech server didn't give back audio, with the reason the app shows."""


def configured() -> bool:
    """Whether a speech server is set, so the app can offer to read aloud."""
    return bool((settings.VOICE_SPEECH_URL or "").strip())


def endpoint() -> str:
    """The address speech requests go to: the setting, with ``/audio/speech``
    added unless it ends with it already."""
    url = (settings.VOICE_SPEECH_URL or "").strip().rstrip("/")
    if not url:
        msg = "No speech server is set on this hub (voice.speech_url)."
        raise SpeechUnavailable(msg)
    if not url.lower().startswith(("http://", "https://")):
        msg = "voice.speech_url isn't an http:// or https:// address."
        raise SpeechUnavailable(msg)
    return url if url.endswith(SPEECH_PATH) else url + SPEECH_PATH


def body(text: str) -> dict[str, str]:
    """The OpenAI-style request: the text, mp3 back, and the model and voice
    only when the hub sets them, so a server's own defaults apply otherwise."""
    out = {"input": text, "response_format": "mp3"}
    if model := (settings.VOICE_SPEECH_MODEL or "").strip():
        out["model"] = model
    if voice := (settings.VOICE_SPEECH_VOICE or "").strip():
        out["voice"] = voice
    return out


def _reason(response: httpx.Response) -> str:
    """What a failing server said, cut to a line."""
    try:
        data = response.json()
    except ValueError:
        text = response.text
    else:
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            error = error.get("message")
        text = str(error or (data.get("detail") if isinstance(data, dict) else "") or data)
    text = " ".join(text.split())
    return text[:200]


async def speak(text: str) -> tuple[bytes, str]:
    """Ask the speech server to say ``text``; returns its audio and media type."""
    url = endpoint()
    headers = {"Accept": "audio/*"}
    if key := (settings.VOICE_SPEECH_API_KEY or "").strip():
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as client:
            response = await client.post(url, json=body(text), headers=headers)
    except httpx.TimeoutException as exc:
        msg = f"The speech server didn't answer within {TIMEOUT_S:.0f} seconds."
        raise SpeechFailed(msg) from exc
    except httpx.HTTPError as exc:
        msg = f"The hub couldn't reach the speech server: {exc}"
        raise SpeechFailed(msg) from exc
    if response.status_code >= 400:
        reason = _reason(response)
        msg = f"The speech server answered {response.status_code}" + (
            f": {reason}" if reason else "."
        )
        raise SpeechFailed(msg)
    media = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not media.startswith("audio/"):
        msg = "The speech server answered without audio. Is voice.speech_url its speech endpoint?"
        raise SpeechFailed(msg)
    if not response.content:
        msg = "The speech server answered with no audio."
        raise SpeechFailed(msg)
    if len(response.content) > MAX_AUDIO_BYTES:
        msg = "The speech server's answer is too long to play."
        raise SpeechFailed(msg)
    return response.content, media
