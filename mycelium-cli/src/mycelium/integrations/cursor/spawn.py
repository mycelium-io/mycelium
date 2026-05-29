# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor cold-spawn — invokes ``cursor-agent -p`` for one ``@handle`` mention.

Parallels :mod:`mycelium.integrations.claude_code.spawn` but with two notable
differences driven by the cursor-agent CLI:

1. **No system-prompt flag.** ``cursor-agent --help`` exposes
   ``-p/--print``, ``--output-format``, ``--workspace``, ``--trust``,
   ``--force``, ``--approve-mcps`` and the positional ``prompt`` — but no
   ``--append-system-prompt`` / ``--system-prompt`` equivalent. So the
   identity preamble (built by :func:`mycelium.daemon.preamble.identity_preamble`
   and used verbatim by claude_code) is **prepended to the positional
   prompt** with a ``---`` separator. The result is a single string the
   model reads top-to-bottom: identity / persona block, then the user's
   mention.

2. **No per-call cost exposed.** Cursor's JSON output reports
   ``usage`` (token counts) but no ``total_cost_usd``. The daemon's
   in-memory budget tracker (``state.budget_used_usd``) therefore receives
   ``0.0`` per cursor invocation. The bundled docs call this out and
   recommend a pre-paid plan or external monitoring; future work can
   apply per-model pricing tables to the token counts. The raw
   ``usage`` is preserved on :attr:`SpawnResult.extra` so log analysers
   can opt in.

Authentication is **not pre-flight checked** here — same posture as
claude_code (where ``claude`` is assumed authenticated). If
``cursor-agent`` returns an "Authentication required" error in stderr, we
surface a friendlier ``daemon error`` reply pointing at ``cursor-agent
login`` (run interactively once, the credential is then available to the
non-login-shell daemon process). See ``docs/cursor-adapter.md`` (auth-doc
milestone) for the operator-facing setup steps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from mycelium.daemon.preamble import identity_preamble
from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult

log = logging.getLogger("mycelium.daemon")


#: Separator the cold-start agent sees between the identity preamble and the
#: user's actual mention prompt. Three dashes is the conventional Markdown
#: horizontal rule — cursor-agent has no system-prompt flag (verified
#: against ``cursor-agent --help``), so the entire instruction lives in the
#: positional argument and this separator is the only thing telling the
#: model where the persona block ends.
_PREAMBLE_SEPARATOR = "\n\n---\n\n"


def _detect_auth_required(stderr: str) -> bool:
    """Return True iff *stderr* looks like a ``cursor-agent`` auth failure.

    cursor-agent prints variants of "Authentication required" / "Not logged
    in" when no credential is available. The daemon runs without a login
    shell, so this happens iff the operator never ran ``cursor-agent
    login`` interactively (or the stored credential expired). The check is
    intentionally substring-based and case-insensitive — cursor-agent's
    exact phrasing has changed at least once between releases, and we'd
    rather over-detect a borderline message than silently surface the raw
    crash to the user. False positives just yield a friendlier message;
    the real error text is still preserved in ``SpawnResult.transcript``.
    """
    s = stderr.lower()
    return any(
        marker in s
        for marker in (
            "authentication required",
            "not authenticated",
            "not logged in",
            "please log in",
            "please run `cursor-agent login`",
        )
    )


def parse_cursor_output(stdout: str) -> tuple[str, dict[str, Any]]:
    """Pull ``(final_message, extras)`` out of ``cursor-agent -p --output-format json``.

    Unlike claude (which returns an array of stream events with a terminal
    ``type=="result"`` entry), cursor returns a single dict with the
    answer in ``"result"`` and a ``"usage"`` sub-object holding token
    counts. ``"is_error": true`` marks failures. ``extras`` carries every
    field other than ``"result"`` itself so log analysers can replay
    session_id, request_id, duration_ms, usage, subtype verbatim.

    Falls back to returning ``stdout`` as the final message and an empty
    ``extras`` dict when the output isn't valid JSON — graceful degradation
    if a future cursor build changes its print format.
    """
    try:
        parsed: Any = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, {}

    if not isinstance(parsed, dict):
        return stdout, {}

    # Defensive: cast to dict[str, Any] for downstream pop/get.
    obj: dict[str, Any] = dict(parsed)
    result = obj.pop("result", None)
    if not isinstance(result, str) or not result:
        # Cursor occasionally returns ``result: null`` on a refused or
        # empty turn — preserve everything in extras and fall back to the
        # raw stdout so the user sees something.
        return stdout, obj
    return result, obj


async def spawn_cursor(*, request: SpawnRequest) -> SpawnResult:
    """Run ``cursor-agent -p`` once for one ``@handle`` mention.

    The signature is the family-agnostic
    :class:`mycelium.integrations._spawn_common.SpawnRequest`; the return
    is the matching :class:`SpawnResult`. The daemon dispatch loop has
    no cursor-specific code paths — it calls ``CursorIntegration.spawn()``
    which delegates here.

    ``RunningProc`` registration lives in this function (same pattern as
    ``spawn_claude``) because the subprocess handle is family-internal.
    The daemon dispatch loop owns the per-handle serial lock; this
    function owns "let an abort verb SIGTERM me mid-flight".

    A wall-clock timeout (``DaemonConfig.spawn_timeout_s``, default 10 min)
    bounds how long a single invocation may hold the per-handle lock. If
    exceeded, the process is SIGTERMed (then SIGKILLed after a grace
    period) and the result reports a timeout. Without this guard, a hung
    ``cursor-agent`` blocks all future dispatches for that handle
    indefinitely.
    """
    from mycelium.daemon.config import DaemonConfig
    from mycelium.daemon.state import RunningProc

    binary = request.binary or "cursor-agent"

    if shutil.which(binary) is None:
        return SpawnResult(
            ok=False,
            final_message=(
                f"daemon error: `{binary}` not found on PATH. "
                "Install Cursor CLI (https://cursor.com/cli) or set "
                "`cursor_binary` in cc-daemon.toml."
            ),
            transcript="",
        )

    expanded_cwd = os.path.expanduser(request.cwd)
    if not Path(expanded_cwd).is_dir():
        return SpawnResult(
            ok=False,
            final_message=f"daemon error: cwd '{request.cwd}' is not a directory.",
            transcript="",
        )

    # Build the combined prompt: identity preamble + ---separator+ user mention.
    # cursor-agent has no system-prompt flag, so the preamble has to ride in
    # the positional prompt argument. The separator is the only signal to
    # the model that the persona block has ended.
    preamble = identity_preamble(
        handle=request.handle,
        room=request.room or "(unknown)",
        description=request.description or "",
        sender=request.sender or "(anonymous)",
        notes=request.notes,
        plan_block=request.plan_block,
    )
    combined_prompt = preamble + _PREAMBLE_SEPARATOR + request.prompt

    cmd = [
        binary,
        "-p",
        "--output-format",
        "json",
        # ``--workspace`` is the cursor-side anchor for file edits; we set
        # both this AND subprocess ``cwd=`` so shell commands the agent
        # runs and cursor's own file ops both resolve to the manifest's
        # working dir.
        "--workspace",
        expanded_cwd,
        # Headless prerequisites: trust without a TUI prompt; allow shell
        # commands so the agent can run mycelium CLI; auto-approve MCP
        # servers (each mention is a fresh process, so the user can't
        # confirm interactively).
        "--trust",
        "--force",
        "--approve-mcps",
        combined_prompt,
    ]

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=expanded_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return SpawnResult(
            ok=False,
            final_message=f"daemon error: spawn failed ({exc})",
            transcript="",
            duration_s=time.monotonic() - started,
        )

    # Same RunningProc pattern as spawn_claude: a sibling ``@handle abort``
    # message SIGTERMs us. Cleared in finally so the next dispatch sees an
    # empty slot. Mirrors claude_code's behaviour exactly so abort/status
    # are identical UX across both families.
    if request.state is not None and request.handle:
        request.state.running[request.handle] = RunningProc(
            process=proc,
            started_at=started,
            prompt=request.prompt,
            sender=request.sender or "",
            room=request.room or "",
        )

    timeout_s = DaemonConfig.load().spawn_timeout_s
    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        timed_out = True
        log.warning(
            "cursor-agent @%s exceeded spawn timeout (%.0fs) — killing",
            request.handle,
            timeout_s,
        )
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        # Grace period for clean shutdown before SIGKILL.
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()
    finally:
        if request.state is not None and request.handle:
            request.state.running.pop(request.handle, None)

    duration = time.monotonic() - started
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    transcript = stdout + ("\n" + stderr if stderr else "")

    if timed_out:
        return SpawnResult(
            ok=False,
            final_message=(
                f"daemon error: cursor-agent timed out after {int(timeout_s)}s — "
                "the invocation was killed. If this recurs, consider splitting the "
                "task or raising `spawn_timeout_s` in cc-daemon.toml."
            ),
            transcript=transcript,
            duration_s=duration,
        )

    # Negative return code → terminated by signal (SIGTERM from abort verb).
    if proc.returncode is not None and proc.returncode < 0:
        return SpawnResult(
            ok=False,
            aborted=True,
            final_message="",  # caller writes the human-facing abort message
            transcript=transcript,
            duration_s=duration,
        )

    if proc.returncode != 0:
        # Friendlier message for the auth case — the operator hit this
        # because cursor-agent has never been logged in on this host
        # under the daemon's user. Same posture as claude_code: we don't
        # pre-flight check, we surface the friendly hint when the real
        # error fires.
        if _detect_auth_required(stderr):
            log.warning("cursor auth required for @%s — see `cursor-agent login`", request.handle)
            final = (
                "daemon error: `cursor-agent` is not authenticated. "
                "Run `cursor-agent login` once interactively under the user "
                "the cc-daemon runs as, then re-invoke."
            )
        else:
            final = f"daemon error: cursor-agent exited {proc.returncode}. " + (
                f"stderr: {stderr[:400]}" if stderr else ""
            )
        return SpawnResult(
            ok=False,
            final_message=final,
            transcript=transcript,
            duration_s=duration,
        )

    final_message, extras = parse_cursor_output(stdout)
    is_error = bool(extras.get("is_error"))

    return SpawnResult(
        ok=not is_error,
        final_message=final_message,
        transcript=transcript,
        # Cursor doesn't surface per-call $ cost; tokens-to-cost mapping is
        # model-specific and lives outside this module. Keep cost_usd=0.0
        # so the daemon's budget tracker doesn't accumulate garbage. The
        # ``usage`` block is preserved on .extra below for downstream.
        cost_usd=0.0,
        duration_s=duration,
        extra=extras,
    )
