# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading notifications aloud: the hub relays text to its own speech server.

The speech server is a mock transport, so nothing leaves the test.
"""

import json

import httpx
import pytest

from app.config import settings
from app.services import speech

MP3 = b"ID3\x04fake-mp3-bytes"


@pytest.fixture
def server(monkeypatch):
    """A speech server that records what it's asked and answers with ``reply``."""
    seen: list[httpx.Request] = []
    state = {"reply": httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["reply"]

    monkeypatch.setattr(speech, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "http://tts.local:8880/v1")
    monkeypatch.setattr(settings, "VOICE_SPEECH_MODEL", "")
    monkeypatch.setattr(settings, "VOICE_SPEECH_VOICE", "")
    monkeypatch.setattr(settings, "VOICE_SPEECH_API_KEY", "")
    return seen, state


@pytest.mark.asyncio
async def test_without_a_speech_server_nothing_is_offered(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "")
    assert (await client.get("/api/voice")).json()["speech"] is False
    assert (await client.get("/api/hub/settings")).json()["voice"]["speech"] is False
    response = await client.post("/api/voice/speech", json={"text": "hello"})
    assert response.status_code == 404
    assert "voice.speech_url" in response.json()["detail"]


@pytest.mark.asyncio
async def test_the_hub_relays_text_and_hands_back_the_audio(client, server):
    seen, _ = server
    assert (await client.get("/api/voice")).json()["speech"] is True
    response = await client.post("/api/voice/speech", json={"text": "julia says hello."})
    assert response.status_code == 200
    assert response.content == MP3
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    (request,) = seen
    # /audio/speech is added to a base address, and only the text is sent:
    # no model or voice the operator didn't set, and no key.
    assert str(request.url) == "http://tts.local:8880/v1/audio/speech"
    assert json.loads(request.content) == {"input": "julia says hello.", "response_format": "mp3"}
    assert "authorization" not in request.headers


@pytest.mark.asyncio
async def test_model_voice_and_key_are_sent_when_set(client, server, monkeypatch):
    seen, _ = server
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "https://tts.example.com/v1/audio/speech/")
    monkeypatch.setattr(settings, "VOICE_SPEECH_MODEL", "qwen-tts")
    monkeypatch.setattr(settings, "VOICE_SPEECH_VOICE", "Cherry")
    monkeypatch.setattr(settings, "VOICE_SPEECH_API_KEY", "sk-test")
    assert (await client.post("/api/voice/speech", json={"text": "hi"})).status_code == 200
    (request,) = seen
    # A full endpoint is used as it is.
    assert str(request.url) == "https://tts.example.com/v1/audio/speech"
    assert json.loads(request.content) == {
        "input": "hi",
        "response_format": "mp3",
        "model": "qwen-tts",
        "voice": "Cherry",
    }
    assert request.headers["authorization"] == "Bearer sk-test"
    # The key is only ever "set" on the Hub page.
    hub = (await client.get("/api/hub/settings")).json()["voice"]
    assert hub == {"enabled": False, "model": "fast", "speech": True, "speech_has_key": True}


@pytest.mark.asyncio
async def test_the_request_takes_no_address(client, server):
    seen, _ = server
    # An address in the body is ignored: the hub only ever calls its own setting.
    response = await client.post(
        "/api/voice/speech", json={"text": "hi", "url": "http://169.254.169.254/"}
    )
    assert response.status_code == 200
    assert str(seen[0].url) == "http://tts.local:8880/v1/audio/speech"


@pytest.mark.asyncio
async def test_empty_or_long_text_is_refused(client, server):
    seen, _ = server
    assert (await client.post("/api/voice/speech", json={"text": ""})).status_code == 422
    assert (await client.post("/api/voice/speech", json={"text": "a" * 1001})).status_code == 422
    assert seen == []


@pytest.mark.asyncio
async def test_a_failing_server_says_why(client, server):
    _, state = server
    state["reply"] = httpx.Response(400, json={"error": {"message": "voice 'x' not found"}})
    response = await client.post("/api/voice/speech", json={"text": "hi"})
    assert response.status_code == 502
    assert response.json()["detail"] == "The speech server answered 400: voice 'x' not found"


@pytest.mark.asyncio
async def test_an_answer_that_isnt_audio_is_refused(client, server):
    _, state = server
    state["reply"] = httpx.Response(
        200, text="<html>not here</html>", headers={"content-type": "text/html"}
    )
    response = await client.post("/api/voice/speech", json={"text": "hi"})
    assert response.status_code == 502
    assert "without audio" in response.json()["detail"]


@pytest.mark.asyncio
async def test_an_unreachable_server_says_so(client, server, monkeypatch):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(speech, "_transport", httpx.MockTransport(refuse))
    response = await client.post("/api/voice/speech", json={"text": "hi"})
    assert response.status_code == 502
    assert response.json()["detail"].startswith("The hub couldn't reach the speech server")


@pytest.mark.asyncio
async def test_a_redirect_is_not_followed(client, server):
    seen, state = server
    state["reply"] = httpx.Response(302, headers={"location": "http://elsewhere.local/"})
    response = await client.post("/api/voice/speech", json={"text": "hi"})
    assert response.status_code == 502
    assert len(seen) == 1


def test_an_address_that_isnt_http_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "file:///etc/passwd")
    with pytest.raises(speech.SpeechUnavailable):
        speech.endpoint()
