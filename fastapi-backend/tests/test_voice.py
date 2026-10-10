# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Voice: a mic's audio in, text for the draft out.

Most of this runs against a stub engine, so the suite needs no model. The last
test runs the real Moonshine v2 and Silero VAD when their files are on disk
(``VOICE_MODEL_DIR``, or the default model folder) and skips otherwise.
"""

import hashlib
import os
import threading
import wave
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from app.config import settings
from app.services import voice, voice_worker

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
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    eng = FakeEngine()
    monkeypatch.setattr(voice, "engine", lambda: eng)
    yield eng
    voice.reset()


@pytest.fixture(autouse=True)
def _in_process(monkeypatch):
    """The routes reach the voice worker; most tests run its work here instead."""
    monkeypatch.setattr(voice_worker, "IN_PROCESS", True)
    yield
    voice_worker.stop()


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
async def test_voice_is_off_unless_turned_on(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VOICE_MODEL_DIR", str(tmp_path))
    body = (await client.get("/api/voice")).json()
    assert body["state"] == "unavailable"
    assert body["detail"] == "voice is off on this hub (voice.enabled)"
    # Off, starting the hub fetches nothing.
    started = []
    monkeypatch.setattr(voice.threading, "Thread", lambda **kw: started.append(kw) or _NoThread())
    voice.prefetch()
    assert started == []


@pytest.mark.asyncio
async def test_status_says_whether_a_mic_can_be_turned_on(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
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


class _NoThread:
    def start(self) -> None:
        pass


def test_turning_voice_on_fetches_the_model_as_the_hub_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(settings, "VOICE_MODEL_DIR", str(tmp_path))
    started = []
    monkeypatch.setattr(voice.threading, "Thread", lambda **kw: started.append(kw) or _NoThread())
    voice.prefetch()
    assert [t["name"] for t in started] == ["voice-fetch"]


@pytest.mark.asyncio
async def test_speech_is_handed_back_as_each_pause_ends_it(client, fake):
    # Speaking: nothing to hand back yet.
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(1.0, loud=True))
    assert r.status_code == 200, r.text
    assert r.json() == {"texts": [], "speaking": True, "ready": True}

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
    assert "voice is off" in r.json()["detail"]


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


# ── The worker, from the hub's side ──────────────────────────────────────────


class _FakeProc:
    def __init__(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, _timeout: float) -> None:
        pass

    def kill(self) -> None:
        self.alive = False


class _FakeConn:
    """A pipe to a worker that runs ``voice.feed`` on the stand-in engine."""

    def __init__(self) -> None:
        self.reply: tuple | None = None
        self.gone = False

    def send(self, msg) -> None:
        if self.gone:
            raise BrokenPipeError
        op, args = msg
        if op == "feed":
            sid, audio, final, caller = args
            heard = voice.feed(sid, audio, final=final, caller=caller)
            self.reply = ("ok", (heard.texts, heard.speaking))
        else:
            self.reply = ("ok", None)

    def recv(self):
        return self.reply

    def close(self) -> None:
        pass


@pytest.fixture
def worker(monkeypatch, fake):
    """The hub side for real, with a worker started by a stand-in ``_start``."""
    monkeypatch.setattr(voice_worker, "IN_PROCESS", False)
    monkeypatch.setattr(voice, "state", lambda: ("ready", ""))
    gate = threading.Event()
    starts = []

    def start() -> None:
        starts.append(1)
        gate.wait(5)
        with voice_worker._state_lock:
            # Stand-ins for a process and its pipe, shaped like the real ones.
            voice_worker._worker = voice_worker._Worker(
                cast("Any", _FakeProc()), cast("Any", _FakeConn())
            )

    monkeypatch.setattr(voice_worker, "_start", start)
    yield gate, starts
    gate.set()
    _wait_for_start()


def _wait_for_start() -> None:
    if voice_worker._starter is not None:
        voice_worker._starter.join(5)


@pytest.mark.asyncio
async def test_the_first_mic_starts_the_worker_once_and_waits_for_nobody(client, worker):
    gate, starts = worker
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=True))
    assert r.json() == {"texts": [], "speaking": False, "ready": False}
    # A second chunk doesn't start a second worker or wait on the first.
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=True))
    assert r.json()["ready"] is False
    assert starts == [1]

    gate.set()
    _wait_for_start()
    r = await client.post(
        f"/api/voice/sessions/{SID}", content=pcm(0.5, loud=True) + pcm(0.2, loud=False)
    )
    assert r.json()["ready"] is True
    assert r.json()["texts"] == ["0.5 seconds of speech"]


@pytest.mark.asyncio
async def test_a_worker_that_exited_is_started_again(client, worker):
    gate, starts = worker
    gate.set()
    await client.post(f"/api/voice/sessions/{SID}", content=b"")
    _wait_for_start()
    # It went idle and exited between two chunks.
    running = voice_worker._worker
    assert running is not None
    cast("_FakeConn", running.conn).gone = True
    r = await client.post(f"/api/voice/sessions/{SID}", content=pcm(0.2, loud=True))
    assert r.json()["ready"] is False
    _wait_for_start()
    assert starts == [1, 1]
    assert (await client.post(f"/api/voice/sessions/{SID}", content=b"")).json()["ready"] is True


@pytest.mark.asyncio
async def test_a_failed_start_is_reported_and_not_retried_at_once(client, monkeypatch, fake):
    monkeypatch.setattr(voice_worker, "IN_PROCESS", False)
    monkeypatch.setattr(voice, "state", lambda: ("not_downloaded", ""))
    fetches = []

    def cut_off():
        fetches.append(1)
        raise voice.VoiceUnavailable("the download was cut off")

    monkeypatch.setattr(voice, "ensure_models", cut_off)
    await client.post(f"/api/voice/sessions/{SID}", content=b"")
    _wait_for_start()
    r = await client.post(f"/api/voice/sessions/{SID}", content=b"")
    assert r.status_code == 503
    assert "cut off" in r.json()["detail"]
    assert fetches == [1]

    # Once the wait is over, the next mic tries again.
    monkeypatch.setattr(voice_worker, "_retry_at", 0.0)
    assert (await client.post(f"/api/voice/sessions/{SID}", content=b"")).json()["ready"] is False
    _wait_for_start()
    assert fetches == [1, 1]


@pytest.mark.asyncio
async def test_with_voice_off_no_worker_is_started(client, monkeypatch):
    monkeypatch.setattr(voice_worker, "IN_PROCESS", False)
    r = await client.post(f"/api/voice/sessions/{SID}", content=b"")
    assert r.status_code == 503
    assert voice_worker._starter is None or not voice_worker._starter.is_alive()
    assert voice_worker._worker is None


class _Stream:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self, _size: int):
        yield self.body


def test_a_download_whose_hash_differs_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(voice.httpx, "stream", lambda *a, **k: _Stream(b"something else"))
    dest = tmp_path / "silero_vad_v5.onnx"
    with pytest.raises(voice.VoiceUnavailable, match="isn't the file"):
        voice._fetch("https://example.com/x", dest, voice.SILERO_SHA256)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_download_whose_hash_matches_is_kept(monkeypatch, tmp_path):
    body = b"the model"
    monkeypatch.setattr(voice.httpx, "stream", lambda *a, **k: _Stream(body))
    dest = tmp_path / "model.onnx"
    voice._fetch("https://example.com/x", dest, hashlib.sha256(body).hexdigest())
    assert dest.read_bytes() == body


def test_a_mic_belongs_to_whoever_opened_it(fake):
    voice.feed(SID, pcm(0.5, loud=True), caller="ada")
    # Another caller with the same id gets a session of its own.
    assert voice.feed(SID, pcm(0.2, loud=False), caller="bex").texts == []
    assert voice.feed(SID, pcm(0.2, loud=False), caller="ada").texts == ["0.5 seconds of speech"]
    voice.end(SID, caller="bex")
    assert voice.open_sessions() == 1


def test_one_caller_cannot_hold_every_mic(fake):
    for i in range(voice.MAX_SESSIONS_PER_CALLER):
        voice.feed(f"{i:016x}", b"", caller="ada")
    with pytest.raises(voice.VoiceUnavailable, match="already have"):
        voice.feed("f" * 16, b"", caller="ada")
    # Someone else, and a hub with sign-in off, still get one.
    voice.feed("f" * 16, b"", caller="bex")
    voice.feed("e" * 16, b"", caller=None)


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
def test_a_real_worker_transcribes_speech_and_exits_when_idle(monkeypatch):
    root = _real_models()
    assert root is not None
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    # The worker is its own process and reads its settings from the environment.
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOICE_MODEL_DIR", str(root))
    monkeypatch.setattr(settings, "VOICE_MODEL_DIR", str(root))
    monkeypatch.setattr(voice_worker, "IN_PROCESS", False)
    monkeypatch.setattr(voice_worker, "IDLE_EXIT_S", 1.0)
    monkeypatch.setattr(voice_worker, "_POLL_S", 0.2)
    # The first chunk starts the worker and says so; wait for it as the app does.
    with pytest.raises(voice.VoiceWarming):
        voice_worker.feed(SID, b"")
    _wait_for_start()
    worker = voice_worker._worker
    assert worker is not None
    assert worker.proc.is_alive()
    with wave.open(str(root / voice.MOONSHINE / "test_wavs" / "0.wav")) as w:
        rate = w.getframerate()
        recorded = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    # The app sends 16 kHz; the bundled clip is recorded at another rate.
    at = np.linspace(0, len(recorded) - 1, int(len(recorded) * RATE / rate))
    audio = np.interp(at, np.arange(len(recorded)), recorded).astype("<i2").tobytes()
    chunk = RATE // 2 * 2  # half a second of 16-bit samples
    texts: list[str] = []
    for i in range(0, len(audio), chunk):
        texts += voice_worker.feed(SID, audio[i : i + chunk]).texts
    texts += voice_worker.feed(SID, b"", final=True).texts
    assert " ".join(texts).strip()

    # No mic open: it exits, and all its memory goes with it.
    worker.proc.join(10)
    assert not worker.proc.is_alive()
