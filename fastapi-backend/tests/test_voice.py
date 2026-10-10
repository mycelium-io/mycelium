# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Voice: a mic's audio in, text for the draft out.

Most of this runs against a stub engine, so the suite needs no model. The last
test runs the real Moonshine v2 and Silero VAD when their files are on disk
(``VOICE_MODEL_DIR``, or the default model folder) and skips otherwise.
"""

import os
import wave
from pathlib import Path

import numpy as np
import pytest

from app.config import settings
from app.services import voice

RATE = voice.SAMPLE_RATE


class _Segment:
    def __init__(self, samples: np.ndarray) -> None:
        self.samples = samples


class FakeDetector:
    """Speech is any window louder than silence; a quiet window ends a piece."""

    def __init__(self) -> None:
        self.current: list[np.ndarray] = []
        self.done: list[np.ndarray] = []

    def accept_waveform(self, window: np.ndarray) -> None:
        if float(np.max(np.abs(window))) > 0.01:
            self.current.append(window)
        elif self.current:
            self.done.append(np.concatenate(self.current))
            self.current = []

    def flush(self) -> None:
        if self.current:
            self.done.append(np.concatenate(self.current))
            self.current = []

    def empty(self) -> bool:
        return not self.done

    @property
    def front(self) -> _Segment:
        return _Segment(self.done[0])

    def pop(self) -> None:
        self.done.pop(0)

    def is_speech_detected(self) -> bool:
        return bool(self.current)


class FakeEngine:
    window = 512

    def __init__(self) -> None:
        self.heard: list[int] = []

    def new_detector(self) -> FakeDetector:
        return FakeDetector()

    def transcribe(self, samples: np.ndarray) -> str:
        self.heard.append(len(samples))
        return f"{len(samples) / RATE:.1f} seconds of speech"


@pytest.fixture
def fake(monkeypatch):
    voice.reset()
    eng = FakeEngine()
    monkeypatch.setattr(voice, "engine", lambda: eng)
    yield eng
    voice.reset()


def pcm(seconds: float, *, loud: bool) -> bytes:
    n = int(seconds * RATE)
    tone = (
        (np.sin(np.arange(n) * 2 * np.pi * 220 / RATE) * 8000).astype("<i2")
        if loud
        else np.zeros(n, "<i2")
    )
    return tone.tobytes()


SID = "0123456789abcdef"


@pytest.mark.asyncio
async def test_status_says_whether_a_mic_can_be_turned_on(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VOICE_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "VOICE_DOWNLOAD", True)
    body = (await client.get("/api/voice")).json()
    assert body["state"] == "not_downloaded"
    assert body["sample_rate"] == 16000
    assert body["language"] == "en"

    monkeypatch.setattr(settings, "VOICE_DOWNLOAD", False)
    body = (await client.get("/api/voice")).json()
    assert body["state"] == "unavailable"
    assert str(tmp_path) in body["detail"]

    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    assert (await client.get("/api/voice")).json()["detail"] == "voice is turned off on this hub"


@pytest.mark.asyncio
async def test_speech_is_handed_back_as_each_pause_ends_it(client, fake):
    # Speaking: nothing to hand back yet.
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(1.0, loud=True))
    assert r.status_code == 200, r.text
    assert r.json() == {"texts": [], "speaking": True}

    # A pause ends the piece.
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=False))
    assert r.json()["texts"] == ["1.0 seconds of speech"]
    assert r.json()["speaking"] is False

    # Still listening: the mic stays open across pauses.
    r = await client.post(
        f"/api/voice/sessions/{SID}", content=pcm(0.6, loud=True) + pcm(0.3, loud=False)
    )
    assert len(r.json()["texts"]) == 1
    assert voice.open_sessions() == 1


@pytest.mark.asyncio
async def test_turning_the_mic_off_hands_back_what_was_being_said(client, fake):
    await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.8, loud=True))
    r = await client.post(f"/api/voice/sessions/{SID}", params={"final": "true"}, content=b"")
    assert len(r.json()["texts"]) == 1
    assert r.json()["speaking"] is False
    assert voice.open_sessions() == 0


@pytest.mark.asyncio
async def test_a_chunk_that_splits_a_window_carries_the_rest_to_the_next(client, fake):
    # 700 samples: one window of 512 is heard now, the other 188 wait.
    await client.post(f"/api/voice/sessions/{SID}", content=(np.full(700, 8000, "<i2")).tobytes())
    await client.post(
        f"/api/voice/sessions/{SID}",
        content=(np.full(324, 8000, "<i2")).tobytes() + pcm(0.1, loud=False),
    )
    assert fake.heard == [1024]


@pytest.mark.asyncio
async def test_closing_a_mic_drops_what_it_was_hearing(client, fake):
    await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=True))
    assert (await client.delete(f"/api/voice/sessions/{SID}")).status_code == 204
    assert voice.open_sessions() == 0
    assert fake.heard == []


@pytest.mark.asyncio
async def test_mics_are_kept_apart(client, fake):
    other = "fedcba9876543210"
    await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=True))
    r = await client.post(f"/api/voice/sessions/{other}", content=pcm(0.3, loud=False))
    assert r.json()["texts"] == []
    assert voice.open_sessions() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sid", "body", "status"),
    [
        ("not-hex!", b"\x00\x00", 422),
        ("abc", b"\x00\x00", 422),
        (SID, b"\x00\x00\x00", 422),
    ],
)
async def test_bad_chunks_are_refused(client, fake, sid, body, status):
    assert (await client.post(f"/api/voice/sessions/{sid}", content=body)).status_code == status


@pytest.mark.asyncio
async def test_a_chunk_over_a_minute_is_refused(client, fake):
    r = await client.post(f"/api/voice/sessions/{SID}", content=b"\x00\x00" * (61 * RATE))
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_a_hub_that_cannot_transcribe_says_why(client, monkeypatch):
    voice.reset()
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.1, loud=True))
    assert r.status_code == 503
    assert "turned off" in r.json()["detail"]


@pytest.mark.asyncio
async def test_too_many_open_mics_are_refused(client, fake, monkeypatch):
    monkeypatch.setattr(voice, "MAX_SESSIONS", 1)
    await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.1, loud=False))
    r = await client.post("/api/voice/sessions/fedcba9876543210", content=pcm(0.1, loud=False))
    assert r.status_code == 503
    assert "too many" in r.json()["detail"]


def test_an_idle_mic_is_closed(fake, monkeypatch):
    voice.feed(SID, pcm(0.1, loud=False))
    clock = [voice.time.monotonic() + voice.SESSION_IDLE_S + 1]
    monkeypatch.setattr(voice.time, "monotonic", lambda: clock[0])
    assert voice.open_sessions() == 0


def test_long_speech_is_cut_at_its_quietest_point_under_the_limit():
    speech = np.ones(int(13 * RATE), dtype=np.float32)
    breath = int(4.2 * RATE)
    speech[breath : breath + RATE // 10] = 0.0
    pieces = voice.split_long(speech)
    assert all(len(p) <= voice.MAX_PIECE_S * RATE for p in pieces)
    assert sum(len(p) for p in pieces) == len(speech)
    assert abs(len(pieces[0]) - breath) <= RATE // 20


def test_short_speech_is_left_whole():
    speech = np.ones(RATE * 3, dtype=np.float32)
    assert [len(p) for p in voice.split_long(speech)] == [len(speech)]


def _real_models() -> Path | None:
    root = Path(os.environ.get("VOICE_MODEL_DIR") or voice.model_dir())
    return root if voice._present(root) else None


@pytest.mark.skipif(_real_models() is None, reason="the speech model isn't on disk")
def test_the_real_model_transcribes_speech_fed_in_chunks(monkeypatch):
    root = _real_models()
    assert root is not None
    monkeypatch.setattr(settings, "VOICE_MODEL_DIR", str(root))
    voice.reset()
    with wave.open(str(root / voice.MOONSHINE / "test_wavs" / "0.wav")) as w:
        rate = w.getframerate()
        recorded = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    # The app sends 16 kHz; the bundled clip is recorded at another rate.
    at = np.linspace(0, len(recorded) - 1, int(len(recorded) * RATE / rate))
    audio = np.interp(at, np.arange(len(recorded)), recorded).astype("<i2").tobytes()
    chunk = RATE // 2 * 2  # half a second of 16-bit samples
    texts: list[str] = []
    for i in range(0, len(audio), chunk):
        texts += voice.feed(SID, audio[i : i + chunk]).texts
    texts += voice.feed(SID, b"", final=True).texts
    voice.reset()
    assert " ".join(texts).strip()
