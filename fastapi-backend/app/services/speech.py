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

import re
import time
from collections import deque
from typing import Any

import httpx

from app.config import settings
from app.schemas import VOICE_NAME_PATTERN

#: The longest text one request may ask for. The app sends a sentence at a
#: time, so this is well past what it needs.
MAX_TEXT = 1000

#: How long the speech server has to answer.
TIMEOUT_S = 30.0

#: The most audio one answer may carry: minutes of speech, far past a sentence.
MAX_AUDIO_BYTES = 10 * 1024 * 1024

#: The path an OpenAI-style server takes speech requests at.
SPEECH_PATH = "/audio/speech"

#: The most voices listed for a person to pick from.
MAX_VOICES = 300
_VOICE_NAME = re.compile(VOICE_NAME_PATTERN)

#: How the hub reaches the server; tests replace it with a mock transport.
_transport: httpx.AsyncBaseTransport | None = None

#: Requests the whole hub may send the speech server in `RATE_WINDOW_S`. Each
#: one can spend the operator's key, and with sign-in off anyone who reaches
#: the hub can call the route, so a loop is refused rather than billed. Reading
#: aloud asks for about one sentence every two seconds, far under it.
RATE_LIMIT = 10
RATE_WINDOW_S = 2.0
_recent: deque[float] = deque()


class SpeechUnavailable(RuntimeError):
    """No speech server is set on this hub, or its address isn't one."""


class SpeechFailed(RuntimeError):
    """The speech server didn't give back audio, with the reason the app shows."""


class SpeechBusy(RuntimeError):
    """Too many requests in a moment: the caller waits and asks again."""


def _admit(now: float | None = None) -> None:
    """Count a request against the hub's limit, or refuse it."""
    now = time.monotonic() if now is None else now
    while _recent and now - _recent[0] >= RATE_WINDOW_S:
        _recent.popleft()
    if len(_recent) >= RATE_LIMIT:
        msg = "Too many speech requests at once. Try again in a moment."
        raise SpeechBusy(msg)
    _recent.append(now)


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


def body(text: str, voice: str | None = None, speed: float | None = None) -> dict[str, str | float]:
    """The OpenAI-style request: the text, mp3 back, and the model and voice
    only when set, so a server's own defaults apply otherwise. A person's own
    voice and speed, when they chose one, go in place of the hub's."""
    out: dict[str, str | float] = {"input": text, "response_format": "mp3"}
    if model := (settings.VOICE_SPEECH_MODEL or "").strip():
        out["model"] = model
    if chosen := (voice or settings.VOICE_SPEECH_VOICE or "").strip():
        out["voice"] = chosen
    if speed is not None:
        out["speed"] = speed
    return out


def _headers(accept: str) -> dict[str, str]:
    headers = {"Accept": accept}
    if key := (settings.VOICE_SPEECH_API_KEY or "").strip():
        headers["Authorization"] = f"Bearer {key}"
    return headers


def voices_endpoint() -> str:
    """Where the server lists its voices, beside its speech endpoint: the
    ``/audio/voices`` that Kokoro, vLLM and most OpenAI-style servers add."""
    return endpoint().removesuffix("/speech") + "/voices"


def _names(data: Any) -> list[str]:
    """Voice names from the shapes servers answer with: a list, or one under
    ``voices`` or ``data``, of names or of objects naming one. Only names a
    request may ask for are kept, so the picker never offers one the hub then
    refuses, and at most `MAX_VOICES` of them, from a server that sends more."""
    if isinstance(data, dict):
        data = data.get("voices", data.get("data", []))
    if not isinstance(data, list):
        return []
    names: set[str] = set()
    for entry in data:
        name = entry
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("id") or entry.get("voice_id")
        if isinstance(name, str) and _VOICE_NAME.match(name.strip()):
            names.add(name.strip())
    return sorted(names)[:MAX_VOICES]


async def voices() -> list[str]:
    """The voices the speech server offers, or none when it doesn't list them
    (OpenAI's own API has no such endpoint); a person can still type one."""
    url = voices_endpoint()
    _admit()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as client:
            response = await client.get(url, headers=_headers("application/json"))
    except httpx.HTTPError:
        return []
    if response.status_code >= 400:
        return []
    try:
        return _names(response.json())
    except ValueError:
        return []


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


async def speak(
    text: str, voice: str | None = None, speed: float | None = None
) -> tuple[bytes, str]:
    """Ask the speech server to say ``text``; returns its audio and media type."""
    url = endpoint()
    _admit()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as client:
            response = await client.post(
                url, json=body(text, voice, speed), headers=_headers("audio/*")
            )
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
