# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A program's output is always drained, and a hub that stops answering is said.

A program whose output pipe nobody drains blocks on its next write once the
pipe fills. The desktop hub froze like that. These hold that a reader keeps
draining whatever happens to a line, that a dead reader is replaced, that the
supervisor's own writing never waits on its log or on the app, and that a hub
that stops answering is reported and restarted only on a yes.
"""

from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mycelium.desktop import supervisor as sv
from mycelium.desktop.events import EventWriter
from mycelium.desktop.supervisor import Component, Locator, Supervisor
from mycelium.runner import approvals

#: Far more than a pipe holds (64 KB on macOS and Linux), then a clean exit.
FLOOD = [sys.executable, "-c", "import sys\nfor i in range(40000): print('x' * 40, i)\n"]


def _supervisor(tmp_path: Path, emit) -> Supervisor:
    sup = Supervisor(
        "client",
        hub_url="http://hub.example",
        emit=emit,
        env={},
        start_runner=False,
        locator=Locator(None, None),
        requests_base=tmp_path,
    )
    sup.components = []
    return sup


def _wait(cond, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_a_reader_keeps_draining_when_a_line_cant_be_written(tmp_path: Path):
    def broken(event: dict[str, Any]) -> None:
        if event.get("type") == "log":
            raise OSError(28, "No space left on device")

    sup = _supervisor(tmp_path, broken)
    c = Component(name="hub", argv=lambda: (FLOOD, None), ready=lambda: True)
    sup._spawn(c)
    assert c.proc is not None
    # Every line failed to be written, and still the program ran to the end
    # rather than blocking on a full pipe.
    assert _wait(lambda: c.proc is not None and c.proc.poll() is not None)
    assert c.proc.returncode == 0
    assert c.tail[-1].endswith("39999")


def test_a_dead_reader_is_replaced(tmp_path: Path):
    sup = _supervisor(tmp_path, lambda _e: None)
    sleeper = [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(30)"]
    c = Component(name="hub", argv=lambda: (sleeper, None), ready=lambda: True)
    sup._spawn(c)
    try:
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        c.reader = dead
        sup._tick(c)
        assert c.reader is not dead
        assert c.reader is not None and c.reader.is_alive()
    finally:
        sup._terminate(c)


def test_a_hub_that_stops_answering_is_said_and_restarted_on_a_yes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(approvals, "CHECK_S", 0.01)
    events: list[dict[str, Any]] = []
    sup = _supervisor(tmp_path, events.append)
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    answering = [True]
    c = Component(name="hub", argv=lambda: (sleeper, None), ready=lambda: answering[0], watch=True)
    sup.components = [c]
    sup._spawn(c)
    try:
        sup._set(c, "running")
        c.tail.extend(["started", "Traceback: something stuck"])
        answering[0] = False
        sup._watch(c, now=1.0)  # first miss: noted
        sup._watch(c, now=1.0 + sv.WATCH_S)  # still under a minute: nothing yet
        assert sup.status()["hung"] is None
        sup._watch(c, now=2.0 + sv.HUNG_S)
        status = sup.status()
        assert status["hung"] == "hub"
        assert sv.hung_warning("hub") in status["warnings"]
        (request,) = [e["request"] for e in events if e["type"] == "request"]
        assert request["title"] == "The hub stopped responding"
        assert "Traceback: something stuck" in request["message"]
        # Asked once per process, however long it stays stuck.
        sup._watch(c, now=3.0 + 2 * sv.HUNG_S)
        assert len([e for e in events if e["type"] == "request"]) == 1

        old = c.proc
        approvals.answer(request["id"], yes=True, base=tmp_path)
        assert _wait(lambda: c.restart_now, timeout=5)
        sup._tick(c)
        assert old is not None and old.poll() is not None
        assert (c.state, c.detail) == ("starting", "restarting: it stopped responding")
        assert sup.status()["hung"] is None
    finally:
        sup._terminate(c)


def test_a_hub_that_answers_again_clears_the_warning(tmp_path: Path):
    sup = _supervisor(tmp_path, lambda _e: None)
    answering = [False]
    c = Component(name="hub", argv=lambda: ([], None), ready=lambda: answering[0], watch=True)
    c.state = "running"
    sup.hung = "hub"
    answering[0] = True
    sup._watch(c, now=1.0)
    assert sup.hung is None


class StuckStdout(io.StringIO):
    """A stdout whose reader went away without closing it: writes wait."""

    def __init__(self) -> None:
        super().__init__()
        self.free = threading.Event()

    def write(self, text: str) -> int:
        self.free.wait()
        return super().write(text)


def test_the_supervisors_own_writing_never_waits(tmp_path: Path):
    stuck = StuckStdout()
    writer = EventWriter(tmp_path / "desktop.log", line=str, stdout=stuck, queue_size=50)
    started = time.monotonic()
    for i in range(5_000):
        writer.emit({"type": "log", "component": "hub", "line": str(i)})
    assert time.monotonic() - started < 1.0
    assert writer.dropped > 0
    stuck.free.set()
    writer.close()


def test_the_log_is_rotated_by_size(tmp_path: Path):
    log = tmp_path / "desktop.log"
    writer = EventWriter(log, line=lambda e: "x" * 100, max_bytes=1_000)
    for _ in range(30):
        writer.emit({"type": "log"})
    writer.close()
    assert (tmp_path / "desktop.log.1").exists()
    assert log.stat().st_size <= 1_100


def test_a_full_disk_loses_lines_but_not_the_writer(tmp_path: Path, monkeypatch):
    out = io.StringIO()
    writer = EventWriter(tmp_path / "desktop.log", line=str, stdout=out)

    def full(*_a: Any) -> None:
        raise OSError(28, "No space left on device")

    assert writer._log is not None
    monkeypatch.setattr(writer._log, "write", full)
    writer.emit({"type": "log", "line": "lost"})
    writer.emit({"type": "status", "line": "still sent to the app"})
    writer.close()
    assert "still sent to the app" in out.getvalue()
