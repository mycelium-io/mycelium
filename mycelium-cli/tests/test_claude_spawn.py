# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code cold-spawn — argv invariants for headless / autonomous use.

The cc-daemon spawns ``claude -p`` per ``@handle`` mention or per
``coordination_tick``. Both flows are headless: there is nobody at a
terminal to answer ``Permission required to run Bash``. Without an
explicit bypass the spawn stalls on the first tool call and the agent
posts apologetic "command needs approval" broadcasts forever — the live
failure that surfaced when claude_code first joined an autonomous
coordination round.

This test pins the exact CLI flags so a future refactor that drops the
permission-mode bypass (or switches to ``--allowedTools …`` without
covering the same surface) is caught here, not in production.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import pytest

from mycelium.integrations.claude_code import spawn as claude_spawn


class _FakeProc:
    """Stand-in for ``asyncio.subprocess.Process`` — only what
    ``spawn_claude`` touches on the happy path."""

    def __init__(self, *, returncode: int, stdout: bytes, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.pid = 4242

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _install_fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_argv: list[list[str]],
    returncode: int = 0,
    stdout: bytes = b'{"result": "ok"}',
) -> None:
    """Patch the subprocess + binary discovery surface ``spawn_claude``
    uses, capturing argv so the test can assert on what we invoked."""

    async def _fake_create(*args: Any, **_kwargs: Any) -> _FakeProc:
        captured_argv.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/claude")


def test_spawn_claude_invokes_permission_mode_bypass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The two flags the autonomous-coordination flow depends on:

    1. ``-p PROMPT`` — print mode, non-interactive.
    2. ``--permission-mode bypassPermissions`` — skip the interactive
       approval prompt for every Bash / Edit / Read tool call.

    Drop either of these and the cc-daemon's autonomous dispatch path
    silently regresses to the operator-driven accept loop (or worse,
    posts "command needs approval" forever). Pin both.
    """
    captured: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, captured_argv=captured)

    asyncio.run(
        claude_spawn.spawn_claude(
            claude_binary="claude",
            cwd=str(tmp_path),
            prompt="say hi",
            notes="",
        )
    )

    assert len(captured) == 1, "expected exactly one subprocess invocation"
    argv = captured[0]
    # Must be invoking the configured binary in print mode with the prompt.
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert argv[2] == "say hi"
    # Headless invariants — adjacent flag/value pair, in that order.
    assert "--permission-mode" in argv
    mode_idx = argv.index("--permission-mode")
    assert argv[mode_idx + 1] == "bypassPermissions", (
        "permission mode must be bypassPermissions; "
        "anything else (default / acceptEdits / plan) re-introduces the "
        "interactive approval prompt that breaks coordination_tick spawns"
    )
    # JSON output is required so parse_claude_output can read cost_usd.
    assert "--output-format" in argv
    fmt_idx = argv.index("--output-format")
    assert argv[fmt_idx + 1] == "json"


def test_spawn_claude_does_not_use_dangerously_skip_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """``--dangerously-skip-permissions`` and the ``--allow-…`` variant
    are aggressive bypasses; the narrower ``--permission-mode
    bypassPermissions`` is the documented choice. If a future refactor
    swaps in the broader flag we want a heads-up so we can re-evaluate
    threat-model assumptions for cold-spawn agents."""
    captured: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, captured_argv=captured)

    asyncio.run(
        claude_spawn.spawn_claude(
            claude_binary="claude",
            cwd=str(tmp_path),
            prompt="say hi",
            notes="",
        )
    )

    argv = captured[0]
    assert "--dangerously-skip-permissions" not in argv
    assert "--allow-dangerously-skip-permissions" not in argv


def test_spawn_claude_appends_identity_preamble_when_handle_provided(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Cold-started Claude doesn't know who it is — the preamble carries
    the handle / room / description through ``--append-system-prompt``.
    Without this the agent sometimes refuses to act under @handle ("I
    don't know who that is"). Adjacent to the permission-mode flag so
    one regression test covers both invariants."""
    captured: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, captured_argv=captured)

    asyncio.run(
        claude_spawn.spawn_claude(
            claude_binary="claude",
            cwd=str(tmp_path),
            prompt="hello",
            notes="",
            handle="planner",
            room="cursor-ioc-e2e",
            description="negotiation counterparty",
            sender="CognitiveEngine",
        )
    )

    argv = captured[0]
    assert "--append-system-prompt" in argv
    preamble_idx = argv.index("--append-system-prompt")
    preamble = argv[preamble_idx + 1]
    assert "planner" in preamble
    assert "cursor-ioc-e2e" in preamble
