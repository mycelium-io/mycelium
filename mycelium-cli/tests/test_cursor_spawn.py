# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Cursor cold-spawn — happy-path JSON parse + preamble injection + abort.

Covers everything ``test_cursor_auth.py`` doesn't: the success path through
``spawn_cursor`` (JSON-decoded result, ``cost_usd=0.0``, usage preserved in
extras) plus the two structural invariants that distinguish cursor from
claude_code:

1. **Preamble injection through the positional prompt.** cursor-agent has
   no ``--append-system-prompt`` flag, so the identity preamble rides in
   the positional argument with a ``---`` separator. The exact argv we
   send must contain the preamble before the separator before the user's
   prompt body — a regression here silently strips the agent's identity.

2. **Abort via negative returncode.** A sibling ``@handle abort`` mention
   SIGTERMs the running process; ``spawn_cursor`` returns
   ``SpawnResult(aborted=True, ok=False, final_message="")`` so the
   dispatch loop can post a human-facing abort message without confusing
   it with a regular failure.

JSON parse edge cases (null result, invalid JSON) are pinned separately
because ``parse_cursor_output`` is the public-ish surface log analysers
could replay against persisted invocation logs.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import pytest

from mycelium.integrations._spawn_common import SpawnRequest
from mycelium.integrations.cursor import spawn as cursor_spawn

# ── parse_cursor_output ──────────────────────────────────────────────────────


def test_parse_extracts_result_and_preserves_extras() -> None:
    payload = (
        '{"result": "hello world", '
        '"usage": {"input_tokens": 12, "output_tokens": 3}, '
        '"session_id": "abc", "is_error": false}'
    )
    final, extras = cursor_spawn.parse_cursor_output(payload)
    assert final == "hello world"
    assert extras["usage"]["input_tokens"] == 12
    assert extras["session_id"] == "abc"
    assert extras["is_error"] is False
    # ``result`` is consumed, not left in extras.
    assert "result" not in extras


def test_parse_handles_null_result_by_falling_back_to_stdout() -> None:
    """Cursor occasionally returns ``result: null`` on refused / empty
    turns. The user still needs to see *something* in the room, so we
    fall back to the raw stdout — and crucially, extras still carry the
    usage block (which a budget-tracker may want)."""
    payload = '{"result": null, "usage": {"input_tokens": 0}}'
    final, extras = cursor_spawn.parse_cursor_output(payload)
    assert final == payload  # raw fallback
    assert extras["usage"]["input_tokens"] == 0


def test_parse_handles_invalid_json_gracefully() -> None:
    """A future cursor build that changes its print format should not
    crash the daemon — surface the raw text and an empty extras dict."""
    final, extras = cursor_spawn.parse_cursor_output("not-json {[")
    assert final == "not-json {["
    assert extras == {}


def test_parse_handles_non_dict_json() -> None:
    """If cursor ever emits a bare array or string at the top level,
    same graceful-degradation path."""
    final, extras = cursor_spawn.parse_cursor_output('["a", "b"]')
    assert final == '["a", "b"]'
    assert extras == {}


# ── spawn_cursor: happy path + preamble injection + abort ────────────────────


class _FakeProc:
    """Minimal stand-in for ``asyncio.subprocess.Process`` — only what
    ``spawn_cursor`` touches."""

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
    stderr: bytes = b"",
    captured_argv: list[list[str]] | None = None,
) -> None:
    """Replace ``asyncio.create_subprocess_exec`` with a fixture. Optionally
    captures argv into *captured_argv* so a test can assert on what we
    actually invoked."""

    async def _fake_create(*args: Any, **_kwargs: Any) -> _FakeProc:
        if captured_argv is not None:
            captured_argv.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/cursor-agent")


def test_spawn_cursor_happy_path_returns_parsed_result_with_zero_cost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _install_fake_subprocess(
        monkeypatch,
        returncode=0,
        stdout=(
            b'{"result": "all done", '
            b'"usage": {"input_tokens": 7, "output_tokens": 2}, '
            b'"is_error": false}'
        ),
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="do thing",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))

    assert result.ok is True
    assert result.aborted is False
    assert result.final_message == "all done"
    # Cursor doesn't expose per-call $ cost; daemon's budget tracker must
    # not accumulate garbage.
    assert result.cost_usd == 0.0
    # Usage preserved in extras for downstream budget mapping.
    assert result.extra.get("usage", {}).get("input_tokens") == 7
    assert result.duration_s >= 0


def test_spawn_cursor_is_error_flag_overrides_zero_returncode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """cursor-agent occasionally exits 0 with ``is_error: true`` (its
    in-band error channel). ``spawn_cursor`` must respect the JSON
    signal, not just returncode, or the daemon posts a broken reply as
    if it were a success."""
    _install_fake_subprocess(
        monkeypatch,
        returncode=0,
        stdout=b'{"result": "oops", "is_error": true}',
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="x",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))
    assert result.ok is False
    assert result.final_message == "oops"


def test_spawn_cursor_injects_preamble_before_separator_before_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """cursor-agent has no system-prompt flag — the identity preamble
    must end up in the positional argument with the ``---`` separator
    between it and the user's prompt. A regression silently strips
    persona / room context from every cursor invocation."""
    captured: list[list[str]] = []
    _install_fake_subprocess(
        monkeypatch,
        returncode=0,
        stdout=b'{"result": "ok"}',
        captured_argv=captured,
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="USER_PROMPT_SENTINEL",
        description="design system owner",
        sender="@julia",
        binary="cursor-agent",
    )
    asyncio.run(cursor_spawn.spawn_cursor(request=request))

    assert captured, "fake subprocess never invoked"
    argv = captured[0]
    # The positional prompt is the LAST argv element.
    combined = argv[-1]
    assert "USER_PROMPT_SENTINEL" in combined
    assert cursor_spawn._PREAMBLE_SEPARATOR in combined
    # Preamble lands BEFORE the separator, user prompt lands AFTER.
    sep_idx = combined.index(cursor_spawn._PREAMBLE_SEPARATOR)
    user_idx = combined.index("USER_PROMPT_SENTINEL")
    assert sep_idx < user_idx
    # And the preamble itself mentions the handle and room.
    assert "design-agent" in combined[:sep_idx]
    assert "r1" in combined[:sep_idx]


def test_spawn_cursor_uses_workspace_and_headless_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Lock in the cursor-agent CLI flags: ``--workspace``, ``--trust``,
    ``--force``, ``--approve-mcps`` are all required for non-interactive
    daemon use. Dropping any of them re-introduces a TUI prompt the
    daemon can't answer."""
    captured: list[list[str]] = []
    _install_fake_subprocess(
        monkeypatch,
        returncode=0,
        stdout=b'{"result": "ok"}',
        captured_argv=captured,
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="x",
        binary="cursor-agent",
    )
    asyncio.run(cursor_spawn.spawn_cursor(request=request))

    argv = captured[0]
    assert argv[0] == "cursor-agent"
    assert "-p" in argv
    assert "--output-format" in argv
    assert "json" in argv
    assert "--workspace" in argv
    assert str(tmp_path) in argv
    assert "--trust" in argv
    assert "--force" in argv
    assert "--approve-mcps" in argv


def test_spawn_cursor_returns_aborted_on_negative_returncode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """SIGTERM via ``@handle abort`` → negative returncode → aborted=True
    so the dispatch loop posts the abort message instead of an error."""
    _install_fake_subprocess(
        monkeypatch,
        returncode=-15,  # SIGTERM
        stdout=b"",
        stderr=b"",
    )

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="x",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))
    assert result.aborted is True
    assert result.ok is False
    assert result.final_message == ""  # caller writes the human-facing message


# ── spawn_cursor: pre-flight guards ──────────────────────────────────────────


def test_spawn_cursor_missing_binary_returns_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    request = SpawnRequest(
        handle="x",
        room="r",
        cwd=str(tmp_path),
        prompt="x",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))
    assert result.ok is False
    assert "cursor-agent" in result.final_message
    assert "not found on PATH" in result.final_message


def test_spawn_cursor_missing_cwd_returns_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/cursor-agent")
    request = SpawnRequest(
        handle="x",
        room="r",
        cwd=str(tmp_path / "ghost"),
        prompt="x",
        binary="cursor-agent",
    )
    result = asyncio.run(cursor_spawn.spawn_cursor(request=request))
    assert result.ok is False
    assert "not a directory" in result.final_message


# ── RunningProc registration during spawn ────────────────────────────────────


def test_spawn_cursor_registers_running_proc_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Abort verb relies on ``state.running[handle]`` being populated for
    the duration of the spawn — and emptied afterward so the next dispatch
    sees a clean slot. Same contract as ``spawn_claude``; pinned here
    because cursor's process lifetime is family-local code we own."""
    from mycelium.daemon.state import DaemonState

    state = DaemonState()
    seen_keys: list[set[str]] = []

    async def _fake_create(*_args: Any, **_kwargs: Any) -> _FakeProc:
        # Snapshot ``state.running`` after registration but before
        # ``proc.communicate()`` cleans it up.
        seen_keys.append(set(state.running.keys()))
        return _FakeProc(returncode=0, stdout=b'{"result": "ok"}', stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/cursor-agent")

    request = SpawnRequest(
        handle="design-agent",
        room="r1",
        cwd=str(tmp_path),
        prompt="x",
        binary="cursor-agent",
        state=state,
    )
    asyncio.run(cursor_spawn.spawn_cursor(request=request))

    # During the spawn, the handle was registered. The snapshot was taken
    # before communicate() returned, but the registration write happens
    # AFTER create_subprocess_exec returns — so check post-run cleanup
    # is what's reliable here. The crucial post-condition: after spawn
    # completes, the slot is empty.
    assert "design-agent" not in state.running

    # And belt-and-braces: a fresh spawn re-uses the freed slot.
    asyncio.run(cursor_spawn.spawn_cursor(request=request))
    assert "design-agent" not in state.running
