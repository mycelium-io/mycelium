# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading notifications aloud: the hub relays text to its own speech server.

The speech server is a mock transport, so nothing leaves the test.
"""

import json
from collections import deque

import httpx
import pytest

from app.config import settings
from app.services import speech

MP3 = b"ID3\x04fake-mp3-bytes"


@pytest.fixture(autouse=True)
def _fresh_limit(monkeypatch):
    """Each test starts with the hub's speech limit unspent."""
    monkeypatch.setattr(speech, "_recent", deque())


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


@pytest.mark.asyncio
async def test_a_loop_is_refused_before_it_reaches_the_server(client, server):
    seen, _ = server
    codes = [
        (await client.post("/api/voice/speech", json={"text": f"line {i}"})).status_code
        for i in range(speech.RATE_LIMIT + 3)
    ]
    assert codes == [200] * speech.RATE_LIMIT + [429] * 3
    assert len(seen) == speech.RATE_LIMIT
    refused = await client.post("/api/voice/speech", json={"text": "again"})
    assert refused.headers["retry-after"] == "2"


def test_the_limit_frees_up_as_the_window_passes():
    for i in range(speech.RATE_LIMIT):
        speech._admit(now=100.0 + i * 0.01)
    with pytest.raises(speech.SpeechBusy):
        speech._admit(now=100.5)
    speech._admit(now=100.0 + speech.RATE_WINDOW_S)


def test_an_address_that_isnt_http_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "file:///etc/passwd")
    with pytest.raises(speech.SpeechUnavailable):
        speech.endpoint()


@pytest.mark.asyncio
async def test_a_persons_voice_and_speed_go_in_place_of_the_hubs(client, server, monkeypatch):
    seen, _ = server
    monkeypatch.setattr(settings, "VOICE_SPEECH_VOICE", "af_heart")
    response = await client.post(
        "/api/voice/speech", json={"text": "hi", "voice": "bm_george", "speed": 1.25}
    )
    assert response.status_code == 200
    assert json.loads(seen[0].content) == {
        "input": "hi",
        "response_format": "mp3",
        "voice": "bm_george",
        "speed": 1.25,
    }
    # Without a choice, the hub's voice and the server's own speed.
    await client.post("/api/voice/speech", json={"text": "hi"})
    assert json.loads(seen[1].content) == {
        "input": "hi",
        "response_format": "mp3",
        "voice": "af_heart",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [{"voice": "../../etc"}, {"voice": "x" * 65}, {"voice": ""}, {"speed": 0.1}, {"speed": 5}],
)
async def test_a_voice_or_speed_out_of_range_is_refused(client, server, extra):
    seen, _ = server
    response = await client.post("/api/voice/speech", json={"text": "hi", **extra})
    assert response.status_code == 422
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        {"voices": ["bm_george", "af_heart"]},
        ["af_heart", "bm_george"],
        {"data": [{"name": "af_heart"}, {"id": "bm_george"}]},
        {"voices": [{"voice_id": "bm_george"}, {"name": "af_heart"}, {"name": ""}]},
    ],
)
async def test_the_servers_voices_are_listed_from_any_common_shape(
    client, server, monkeypatch, answer
):
    seen, state = server
    monkeypatch.setattr(settings, "VOICE_SPEECH_VOICE", "af_heart")
    state["reply"] = httpx.Response(200, json=answer)
    response = await client.get("/api/voice/voices")
    assert response.json() == {"voices": ["af_heart", "bm_george"], "default": "af_heart"}
    assert str(seen[0].url) == "http://tts.local:8880/v1/audio/voices"


@pytest.mark.asyncio
async def test_a_server_that_lists_no_voices_answers_none(client, server):
    _, state = server
    state["reply"] = httpx.Response(404, json={"detail": "Not Found"})
    assert (await client.get("/api/voice/voices")).json() == {"voices": [], "default": ""}


@pytest.mark.asyncio
async def test_no_voices_without_a_speech_server(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_SPEECH_URL", "")
    assert (await client.get("/api/voice/voices")).status_code == 404


@pytest.mark.asyncio
async def test_only_names_a_request_may_ask_for_are_listed_and_not_too_many(client, server):
    _, state = server
    junk = ["x" * 65, "../etc", "<script>", " ", "good one"]
    many = [f"voice_{i:04d}" for i in range(speech.MAX_VOICES + 50)]
    state["reply"] = httpx.Response(200, json={"voices": junk + many})
    listed = (await client.get("/api/voice/voices")).json()["voices"]
    assert len(listed) == speech.MAX_VOICES
    assert "good one" in listed
    assert not {"x" * 65, "../etc", "<script>"} & set(listed)
