# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor cold-spawn: auth-required detection + friendly error mapping.

Pins the auth-doc milestone's two guarantees:

1. ``_detect_auth_required`` recognises the cursor-agent CLI's auth-failure
   wording across the variants we've seen in the wild (and stays robust to
   minor wording changes, since cursor's exact message has shifted between
   releases). The check is intentionally generous — false positives only
   make the message slightly friendlier; the raw stderr is preserved in
   :attr:`SpawnResult.transcript`.

2. ``spawn_cursor`` translates an auth-failure subprocess exit into a
   user-facing ``daemon error`` reply that names ``cursor-agent login`` and
   also fires a ``log.warning`` on the daemon logger (operators tailing
   journalctl see the diagnostic without having to dig through the room
   transcript).

The subprocess is mocked end-to-end so the test runs without a real
``cursor-agent`` binary on PATH — same pattern as test_daemon_sse_timeout's
SSE mock.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

import pytest

from mycelium.integrations._spawn_common import SpawnRequest
from mycelium.integrations.cursor import spawn as cursor_spawn

# ── _detect_auth_required: positive cases ────────────────────────────────────


@pytest.mark.parametrize(
    "stderr",
    [
        "Authentication required.",
        "Error: Not authenticated\n",
        "you are not logged in",
        "Please log in to continue.",
        "ERROR: Please run `cursor-agent login` first.",
        "Authentication Required\nrun cursor-agent login",  # mixed-case
    ],
)
def test_detect_auth_required_matches_known_phrasings(stderr: str) -> None:
    assert cursor_spawn._detect_auth_required(stderr) is True


# ── _detect_auth_required: negative cases ────────────────────────────────────


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "Some other error",
        "Connection refused",
        # Doesn't match — must not over-trigger on the unrelated word "auth".
        "rate limit: too many requests",
    ],
)
def test_detect_auth_required_does_not_overmatch(stderr: str) -> None:
    assert cursor_spawn._detect_auth_required(stderr) is False


# ── spawn_cursor: friendly auth-error path ───────────────────────────────────


class _FakeProc:
    """Minimal stand-in for an ``asyncio.subprocess.Process``.

    Only implements the surface ``spawn_cursor`` touches: ``returncode``,
    ``communicate()``. The real subprocess module returns bytes; mirror
    that so ``decode()`` calls in spawn_cursor exercise the same path.
    """

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _install_fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
) -> None:
    """Replace ``asyncio.create_subprocess_exec`` with a fixture that
    returns a ``_FakeProc`` so spawn_cursor never shells out."""

    async def _fake_create(*_args: Any, **_kwargs: Any) -> _FakeProc:
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    # spawn_cursor early-exits if ``cursor-agent`` isn't on PATH; pretend
    # it is so we exercise the subprocess path. tmp_path makes the cwd
    # check pass for free below.
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/cursor-agent")


def test_spawn_cursor_translates_auth_failure_to_friendly_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: a real cursor-agent exits non-zero with an auth-required
    stderr on a daemon host that's never run ``cursor-agent login``. The
    daemon must reply with a message that names the fix command AND log a
    warning so the operator notices."""
    _install_fake_subprocess(
        monkeypatch,
        returncode=1,
        stdout=b"",
        stderr=b"Error: Authentication required. Please run `cursor-agent login`.",
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="ping",
        description="design system owner",
        sender="@julia",
        binary="cursor-agent",
    )

    with caplog.at_level(logging.WARNING, logger="mycelium.daemon"):
        result = asyncio.run(cursor_spawn.spawn_cursor(request=request))

    assert result.ok is False
    assert result.aborted is False
    assert "cursor-agent login" in result.final_message
    assert "not authenticated" in result.final_message
    # The raw stderr is preserved on transcript so operators can grep
    # the original message if they need to.
    assert "Authentication required" in result.transcript
    # Warning fired with the handle — operators tailing journalctl see
    # which agent the auth failure belongs to.
    assert any(
        "cursor auth required" in rec.getMessage() and "design-agent" in rec.getMessage()
        for rec in caplog.records
    )


def test_spawn_cursor_non_auth_failure_does_not_get_friendly_auth_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Negative: an unrelated non-zero exit must keep the generic error
    surface — false positives on the auth path would mis-direct the
    operator and slow real debugging."""
    _install_fake_subprocess(
        monkeypatch,
        returncode=2,
        stdout=b"",
        stderr=b"some completely unrelated cursor-agent crash",
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="ping",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))

    assert result.ok is False
    assert "cursor-agent login" not in result.final_message
    assert "exited 2" in result.final_message
    assert "some completely unrelated cursor-agent crash" in result.final_message
