# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Claude Code cold-spawn — invokes ``claude -p`` for one ``@handle`` mention.

Relocated from ``mycelium/daemon/dispatch.py`` (where it lived as
``spawn_claude`` / ``_parse_claude_output``) so the daemon dispatch loop can
call ``Integration.spawn(...)`` uniformly across cold-spawn families instead
of branching on ``manifest.adapter``.

The function body is unchanged — same shutil.which probe, same subprocess
exec, same JSON parser. ``RunningProc`` registration also stays here in this
commit; the next milestone (daemon-core) moves it up into the daemon loop so
all cold-spawn families (claude_code, cursor, future) inherit abort/status
behaviour from one place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mycelium.daemon.preamble import identity_preamble

if TYPE_CHECKING:
    from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon")


def parse_claude_output(stdout: str) -> tuple[str, float]:
    """Pull (final_message, cost_usd) out of ``claude -p --output-format json``.

    Claude Code emits a JSON array of stream events: system/init, assistant
    messages, optional rate_limit_event, and a terminal ``type=="result"``
    entry that carries the assistant's plain-text answer and ``total_cost_usd``.
    Older builds may return a single dict with ``result`` at the top level —
    handle both, and fall back to the raw stdout when neither matches.
    """
    try:
        parsed: Any = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, 0.0

    def _extract_from_obj(obj: Any) -> tuple[str | None, float]:
        if not isinstance(obj, dict):
            return None, 0.0
        o: dict[str, Any] = obj
        msg = o.get("result") or o.get("final_message") or o.get("text")
        cost = float(o.get("total_cost_usd") or o.get("cost_usd") or 0.0)
        return msg, cost

    if isinstance(parsed, dict):
        msg, cost = _extract_from_obj(parsed)
        return msg or stdout, cost

    if isinstance(parsed, list):
        items: list[Any] = list(parsed)
        # Walk back to front — `result` entries land last.
        for entry in reversed(items):
            if not (isinstance(entry, dict) and entry.get("type") == "result"):
                continue
            msg, cost = _extract_from_obj(entry)
            if msg is not None:
                return msg, cost
        # Fall back to the most recent assistant message.
        for entry in reversed(items):
            if not (isinstance(entry, dict) and entry.get("type") == "assistant"):
                continue
            message: Any = entry.get("message") or {}
            content: Any = message.get("content") if isinstance(message, dict) else None
            for piece in content or []:
                if isinstance(piece, dict) and piece.get("type") == "text":
                    return piece.get("text") or stdout, 0.0

    return stdout, 0.0


async def spawn_claude(
    *,
    claude_binary: str,
    cwd: str,
    prompt: str,
    notes: str,
    state: DaemonState | None = None,
    handle: str | None = None,
    sender: str | None = None,
    room: str | None = None,
    description: str = "",
    plan_block: str = "",
) -> dict[str, Any]:
    """Run ``claude -p`` with the agent's notes as system prompt.

    Returns a dict with ``final_message``, ``transcript``, ``cost_usd``,
    ``duration_s``, ``ok``. Falls back gracefully when the CLI returns plain
    text instead of JSON, since not every Claude Code build exposes
    ``--output-format json``.
    """
    from mycelium.daemon.state import RunningProc

    if shutil.which(claude_binary) is None:
        return {
            "ok": False,
            "final_message": (
                f"daemon error: `{claude_binary}` not found on PATH. "
                "Install Claude Code or set `claude_binary` in cc-daemon.toml."
            ),
            "transcript": "",
            "cost_usd": 0.0,
            "duration_s": 0.0,
        }

    expanded_cwd = os.path.expanduser(cwd)
    if not Path(expanded_cwd).is_dir():
        return {
            "ok": False,
            "final_message": f"daemon error: cwd '{cwd}' is not a directory.",
            "transcript": "",
            "cost_usd": 0.0,
            "duration_s": 0.0,
        }

    cmd = [
        claude_binary,
        "-p",
        prompt,
        "--output-format",
        "json",
    ]
    # Always inject an identity preamble — cold-started Claude doesn't know
    # it's been routed to as @handle without it.
    if handle:
        preamble = identity_preamble(
            handle=handle,
            room=room or "(unknown)",
            description=description or "",
            sender=sender or "(anonymous)",
            notes=notes,
            plan_block=plan_block,
        )
        cmd.extend(["--append-system-prompt", preamble])
    elif notes.strip():
        cmd.extend(["--append-system-prompt", notes])

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=expanded_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "final_message": f"daemon error: spawn failed ({exc})",
            "transcript": "",
            "cost_usd": 0.0,
            "duration_s": time.monotonic() - started,
        }

    # Register so a sibling `@handle abort` message can SIGTERM us. Cleared
    # in finally so the next dispatch sees an empty slot. The daemon-core
    # milestone will move this up to the dispatch loop so every cold-spawn
    # family gets it uniformly.
    if state is not None and handle is not None:
        state.running[handle] = RunningProc(
            process=proc,
            started_at=started,
            prompt=prompt,
            sender=sender or "",
            room=room or "",
        )
    try:
        stdout_b, stderr_b = await proc.communicate()
    finally:
        if state is not None and handle is not None:
            state.running.pop(handle, None)

    duration = time.monotonic() - started
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode is not None and proc.returncode < 0:
        # Negative return code → terminated by signal (SIGTERM from abort verb).
        return {
            "ok": False,
            "aborted": True,
            "final_message": "",  # caller writes the human-facing abort message
            "transcript": stdout + ("\n" + stderr if stderr else ""),
            "cost_usd": 0.0,
            "duration_s": duration,
        }

    if proc.returncode != 0:
        return {
            "ok": False,
            "final_message": (
                f"daemon error: claude -p exited {proc.returncode}. "
                + (f"stderr: {stderr[:400]}" if stderr else "")
            ),
            "transcript": stdout + ("\n" + stderr if stderr else ""),
            "cost_usd": 0.0,
            "duration_s": duration,
        }

    final_message, cost_usd = parse_claude_output(stdout)

    return {
        "ok": True,
        "final_message": final_message,
        "transcript": stdout,
        "cost_usd": cost_usd,
        "duration_s": duration,
    }
