# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Voice: what someone says into their microphone, transcribed on the hub.

The app streams 16 kHz mono audio here in small chunks while a person has the
mic toggled on (``routes/voice.py``). Each open mic is a session holding a
Silero voice activity detector, which hears where speech starts and stops; each
stretch of speech it closes is transcribed by the hub's speech model and handed
back as text for the composer's draft. Pauses only split speech into pieces;
nothing here decides when to stop listening or to send.

Two speech models are offered (``voice.model``, :data:`MODELS`): ``fast`` is
Moonshine v2 base (~150 MB on disk, a ~500 MB worker), and ``accurate`` is
NVIDIA's Parakeet TDT 0.6B v2 (~630 MB on disk, a ~1.4 GB worker), which makes
about half the mistakes. Both are English only. The hub reads the choice when it
starts.

Voice is off unless the hub's operator turns it on (``voice.enabled``). Off,
nothing here loads or downloads anything. On, the chosen model is fetched once
into :func:`model_dir` (the data folder, so a rebuilt container keeps them):
Moonshine as the hub starts, Parakeet only once someone turns a mic on, since
it's a larger download a hub may never use. The sessions and the engine here
run inside the voice worker (``voice_worker.py``), a process the hub starts
when a mic opens and that exits once nobody is talking, because ONNX Runtime
never gives a model's memory back to the process that loaded it. The models
run on the CPU through sherpa-onnx, like the search model runs through
fastembed. Audio is never stored: a session holds only the samples of the
piece it is hearing, and forgets a mic left idle.

One limit shapes Moonshine's cutting: sherpa-onnx 1.13.8 returns empty text
for a Moonshine v2 piece much past six seconds (k2-fsa/sherpa-onnx#3975, fixed
after that release). For it the detector caps a piece's length, and
:func:`split_long` cuts anything longer at its quietest point, so no piece
reaches the model whole. Parakeet has no such limit: its pieces end at a pause,
or after :data:`ACCURATE`'s ``max_piece_s`` of unbroken speech so text still
arrives during a long run.
"""

from __future__ import annotations

import hashlib
import importlib.util
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

SILERO = "silero_vad_v5.onnx"
_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
# What the Silero release asset was when this was written; a download that
# doesn't match is refused.
SILERO_SHA256 = "6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396"

# A mic left this long without a chunk is closed; the app sends one every
# fraction of a second while it is on.
SESSION_IDLE_S = 60.0
MAX_SESSIONS = 16

State = Literal["ready", "not_downloaded", "unavailable"]


@dataclass(frozen=True)
class SpeechModel:
    """One speech model a hub can run, and how it's fetched and cut."""

    #: The ``voice.model`` value that picks it.
    choice: str
    #: Its archive on sherpa-onnx's release page, and the folder it unpacks to.
    folder: str
    #: What that archive was when this was written; a download that differs is refused.
    archive_sha256: str
    #: The files the engine loads, by role, inside ``folder``.
    files: dict[str, str]
    #: What each of those files was in the archive. Only read to take on a
    #: folder unpacked before the marker existed: whole files are marked
    #: rather than downloaded again, and a half-written one doesn't match.
    file_sha256: dict[str, str]
    #: The longest piece handed to the model, in seconds.
    max_piece_s: float
    #: A pause this long ends a piece of speech.
    min_silence_s: float
    #: Whether the hub fetches it as it starts, rather than when a mic opens.
    fetch_at_start: bool


FAST = SpeechModel(
    choice="fast",
    folder="sherpa-onnx-moonshine-base-en-quantized-2026-02-27",
    archive_sha256="43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891",
    files={
        "encoder": "encoder_model.ort",
        "decoder": "decoder_model_merged.ort",
        "tokens": "tokens.txt",
    },
    file_sha256={
        "encoder": "7c66495948d0d08ec1af454cd4b5514862ae6511e94712a60e6d83eaec8dc8cf",
        "decoder": "d9d7b333af34bc552580576ddcf248a1c6c839e0d3b43b09afb9376ed009899d",
        "tokens": "2870d843e14c1e187bf1913a521562a63b53933814bd7f2145120468f494a049",
    },
    # Under the length past which Moonshine v2 comes back empty (see above).
    max_piece_s=5.5,
    # Short enough that text arrives while someone is still talking in
    # sentences, long enough not to split words.
    min_silence_s=0.4,
    fetch_at_start=True,
)

ACCURATE = SpeechModel(
    choice="accurate",
    folder="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
    archive_sha256="157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad",
    files={
        "encoder": "encoder.int8.onnx",
        "decoder": "decoder.int8.onnx",
        "joiner": "joiner.int8.onnx",
        "tokens": "tokens.txt",
    },
    file_sha256={
        "encoder": "a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab",
        "decoder": "b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e",
        "joiner": "7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2",
        "tokens": "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d",
    },
    # Not a limit of the model: unbroken speech this long is handed over
    # anyway, so text keeps arriving. The detector buffers 30 s.
    max_piece_s=20.0,
    # It reads a whole sentence better than its halves, and is quick enough
    # that waiting for a longer pause costs little.
    min_silence_s=1.0,
    fetch_at_start=False,
)

MODELS = {m.choice: m for m in (FAST, ACCURATE)}

# Kept by name: Moonshine is what a hub runs unless told otherwise.
MOONSHINE = FAST.folder
MOONSHINE_SHA256 = FAST.archive_sha256
MAX_PIECE_S = FAST.max_piece_s
MIN_SILENCE_S = FAST.min_silence_s


class VoiceUnavailable(RuntimeError):
    """The hub can't transcribe right now, with the reason to show the person."""


def chosen() -> SpeechModel:
    """The model ``voice.model`` picks, or :class:`VoiceUnavailable` for one it doesn't know."""
    model = MODELS.get(settings.VOICE_MODEL.strip().lower())
    if model is None:
        msg = f"voice.model is {settings.VOICE_MODEL!r}; it's one of " + ", ".join(
            repr(name) for name in MODELS
        )
        raise VoiceUnavailable(msg)
    return model


def model_dir() -> Path:
    """Where the models live: ``VOICE_MODEL_DIR``, else ``<data dir>/models/voice``."""
    if settings.VOICE_MODEL_DIR:
        return Path(settings.VOICE_MODEL_DIR)
    return Path(settings.MYCELIUM_DATA_DIR) / "models" / "voice"


def _files(root: Path, model: SpeechModel) -> dict[str, Path]:
    folder = root / model.folder
    return {role: folder / name for role, name in model.files.items()} | {"vad": root / SILERO}


# Written into a model's folder once its archive has been checked and
# unpacked, holding the archive's hash. A folder without it may be half
# unpacked (or from an older archive), and a half-written .ort file is what
# ONNX Runtime refuses with "ORT model verification failed".
UNPACKED_MARKER = ".verified"


def _present(root: Path, model: SpeechModel) -> bool:
    """Whether the models are on disk, whole.

    The files existing isn't enough: they appear one by one while the archive
    unpacks. So a hub that fetches its own models also needs the marker an
    unpack writes last. With ``VOICE_DOWNLOAD`` off the operator put the
    files there, and their existing is taken as their being whole.
    """
    if not all(p.is_file() for p in _files(root, model).values()):
        return False
    return not settings.VOICE_DOWNLOAD or _unpacked(root, model)


def _unpacked(root: Path, model: SpeechModel) -> bool:
    marker = root / model.folder / UNPACKED_MARKER
    try:
        return marker.read_text().strip() == model.archive_sha256
    except OSError:
        return False


def _adopt_unmarked(root: Path, model: SpeechModel) -> bool:
    """Mark a model folder whose files are whole, and say whether it was."""
    files = _files(root, model)
    for role, want in model.file_sha256.items():
        digest = hashlib.sha256()
        try:
            with files[role].open("rb") as f:
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
        except OSError:
            return False
        if digest.hexdigest() != want:
            return False
    (root / model.folder / UNPACKED_MARKER).write_text(model.archive_sha256 + "\n")
    return True


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
        return "unavailable", "voice is off on this hub (voice.enabled)"
    # Found rather than imported: the hub itself never loads it.
    if importlib.util.find_spec("sherpa_onnx") is None:
        return "unavailable", "this hub has no speech runtime (sherpa-onnx)"
    try:
        model = chosen()
    except VoiceUnavailable as exc:
        return "unavailable", str(exc)
    if _present(model_dir(), model):
        return "ready", ""
    if settings.VOICE_DOWNLOAD:
        if model.fetch_at_start:
            return "not_downloaded", "the speech model is still downloading"
        return "not_downloaded", "the speech model downloads the first time a mic is turned on"
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


def _unpack(root: Path, model: SpeechModel) -> None:
    """Fetch and unpack a model's archive, then move it into place at once.

    Everything happens in a staging folder beside the real one, which is only
    renamed into place once it's whole and marked, so nothing ever sees a
    model folder with some of its files written.
    """
    staging = root / f".{model.folder}.{secrets.token_hex(4)}.part"
    staging.mkdir()
    try:
        archive = staging / f"{model.folder}.tar.bz2"
        _fetch(f"{_RELEASE}/{model.folder}.tar.bz2", archive, model.archive_sha256)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(staging, filter="data")
        unpacked = staging / model.folder
        (unpacked / UNPACKED_MARKER).write_text(model.archive_sha256 + "\n")
        shutil.rmtree(root / model.folder, ignore_errors=True)
        unpacked.rename(root / model.folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure_models() -> Path:
    """The model folder, fetching what the chosen model needs once if the hub may."""
    model = chosen()
    root = model_dir()
    if _present(root, model):
        return root
    if not settings.VOICE_DOWNLOAD:
        msg = f"the speech model isn't at {root}"
        raise VoiceUnavailable(msg)
    with _download_lock:
        if _present(root, model):
            return root
        root.mkdir(parents=True, exist_ok=True)
        logger.info("voice: fetching the %s speech model into %s", model.choice, root)
        try:
            if not (root / SILERO).is_file():
                _fetch(f"{_RELEASE}/{SILERO}", root / SILERO, SILERO_SHA256)
            if not _unpacked(root, model) and not _adopt_unmarked(root, model):
                _unpack(root, model)
        except (httpx.HTTPError, OSError, tarfile.TarError) as exc:
            msg = f"couldn't fetch the speech model: {exc}"
            raise VoiceUnavailable(msg) from exc
    if not _present(root, model):
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
    """The chosen speech model and Silero VAD through sherpa-onnx, loaded once per worker."""

    def __init__(self, root: Path, model: SpeechModel | None = None) -> None:
        so = _runtime()
        self.model = model or chosen()
        files = _files(root, self.model)
        self._so = so
        if "joiner" in self.model.files:  # a transducer: Parakeet
            self._recognizer = so.OfflineRecognizer.from_transducer(
                encoder=str(files["encoder"]),
                decoder=str(files["decoder"]),
                joiner=str(files["joiner"]),
                tokens=str(files["tokens"]),
                num_threads=settings.VOICE_THREADS,
                model_type="nemo_transducer",
            )
        else:
            self._recognizer = so.OfflineRecognizer.from_moonshine_v2(
                encoder=str(files["encoder"]),
                decoder=str(files["decoder"]),
                tokens=str(files["tokens"]),
                num_threads=settings.VOICE_THREADS,
            )
        self._vad = so.VadModelConfig()
        self._vad.silero_vad.model = str(files["vad"])
        self._vad.silero_vad.min_silence_duration = self.model.min_silence_s
        self._vad.silero_vad.max_speech_duration = self.model.max_piece_s
        self._vad.sample_rate = SAMPLE_RATE
        self.window = int(self._vad.silero_vad.window_size)
        # One decode at a time: they take a few hundredths of a second, and
        # the recognizer is shared by every open mic.
        self._lock = threading.Lock()

    def new_detector(self) -> Any:
        return self._so.VoiceActivityDetector(self._vad, buffer_size_in_seconds=30)

    def transcribe(self, samples: np.ndarray) -> str:
        texts = []
        for piece in split_long(samples, self.model.max_piece_s):
            with self._lock:
                stream = self._recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, piece)
                self._recognizer.decode_stream(stream)
                text = stream.result.text.strip()
            if text:
                texts.append(text)
        return " ".join(texts)


class VoiceWarming(RuntimeError):
    """The voice worker is still starting (or its models downloading); send the chunk again."""


# Set once in the voice worker, before it serves a chunk (``voice_worker.serve``).
_engine: Engine | None = None


def set_engine(eng: Engine | None) -> None:
    global _engine
    _engine = eng


def engine() -> Engine:
    """The loaded engine, or :class:`VoiceWarming` when there isn't one yet."""
    if _engine is None:
        raise VoiceWarming
    return _engine


def prefetch() -> None:
    """Start fetching the models in the background, when voice is on and they're missing.

    Called as the hub starts, so turning voice on downloads Moonshine then,
    rather than making the first person to press the mic wait for it.
    Parakeet waits for a mic: it's a larger download a hub may never use.
    """
    if state()[0] == "not_downloaded" and chosen().fetch_at_start:
        threading.Thread(target=_prefetch, name="voice-fetch", daemon=True).start()


def _prefetch() -> None:
    try:
        ensure_models()
    except VoiceUnavailable as exc:
        logger.warning("voice: %s", exc)


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
    Raises :class:`VoiceWarming` before reading the chunk when there's no
    engine yet, so the app can send the same audio again.
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
    """Forget the engine and every open mic (tests)."""
    set_engine(None)
    with _sessions_lock:
        _sessions.clear()
