# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Voice: what someone says into their microphone, transcribed on the hub.

The app streams 16 kHz mono audio here in small chunks while a person has the
mic toggled on (``routes/voice.py``). Each open mic is a session holding a
Silero voice activity detector, which hears where speech starts and stops; each
stretch of speech it closes is transcribed by Moonshine v2 and handed back as
text for the composer's draft. Pauses only split speech into pieces; nothing
here decides when to stop listening or to send.

Both models run on the CPU through sherpa-onnx, like the search model runs
through fastembed. They are files on disk at :func:`model_dir`: baked into the
backend image, staged into the Mac app, or fetched once on first use from
sherpa-onnx's release page. Audio is never stored: a session holds only the
samples of the piece it is hearing, and forgets a mic left idle.

One limit shapes the cutting: sherpa-onnx 1.13.8 returns empty text for a
Moonshine v2 piece much past six seconds (k2-fsa/sherpa-onnx#3975, fixed after
that release). The detector caps a piece's length, and :func:`split_long` cuts
anything longer at its quietest point, so no piece reaches the model whole.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import shutil
import tarfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
LANGUAGE = "en"

MOONSHINE = "sherpa-onnx-moonshine-base-en-quantized-2026-02-27"
SILERO = "silero_vad_v5.onnx"
_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
# What those release assets were when this was written: the Moonshine archive
# and the Silero file. A download that doesn't match is refused.
MOONSHINE_SHA256 = "43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891"
SILERO_SHA256 = "6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396"

# The longest piece handed to the model, in seconds; see the module docstring.
MAX_PIECE_S = 5.5
# A pause this long ends a piece of speech. Short enough that text arrives
# while someone is still talking in sentences, long enough not to split words.
MIN_SILENCE_S = 0.4

# A mic left this long without a chunk is closed; the app sends one every
# fraction of a second while it is on.
SESSION_IDLE_S = 60.0
MAX_SESSIONS = 16

State = Literal["ready", "not_downloaded", "unavailable"]


class VoiceUnavailable(RuntimeError):
    """The hub can't transcribe right now, with the reason to show the person."""


def model_dir() -> Path:
    """Where the models live: ``VOICE_MODEL_DIR``, else ``<data dir>/models/voice``."""
    if settings.VOICE_MODEL_DIR:
        return Path(settings.VOICE_MODEL_DIR)
    return Path(settings.MYCELIUM_DATA_DIR) / "models" / "voice"


def _files(root: Path) -> dict[str, Path]:
    m = root / MOONSHINE
    return {
        "encoder": m / "encoder_model.ort",
        "decoder": m / "decoder_model_merged.ort",
        "tokens": m / "tokens.txt",
        "vad": root / SILERO,
    }


def _present(root: Path) -> bool:
    return all(p.is_file() for p in _files(root).values())


def _runtime() -> Any:
    try:
        import sherpa_onnx
    except ImportError as exc:  # pragma: no cover - the package is a dependency
        msg = "this hub has no speech runtime (sherpa-onnx)"
        raise VoiceUnavailable(msg) from exc
    return sherpa_onnx


def state() -> tuple[State, str]:
    """Whether voice works on this hub, and why not when it doesn't."""
    if not settings.VOICE_ENABLED:
        return "unavailable", "voice is turned off on this hub"
    try:
        _runtime()
    except VoiceUnavailable as exc:
        return "unavailable", str(exc)
    if _present(model_dir()):
        return "ready", ""
    if settings.VOICE_DOWNLOAD:
        return (
            "not_downloaded",
            "the speech model downloads the first time someone turns the mic on",
        )
    return "unavailable", f"the speech model isn't at {model_dir()}"


# ── Getting the models ───────────────────────────────────────────────────────

_download_lock = threading.Lock()


def _fetch(url: str, dest: Path, sha256: str) -> None:
    """Download ``url`` to ``dest``, refusing it unless its SHA-256 is ``sha256``.

    The image build, the Mac app's staging and a hub fetching on first use all
    come through here, so a release asset that changed under the same name is
    caught once, before it is baked in anywhere.
    """
    tmp = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.part")
    digest = hashlib.sha256()
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as out:
                for chunk in resp.iter_bytes(1 << 20):
                    digest.update(chunk)
                    out.write(chunk)
        if digest.hexdigest() != sha256:
            msg = f"{dest.name} from {url} isn't the file this hub expects (SHA-256 {digest.hexdigest()})"
            raise VoiceUnavailable(msg)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_models() -> Path:
    """The model folder, fetching what's missing once if the hub may."""
    root = model_dir()
    if _present(root):
        return root
    if not settings.VOICE_DOWNLOAD:
        msg = f"the speech model isn't at {root}"
        raise VoiceUnavailable(msg)
    with _download_lock:
        if _present(root):
            return root
        root.mkdir(parents=True, exist_ok=True)
        logger.info("voice: fetching the speech model into %s", root)
        try:
            if not (root / SILERO).is_file():
                _fetch(f"{_RELEASE}/{SILERO}", root / SILERO, SILERO_SHA256)
            if not (root / MOONSHINE).is_dir() or not _present(root):
                archive = root / f"{MOONSHINE}.tar.bz2"
                _fetch(f"{_RELEASE}/{MOONSHINE}.tar.bz2", archive, MOONSHINE_SHA256)
                shutil.rmtree(root / MOONSHINE, ignore_errors=True)
                with tarfile.open(archive, "r:bz2") as tar:
                    tar.extractall(root, filter="data")
                archive.unlink(missing_ok=True)
        except (httpx.HTTPError, OSError, tarfile.TarError) as exc:
            msg = f"couldn't fetch the speech model: {exc}"
            raise VoiceUnavailable(msg) from exc
    if not _present(root):
        msg = f"the speech model at {root} is incomplete"
        raise VoiceUnavailable(msg)
    return root


# ── Transcribing ─────────────────────────────────────────────────────────────


def split_long(samples: np.ndarray, max_s: float = MAX_PIECE_S) -> list[np.ndarray]:
    """``samples`` cut into pieces no longer than ``max_s``, each at its quietest spot.

    A cut is looked for in the last two seconds before the limit, in 50 ms
    steps, so it lands in a breath between words rather than through one.
    """
    limit = int(max_s * SAMPLE_RATE)
    step = SAMPLE_RATE // 20
    pieces: list[np.ndarray] = []
    rest = samples
    while len(rest) > limit:
        lo = max(step, limit - 2 * SAMPLE_RATE)
        starts = range(lo, limit - step + 1, step)
        quietest = min(starts, key=lambda s: float(np.mean(rest[s : s + step] ** 2)))
        pieces.append(rest[:quietest])
        rest = rest[quietest:]
    if len(rest):
        pieces.append(rest)
    return pieces


class Engine(Protocol):
    """What a session needs from the models; a stub stands in for it in tests."""

    #: How many samples the detector takes at a time.
    window: int

    def new_detector(self) -> Any: ...

    def transcribe(self, samples: np.ndarray) -> str: ...


class SherpaEngine:
    """Moonshine v2 and Silero VAD through sherpa-onnx, loaded once per hub."""

    def __init__(self, root: Path) -> None:
        so = _runtime()
        files = _files(root)
        self._so = so
        self._recognizer = so.OfflineRecognizer.from_moonshine_v2(
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            tokens=str(files["tokens"]),
            num_threads=settings.VOICE_THREADS,
        )
        self._vad = so.VadModelConfig()
        self._vad.silero_vad.model = str(files["vad"])
        self._vad.silero_vad.min_silence_duration = MIN_SILENCE_S
        self._vad.silero_vad.max_speech_duration = MAX_PIECE_S
        self._vad.sample_rate = SAMPLE_RATE
        self.window = int(self._vad.silero_vad.window_size)
        # One decode at a time: they take a few hundredths of a second, and
        # the recognizer is shared by every open mic.
        self._lock = threading.Lock()

    def new_detector(self) -> Any:
        return self._so.VoiceActivityDetector(self._vad, buffer_size_in_seconds=30)

    def transcribe(self, samples: np.ndarray) -> str:
        texts = []
        for piece in split_long(samples):
            with self._lock:
                stream = self._recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, piece)
                self._recognizer.decode_stream(stream)
                text = stream.result.text.strip()
            if text:
                texts.append(text)
        return " ".join(texts)


class VoiceWarming(RuntimeError):
    """The engine is still loading (or its models downloading); send the chunk again."""


# A load that failed (a download cut off, a full disk) isn't tried again for
# this long, so a mic held on doesn't restart a 150 MB download every chunk.
LOAD_RETRY_S = 60.0

_engine: Engine | None = None
_engine_lock = threading.Lock()
_loader: threading.Thread | None = None
_load_error = ""
_retry_at = 0.0


def _load() -> None:
    global _engine, _load_error, _retry_at
    try:
        loaded = SherpaEngine(ensure_models())
    except Exception as exc:  # anything that stops it is reported, not raised on a thread
        logger.warning("voice: couldn't load the speech model: %s", exc)
        with _engine_lock:
            _load_error = (
                str(exc)
                if isinstance(exc, VoiceUnavailable)
                else f"the speech model didn't load: {exc}"
            )
            _retry_at = time.monotonic() + LOAD_RETRY_S
        return
    with _engine_lock:
        _engine = loaded
        _load_error = ""
    logger.info("voice: speech model loaded (%s)", MOONSHINE)


def engine() -> Engine:
    """The hub's one engine, or :class:`VoiceWarming` while it loads.

    The first call starts loading it on a thread of its own, fetching the
    models if they're missing. Nothing here waits on that, so a request never
    holds one of the hub's worker threads through a download.
    """
    global _loader, _load_error
    if _engine is not None:
        return _engine
    current, why = state()
    if current == "unavailable":
        raise VoiceUnavailable(why)
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _load_error and time.monotonic() < _retry_at:
            raise VoiceUnavailable(_load_error)
        if _loader is None or not _loader.is_alive():
            _load_error = ""
            _loader = threading.Thread(target=_load, name="voice-load", daemon=True)
            _loader.start()
    raise VoiceWarming


# ── Sessions: one per open mic ───────────────────────────────────────────────

# How many mics one signed-in person may hold open at once. A hub with sign-in
# off can't tell its callers apart, so there only MAX_SESSIONS applies.
MAX_SESSIONS_PER_CALLER = 4


@dataclass
class Session:
    detector: Any
    leftover: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    last_seen: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


# Keyed by (caller, id): a mic is reachable only by whoever opened it.
_sessions: dict[tuple[str | None, str], Session] = {}
_sessions_lock = threading.Lock()


def _sweep(now: float) -> None:
    for key in [k for k, sess in _sessions.items() if now - sess.last_seen > SESSION_IDLE_S]:
        del _sessions[key]


def _session(caller: str | None, sid: str, eng: Engine) -> Session:
    now = time.monotonic()
    with _sessions_lock:
        _sweep(now)
        sess = _sessions.get((caller, sid))
        if sess is None:
            if len(_sessions) >= MAX_SESSIONS:
                msg = "too many microphones are open on this hub right now"
                raise VoiceUnavailable(msg)
            if (
                caller is not None
                and sum(1 for c, _ in _sessions if c == caller) >= MAX_SESSIONS_PER_CALLER
            ):
                msg = f"you already have {MAX_SESSIONS_PER_CALLER} microphones open; turn one off first"
                raise VoiceUnavailable(msg)
            sess = _sessions[(caller, sid)] = Session(detector=eng.new_detector())
        sess.last_seen = now
        return sess


def end(sid: str, caller: str | None = None) -> None:
    with _sessions_lock:
        _sessions.pop((caller, sid), None)


def open_sessions() -> int:
    with _sessions_lock:
        _sweep(time.monotonic())
        return len(_sessions)


def pcm16_to_float(data: bytes) -> np.ndarray:
    """Little-endian 16-bit PCM as float32 samples in [-1, 1]."""
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


@dataclass(frozen=True)
class Heard:
    texts: list[str]
    speaking: bool


def feed(sid: str, audio: bytes, *, final: bool = False, caller: str | None = None) -> Heard:
    """Take a chunk of a mic's audio; return the text of any speech it finished.

    ``final`` is the mic being turned off: whatever was being said is
    transcribed now rather than waiting for a pause, and the session ends.
    Raises :class:`VoiceWarming` while the engine loads, before reading the
    chunk, so the app can send the same audio again.
    """
    eng = engine()
    sess = _session(caller, sid, eng)
    texts: list[str] = []
    window = eng.window
    with sess.lock:
        samples = np.concatenate([sess.leftover, pcm16_to_float(audio)])
        whole = len(samples) - len(samples) % window
        for i in range(0, whole, window):
            sess.detector.accept_waveform(samples[i : i + window])
        sess.leftover = samples[whole:]
        if final:
            if len(sess.leftover):
                padded = np.zeros(window, dtype=np.float32)
                padded[: len(sess.leftover)] = sess.leftover
                sess.detector.accept_waveform(padded)
                sess.leftover = np.zeros(0, dtype=np.float32)
            sess.detector.flush()
        while not sess.detector.empty():
            piece = np.asarray(sess.detector.front.samples, dtype=np.float32)
            sess.detector.pop()
            if text := eng.transcribe(piece):
                texts.append(text)
        speaking = bool(sess.detector.is_speech_detected()) and not final
    if final:
        end(sid, caller)
    return Heard(texts=texts, speaking=speaking)


def reset() -> None:
    """Forget the loaded engine, any failed load, and every open mic (tests, or a model swap)."""
    global _engine, _load_error, _retry_at
    with _engine_lock:
        _engine = None
        _load_error = ""
        _retry_at = 0.0
    with _sessions_lock:
        _sessions.clear()
