# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression: cc-daemon log lines were being written twice.

Both the systemd unit template (``StandardOutput=append:<log>`` /
``StandardError=append:<log>``) and the launchd plist (``StandardOutPath`` /
``StandardErrorPath``) already route the daemon's stdout+stderr to
``daemon_log_path()``. Earlier the daemon *also* attached a
``logging.FileHandler`` for the same path, so every record landed in the file
twice — once via the supervisor's stdout capture (the StreamHandler) and once
via the FileHandler. ``cc-daemon.log`` ended up with ~50% adjacent-duplicate
lines and an inflated row count.

The fix in ``_setup_logging`` picks exactly one sink per mode: stdout in
foreground (interactive) and the file directly when running under a
supervisor. This test pins that contract so a future "let's also tee to
stdout" tweak can't silently reintroduce the duplication.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from mycelium.daemon import runner


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """``logging.basicConfig(force=True)`` mutates the root logger; snapshot
    its handlers so this test never leaks state into siblings (especially
    other tests that read ``caplog``)."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    try:
        yield
    finally:
        for h in root.handlers[:]:
            if h not in original_handlers:
                # Avoid leaking open file handles between tests.
                with contextlib.suppress(Exception):
                    h.close()
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_foreground_uses_only_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Foreground (interactive) runs must not open the daemon log file —
    that would race against a separately-running supervised daemon and
    surprise developers debugging at the terminal."""
    log_path = tmp_path / "cc-daemon.log"
    monkeypatch.setattr(runner, "daemon_log_path", lambda: log_path)

    runner._setup_logging(foreground=True)

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1, f"expected one handler, got {handlers!r}"
    assert isinstance(handlers[0], logging.StreamHandler)
    assert not isinstance(handlers[0], logging.FileHandler)
    assert not log_path.exists(), "foreground mode must not touch the file"


def test_background_uses_only_filehandler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Under systemd/launchd the supervisor already routes stdout+stderr to
    the same file. Attaching a StreamHandler here would double every line.
    Pin the FileHandler-only contract."""
    log_path = tmp_path / "cc-daemon.log"
    monkeypatch.setattr(runner, "daemon_log_path", lambda: log_path)

    runner._setup_logging(foreground=False)

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1, (
        "background mode must use exactly one handler; a second StreamHandler "
        "would be re-captured by the supervisor's StandardOutput=append and "
        "duplicate every record."
    )
    assert isinstance(handlers[0], logging.FileHandler)
    # FileHandler is itself a StreamHandler subclass; the assertion above is
    # the meaningful one. Sanity-check the path it points at:
    assert Path(handlers[0].baseFilename) == log_path

    logging.getLogger("mycelium.daemon").info("smoketest")
    handlers[0].flush()
    contents = log_path.read_text()
    assert contents.count("smoketest") == 1, (
        f"log line landed multiple times — a second handler crept back in:\n{contents!r}"
    )


def test_background_falls_back_to_stderr_if_file_unopenable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the log file can't be opened (permission denied, missing dir on a
    read-only mount, etc.) we must still emit *somewhere* so the operator
    can see the failure — even if that "somewhere" is just stderr captured
    by the supervisor."""
    bogus_path = tmp_path / "no-such-dir" / "cc-daemon.log"
    monkeypatch.setattr(runner, "daemon_log_path", lambda: bogus_path)

    runner._setup_logging(foreground=False)

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert not isinstance(handlers[0], logging.FileHandler)
