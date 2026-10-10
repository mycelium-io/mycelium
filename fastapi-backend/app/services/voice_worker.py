# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The voice worker: transcription in a process of its own.

ONNX Runtime keeps the memory a model used after the model is dropped, and
loading it again grows the process further, so the speech model can't be let
go inside the hub. Instead the hub starts this worker the first time a mic
opens. The worker loads the models, serves every mic's chunks
(``voice.feed``) over a pipe, and exits after :data:`IDLE_EXIT_S` with no mic
open, which returns all of its memory. The hub never imports sherpa-onnx.

The hub side is :func:`feed` and :func:`end`, with the same contract as
``voice.feed`` / ``voice.end``: :class:`voice.VoiceWarming` while the worker
starts (or restarts after exiting), so the app sends the chunk again, and
:class:`voice.VoiceUnavailable` with the reason when it can't run at all. One
request is on the pipe at a time; the worker decodes one at a time anyway.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as mp
import threading
import time
from typing import TYPE_CHECKING, Any

from app.services import voice

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess

logger = logging.getLogger(__name__)

# No mic open for this long and the worker exits, giving back the ~300 MB the
# model holds. Starting it again takes about a second.
IDLE_EXIT_S = 300.0
# How long the worker may take to load the models before it's given up on.
START_TIMEOUT_S = 60.0
# A start that failed isn't tried again for this long.
START_RETRY_S = 60.0
_POLL_S = 5.0

# Tests run ``voice.feed`` in this process instead, against a stand-in engine.
IN_PROCESS = False


# ── In the worker process ────────────────────────────────────────────────────


def serve(conn: Connection, idle_exit_s: float) -> None:
    """The worker's loop: load the models, then answer the hub until idle."""
    try:
        voice.set_engine(voice.SherpaEngine(voice.ensure_models()))
    except Exception as exc:  # reported to the hub, which says why to the person
        conn.send(("failed", str(exc)))
        return
    conn.send(("ready", None))
    last = time.monotonic()
    while True:
        if not conn.poll(_POLL_S):
            if voice.open_sessions() == 0 and time.monotonic() - last > idle_exit_s:
                return
            continue
        try:
            op, args = conn.recv()
        except EOFError:
            return  # the hub is gone
        last = time.monotonic()
        try:
            if op == "feed":
                sid, audio, final, caller = args
                heard = voice.feed(sid, audio, final=final, caller=caller)
                conn.send(("ok", (heard.texts, heard.speaking)))
            else:
                sid, caller = args
                voice.end(sid, caller)
                conn.send(("ok", None))
        except voice.VoiceUnavailable as exc:
            conn.send(("unavailable", str(exc)))
        except Exception as exc:  # one bad chunk mustn't take every mic down
            logger.exception("voice worker: %s failed", op)
            conn.send(("unavailable", f"transcribing failed: {exc}"))


# ── In the hub ───────────────────────────────────────────────────────────────


class _Worker:
    def __init__(self, proc: BaseProcess, conn: Connection) -> None:
        self.proc = proc
        self.conn = conn


_worker: _Worker | None = None
_pipe_lock = threading.Lock()  # one request on the pipe at a time
_state_lock = threading.Lock()
_starter: threading.Thread | None = None
_start_error = ""
_retry_at = 0.0


def _start() -> None:
    """Fetch the models if they're missing, then start the worker and wait for it."""
    global _worker, _start_error, _retry_at

    def failed(why: str) -> None:
        global _start_error, _retry_at
        logger.warning("voice: %s", why)
        with _state_lock:
            _start_error = why
            _retry_at = time.monotonic() + START_RETRY_S

    try:
        voice.ensure_models()
    except voice.VoiceUnavailable as exc:
        failed(str(exc))
        return
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=serve, args=(child, IDLE_EXIT_S), name="mycelium-voice", daemon=True)
    proc.start()
    child.close()
    if not parent.poll(START_TIMEOUT_S):
        proc.kill()
        failed("the speech model took too long to load")
        return
    try:
        kind, detail = parent.recv()
    except EOFError:
        kind, detail = "failed", "the voice worker stopped while starting"
    if kind != "ready":
        proc.join(5)
        failed(str(detail))
        return
    with _state_lock:
        _worker = _Worker(proc, parent)
        _start_error = ""
    logger.info("voice: worker started (pid %s)", proc.pid)


def _check_on() -> None:
    """:class:`voice.VoiceUnavailable` with the reason when voice can't run here."""
    current, why = voice.state()
    if current == "unavailable":
        raise voice.VoiceUnavailable(why)


def _running() -> _Worker:
    """The worker, or :class:`voice.VoiceWarming` while one is started."""
    global _starter, _start_error
    _check_on()
    with _state_lock:
        if _worker is not None and _worker.proc.is_alive():
            return _worker
        if _start_error and time.monotonic() < _retry_at:
            raise voice.VoiceUnavailable(_start_error)
        if _starter is None or not _starter.is_alive():
            _start_error = ""
            _starter = threading.Thread(target=_start, name="voice-start", daemon=True)
            _starter.start()
    raise voice.VoiceWarming


def _ask(worker: _Worker, op: str, args: tuple[Any, ...]) -> Any:
    global _worker
    with _pipe_lock:
        try:
            worker.conn.send((op, args))
            kind, payload = worker.conn.recv()
        except (EOFError, OSError):
            # It exited (idle, or crashed) between our check and the send:
            # start another now, and have the app send the chunk again.
            with _state_lock:
                if _worker is worker:
                    _worker = None
            with contextlib.suppress(voice.VoiceWarming, voice.VoiceUnavailable):
                _running()
            raise voice.VoiceWarming from None
    if kind == "unavailable":
        raise voice.VoiceUnavailable(payload)
    return payload


def feed(sid: str, audio: bytes, *, final: bool = False, caller: str | None = None) -> voice.Heard:
    """Hand one mic's chunk to the worker; what it heard comes back."""
    if IN_PROCESS:
        _check_on()
        return voice.feed(sid, audio, final=final, caller=caller)
    texts, speaking = _ask(_running(), "feed", (sid, audio, final, caller))
    return voice.Heard(texts=texts, speaking=speaking)


def end(sid: str, caller: str | None = None) -> None:
    """Close a mic. Nothing to do when no worker is running: it has no mics."""
    if IN_PROCESS:
        voice.end(sid, caller)
        return
    worker = _worker
    if worker is not None and worker.proc.is_alive():
        try:
            _ask(worker, "end", (sid, caller))
        except (voice.VoiceWarming, voice.VoiceUnavailable):
            pass


def stop() -> None:
    """Stop the worker (tests, and a hub shutting down)."""
    global _worker, _start_error, _retry_at
    with _state_lock:
        worker, _worker = _worker, None
        _start_error, _retry_at = "", 0.0
    if worker is not None:
        worker.conn.close()
        worker.proc.join(5)
        if worker.proc.is_alive():
            worker.proc.kill()
