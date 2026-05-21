# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""SSE subscription + @handle dispatch — the heart of the daemon."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import ValidationError

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.mentions import resolve_mentions
from mycelium.daemon.state import DaemonState, RunningProc
from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.protocol import AgentManifest

log = logging.getLogger("mycelium.daemon")

_DEPTH_WINDOW_S = 60.0

# The backend SSE endpoint emits a `: keep-alive` comment every ~15s when a
# room is idle (see fastapi-backend/app/routes/stream.py). So a healthy
# stream is never silent longer than that. Bounding the read timeout at ~3×
# that interval means a half-open / stalled connection (peer or NAT/LB
# dropped it without a FIN — `aiter_text()` would otherwise block forever
# while the daemon still reports the room "connected") raises
# httpx.ReadTimeout within ~45s and we reconnect, instead of going silently
# deaf. Connect is bounded too so an unreachable hub fails fast.
_SSE_KEEPALIVE_S = 15.0
_SSE_READ_TIMEOUT_S = 45.0
_SSE_CONNECT_TIMEOUT_S = 10.0


def _identity_preamble(
    *,
    handle: str,
    room: str,
    description: str,
    sender: str,
    notes: str,
    plan_block: str = "",
) -> str:
    """System-prompt preamble injected into every claude -p spawn.

    Without this, the spawned Claude has no idea it's an addressed agent —
    it tries to explain that it's "actually Claude," asks the user if they
    meant to route somewhere else, etc. (Mirrors how OpenClaw injects
    identity via MYCELIUM_AGENT_HANDLE + before_agent_start; cold-start
    Claude Code has no env channel for that, so we bake it into the prompt.)
    """
    desc_block = f"\n## Your scope\n\n{description.strip()}\n" if description.strip() else ""
    notes_block = (
        f"\n## Your persistent notes\n\n{notes.strip()}\n"
        if notes.strip()
        else "\n## Your persistent notes\n\n(none yet — `mycelium memory get agents/"
        f"{handle}/notes` shows them when they exist)\n"
    )
    return f"""\
# You are @{handle} — a Mycelium-hosted agent

You are operating as the agent **@{handle}** inside the Mycelium room
**{room}**. Another participant ({sender}) just @-mentioned you with the
prompt below. Your reply will be posted to that room *as @{handle}*, so:

- Respond in first person as @{handle}.
- Do NOT explain that you're "actually Claude," ask whether the user
  meant the chat box, or offer to route them elsewhere — you ARE the
  routing destination.
- Do NOT prefix your reply with `@{handle}:` or quote the original
  message back — just answer.
- Keep replies tight. The room is a chat surface; long monologues
  belong in `decisions/` or `work/` memory entries, not the chat.
- You're cold-started: every invocation is fresh. Anything that should
  persist between runs goes in your notes (`mycelium memory set
  agents/{handle}/notes "..."` from your cwd).
{desc_block}{notes_block}{plan_block}
## Control verbs

If the prompt is exactly one of `abort`, `cancel`, `stop`, or `status`,
the daemon handles it before you see it — you'll never receive those.
"""


# Reserved verbs at the start of an addressed message body. Anything not in
# this set goes through to claude -p as a normal prompt.
_CONTROL_ABORT = {"abort", "cancel", "stop"}
_CONTROL_STATUS = {"status"}


def _extract_body(content: str, handle: str) -> str:
    """Return the message body with the leading ``@handle`` mention stripped."""
    lower = content.lower()
    needle = f"@{handle.lower()}"
    idx = lower.find(needle)
    if idx == -1:
        return content.strip()
    return content[idx + len(needle) :].strip()


def _leading_verb(body: str) -> str | None:
    """Return the first whitespace-delimited token, lowercased, or None."""
    if not body:
        return None
    return body.split(None, 1)[0].lower()


# ── Manifest lookup (filesystem only — daemon is single-machine v0) ──────────


def list_agent_handles(room_name: str) -> list[str]:
    """List handles registered in *room_name* by scanning the local filesystem."""
    room_dir = get_room_dir(room_name)
    entries = list_memories(room_dir, prefix="agents/", limit=500)
    handles: list[str] = []
    for key, _meta, _content in entries:
        rest = key.removeprefix("agents/")
        if "/" in rest:
            continue
        handles.append(rest)
    return handles


def load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError:
        return None


def load_notes(room_name: str, handle: str) -> str:
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}/notes")
    if result is None:
        return ""
    _, content = result
    return content


# ── Agent-context (room plan) injection ──────────────────────────────────────
# GET /api/rooms/{room}/agent-context is read on every dispatch, so it's cached
# per-room. The staleness line baked into the rendered block tells the agent
# how old the snapshot is, so a cache hit is still honest.
_AGENT_CONTEXT_TTL_S = 60.0
# room -> (fetched_monotonic, context_or_none, generated_at_iso)
_agent_context_cache: dict[str, tuple[float, str | None, str]] = {}


async def _fetch_agent_context(api_url: str, room_name: str, handle: str) -> tuple[str | None, str]:
    """Return ``(context, generated_at_iso)`` for a room, cached for the TTL.

    Best-effort: a fetch failure never blocks a dispatch. On error a stale
    cache entry is reused if present, else ``(None, "")`` (block omitted).
    """
    now = time.monotonic()
    cached = _agent_context_cache.get(room_name)
    if cached is not None and now - cached[0] < _AGENT_CONTEXT_TTL_S:
        return cached[1], cached[2]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{api_url}/api/rooms/{room_name}/agent-context",
                params={"handle": handle},
            )
            resp.raise_for_status()
            data = resp.json()
        entry = (now, data.get("context"), data.get("generated_at") or "")
        _agent_context_cache[room_name] = entry
        return entry[1], entry[2]
    except Exception as exc:
        log.debug("agent-context fetch failed for %s: %s", room_name, exc)
        if cached is not None:
            return cached[1], cached[2]
        return None, ""


def _humanize_age(generated_at_iso: str) -> str:
    """Render ' (as of HH:MM UTC, ~N min ago)' from an ISO-8601 timestamp."""
    if not generated_at_iso:
        return ""
    try:
        ts = datetime.fromisoformat(generated_at_iso)
    except ValueError:
        return ""
    age_s = max(0.0, (datetime.now(UTC) - ts).total_seconds())
    mins = int(age_s // 60)
    when = ts.strftime("%H:%M UTC")
    if mins < 1:
        return f" (as of {when}, just now)"
    return f" (as of {when}, ~{mins} min ago)"


def _render_plan_block(context: str | None, generated_at_iso: str) -> str:
    """Format the agent-context string into a system-prompt section.

    Returns '' when the room has no plan — callers omit the section entirely.
    """
    if not context:
        return ""
    return (
        f"\n## Room plan{_humanize_age(generated_at_iso)}\n\n{context}\n\n"
        "This snapshot may be stale — run `mycelium plan tasks` for live state.\n"
    )


# ── Gating: allow_from, budget, depth ────────────────────────────────────────


def _normalize_sender(sender_handle: str) -> str:
    return sender_handle.lstrip("@").lower()


def gate_allow_from(manifest: AgentManifest, sender_handle: str) -> bool:
    if not manifest.allow_from:
        return True
    sender = _normalize_sender(sender_handle)
    return any(_normalize_sender(a) == sender for a in manifest.allow_from)


def gate_budget(state: DaemonState, manifest: AgentManifest) -> bool:
    if manifest.budget_usd_per_month <= 0:
        return True
    ym = datetime.now(UTC).strftime("%Y-%m")
    used = state.budget_used_usd.get((manifest.handle, ym), 0.0)
    return used < manifest.budget_usd_per_month


def gate_depth(state: DaemonState, sender_handle: str, depth_cap: int) -> bool:
    """Refuse if *sender_handle* has triggered more than ``depth_cap`` dispatches
    in the trailing 60s window. Approximates a chain-depth cap without needing
    per-message origin chains on the backend."""
    sender = _normalize_sender(sender_handle)
    bucket = state.recent_dispatches[sender]
    now = time.monotonic()
    while bucket and now - bucket[0] > _DEPTH_WINDOW_S:
        bucket.popleft()
    return len(bucket) < depth_cap


# ── claude -p spawn ──────────────────────────────────────────────────────────


def _parse_claude_output(stdout: str) -> tuple[str, float]:
    """Pull (final_message, cost_usd) out of `claude -p --output-format json`.

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
        preamble = _identity_preamble(
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
    # in finally so the next dispatch sees an empty slot.
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

    final_message, cost_usd = _parse_claude_output(stdout)

    return {
        "ok": True,
        "final_message": final_message,
        "transcript": stdout,
        "cost_usd": cost_usd,
        "duration_s": duration,
    }


# ── Side effects: log to memory + reply to room ──────────────────────────────


async def _post_log(
    config: MyceliumConfig,  # noqa: ARG001 — signature kept for symmetry
    room_name: str,
    manifest: AgentManifest,
    *,
    prompt: str,
    sender_handle: str,
    result: dict[str, Any],
) -> None:
    """Write the invocation transcript to a daemon-private log directory.

    Logs live OUTSIDE the room's memory namespace (``~/.mycelium/cc-daemon/
    logs/<room>/<handle>/<ts>.json``) so they don't flood the semantic
    index, `memory ls` output, or synthesis runs. `mycelium agent show`
    reads from here. Logs are local-only — they don't sync via git or the
    backend.
    """
    from mycelium.daemon.config import daemon_invocation_log_dir

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    body = {
        "ts": timestamp,
        "room": room_name,
        "handle": manifest.handle,
        "prompt": prompt,
        "sender": sender_handle,
        "ok": result["ok"],
        "duration_s": round(result["duration_s"], 2),
        "cost_usd": round(result["cost_usd"], 4),
        "final_message": result.get("final_message", ""),
        "transcript": result["transcript"][:16_000],
    }

    def _do() -> None:
        log_dir = daemon_invocation_log_dir(room_name, manifest.handle)
        path = log_dir / f"{timestamp}.json"
        path.write_text(json.dumps(body, indent=2, default=str))

    await asyncio.to_thread(_do)


async def _post_reply(
    config: MyceliumConfig,
    room_name: str,
    manifest: AgentManifest,
    *,
    reply: str,
) -> None:
    """Post the agent's reply back to the originating room as @handle."""
    from mycelium_backend_client import Client
    from mycelium_backend_client.api.messages import (
        send_message_api_rooms_room_name_messages_post as send_api,
    )
    from mycelium_backend_client.models import MessageCreate

    def _do() -> None:
        with Client(base_url=config.server.api_url, raise_on_unexpected_status=True) as client:
            body = MessageCreate(
                sender_handle=manifest.handle,
                message_type="broadcast",
                content=reply,
            )
            send_api.sync(room_name=room_name, client=client, body=body)

    await asyncio.to_thread(_do)


# ── Per-message dispatch ─────────────────────────────────────────────────────


async def on_message(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    msg: dict[str, Any],
) -> None:
    """Inspect *msg* and dispatch if it @-mentions an agent we host."""
    msg_id = str(msg.get("id") or "")
    if msg_id:
        if msg_id in state.seen_message_ids:
            return
        state.seen_message_ids.append(msg_id)

    content = str(msg.get("content") or "")
    sender_handle = str(msg.get("sender_handle") or "")
    if not content:
        return

    handles = list_agent_handles(room_name)
    if not handles:
        return

    mentioned = resolve_mentions(content, handles)
    if not mentioned:
        return

    # Skip self-mentions to avoid trivial loops.
    sender_norm = _normalize_sender(sender_handle)
    mentioned = [h for h in mentioned if _normalize_sender(h) != sender_norm]
    if not mentioned:
        return

    for handle in mentioned:
        manifest = load_manifest(room_name, handle)
        if manifest is None:
            log.warning("no manifest for @%s in %s", handle, room_name)
            continue
        if manifest.adapter != "claude_code":
            continue  # another adapter's gateway owns this handle

        if not gate_allow_from(manifest, sender_handle):
            log.info("denied @%s ← %s (allow_from)", handle, sender_handle)
            continue

        # Control verbs run OUTSIDE the per-handle lock so they can act on a
        # running spawn (abort) or answer instantly while one is in flight
        # (status). They're also exempt from budget + depth caps — they
        # don't spend money and don't kick the chain forward.
        body = _extract_body(content, handle)
        verb = _leading_verb(body)
        if verb in _CONTROL_ABORT:
            asyncio.create_task(
                _handle_abort(
                    config=config,
                    state=state,
                    room_name=room_name,
                    manifest=manifest,
                    sender_handle=sender_handle,
                )
            )
            continue
        if verb in _CONTROL_STATUS:
            asyncio.create_task(
                _handle_status(
                    config=config,
                    state=state,
                    room_name=room_name,
                    manifest=manifest,
                )
            )
            continue

        if not gate_budget(state, manifest):
            log.warning("denied @%s (budget exceeded)", handle)
            continue
        if not gate_depth(state, sender_handle, daemon_cfg.depth_cap):
            log.warning(
                "denied @%s ← %s (depth cap %d in 60s)",
                handle,
                sender_handle,
                daemon_cfg.depth_cap,
            )
            continue

        asyncio.create_task(
            _dispatch_one(
                config=config,
                daemon_cfg=daemon_cfg,
                state=state,
                room_name=room_name,
                manifest=manifest,
                sender_handle=sender_handle,
                prompt=content,
            )
        )


# ── Control verbs ────────────────────────────────────────────────────────────


async def _handle_abort(
    *,
    config: MyceliumConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
    sender_handle: str,
) -> None:
    """`@handle abort|cancel|stop` — SIGTERM the agent's running spawn."""
    running = state.running.get(manifest.handle)
    if running is None:
        await _post_reply(
            config,
            room_name,
            manifest,
            reply=f"○ nothing to abort (no run in flight) — {sender_handle}",
        )
        return
    try:
        running.process.terminate()
    except ProcessLookupError:
        pass
    log.info(
        "abort @%s ← %s (running %.1fs)",
        manifest.handle,
        sender_handle,
        time.monotonic() - running.started_at,
    )
    await _post_reply(
        config,
        room_name,
        manifest,
        reply=f"✗ aborted by {sender_handle}",
    )


async def _handle_status(
    *,
    config: MyceliumConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
) -> None:
    """`@handle status` — describe the agent's current state."""
    running = state.running.get(manifest.handle)
    if running is not None:
        elapsed = time.monotonic() - running.started_at
        reply = (
            f"● running for {elapsed:.0f}s (prompt: {running.prompt[:80]!r}, from {running.sender})"
        )
    else:
        last = state.last_dispatch or {}
        if last.get("agent") == manifest.handle:
            reply = (
                f"○ idle · last run: {last.get('result')} in "
                f"{last.get('duration_s', 0):.1f}s (cost ${last.get('cost_usd', 0):.4f})"
            )
        else:
            reply = "○ idle · no recent runs"
    await _post_reply(config, room_name, manifest, reply=reply)


async def _dispatch_one(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
    manifest: AgentManifest,
    sender_handle: str,
    prompt: str,
) -> None:
    """Run a single dispatch under the per-handle serial lock."""
    lock = state.lock_for(manifest.handle)
    async with lock:
        state.recent_dispatches[_normalize_sender(sender_handle)].append(time.monotonic())

        notes = load_notes(room_name, manifest.handle)
        log.info(
            "dispatch @%s ← %s (room=%s, cmd=%s)",
            manifest.handle,
            sender_handle,
            room_name,
            shlex.quote(prompt[:60]),
        )

        body = _extract_body(prompt, manifest.handle) or prompt
        # Room plan briefing — best-effort, cached per-room. The agent sees
        # the room's title + open tasks so its reply is plan-aware.
        ctx, generated_at = await _fetch_agent_context(
            config.server.api_url, room_name, manifest.handle
        )
        result = await spawn_claude(
            claude_binary=daemon_cfg.claude_binary,
            # cc-daemon only dispatches claude_code manifests, which the
            # AgentManifest validator guarantees have a cwd. The `or ""`
            # is a type-safe floor — an empty cwd makes spawn_claude return
            # its clean "cwd is not a directory" error rather than crash.
            cwd=manifest.cwd or "",
            prompt=body,
            notes=notes,
            state=state,
            handle=manifest.handle,
            sender=sender_handle,
            room=room_name,
            description=manifest.description,
            plan_block=_render_plan_block(ctx, generated_at),
        )

        if result.get("aborted"):
            # Aborted via control verb — the abort handler already posted its
            # own reply, so we just log here and skip the normal log+reply
            # pair. Falling through would post the empty final_message.
            log.info("abort acknowledged for @%s", manifest.handle)
            state.record_dispatch(
                handle=manifest.handle,
                room=room_name,
                result="aborted",
                duration_s=result["duration_s"],
                cost_usd=0.0,
            )
            return

        # Track spend in-memory (per-process, per calendar month).
        ym = datetime.now(UTC).strftime("%Y-%m")
        state.budget_used_usd[(manifest.handle, ym)] = (
            state.budget_used_usd.get((manifest.handle, ym), 0.0) + result["cost_usd"]
        )
        state.record_dispatch(
            handle=manifest.handle,
            room=room_name,
            result="ok" if result["ok"] else "error",
            duration_s=result["duration_s"],
            cost_usd=result["cost_usd"],
        )

        try:
            await _post_log(
                config,
                room_name,
                manifest,
                prompt=prompt,
                sender_handle=sender_handle,
                result=result,
            )
        except Exception as exc:
            state.record_error("post_log", exc)
            log.warning("could not write log entry for @%s: %s", manifest.handle, exc)

        try:
            await _post_reply(config, room_name, manifest, reply=result["final_message"])
        except Exception as exc:
            state.record_error("post_reply", exc)
            log.warning("could not post reply for @%s: %s", manifest.handle, exc)


# ── SSE subscription per room ────────────────────────────────────────────────


async def subscribe_room(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room_name: str,
) -> None:
    """Stay connected to *room_name*'s SSE stream until the daemon stops."""
    url = f"{config.server.api_url}/api/rooms/{room_name}/messages/stream"

    # No total timeout (the stream is long-lived) but a bounded read timeout
    # so a stalled connection is detected via httpx.ReadTimeout rather than
    # hanging aiter_text() forever. write/pool bounded too; defensive.
    timeout = httpx.Timeout(
        None,
        connect=_SSE_CONNECT_TIMEOUT_S,
        read=_SSE_READ_TIMEOUT_S,
        write=_SSE_CONNECT_TIMEOUT_S,
        pool=_SSE_CONNECT_TIMEOUT_S,
    )

    while not state.stopping.is_set():
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp,
            ):
                if resp.status_code == 404:
                    log.warning(
                        "SSE 404 for %s — room may not exist; retry in 15s",
                        room_name,
                    )
                    await asyncio.sleep(15)
                    continue
                if resp.status_code >= 400:
                    log.warning("SSE %s for %s — retry in 5s", resp.status_code, room_name)
                    await asyncio.sleep(5)
                    continue

                log.info("SSE connected: %s", room_name)
                state.rooms_connected.add(room_name)

                buffer = ""
                async for chunk in resp.aiter_text():
                    if state.stopping.is_set():
                        break
                    buffer += chunk
                    blocks = buffer.split("\n\n")
                    buffer = blocks.pop()
                    for block in blocks:
                        for line in block.split("\n"):
                            if not line.startswith("data: "):
                                continue
                            raw = line[6:].strip()
                            if not raw or raw == "{}":
                                continue
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            try:
                                await on_message(
                                    config=config,
                                    daemon_cfg=daemon_cfg,
                                    state=state,
                                    room_name=room_name,
                                    msg=msg,
                                )
                            except Exception as exc:
                                state.record_error(f"on_message[{room_name}]", exc)
                                log.exception("dispatch error in %s: %s", room_name, exc)
        except asyncio.CancelledError:
            raise
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            # A stalled/half-open stream: no keep-alive for _SSE_READ_TIMEOUT_S
            # (or the hub didn't accept the connection in time). Distinct log
            # so operators can tell a deaf socket from a network error.
            state.record_error(f"sse_stalled[{room_name}]", exc)
            log.warning(
                "SSE stalled for %s (no data within %.0fs) — reconnecting in 5s",
                room_name,
                _SSE_READ_TIMEOUT_S,
            )
        except Exception as exc:
            state.record_error(f"sse[{room_name}]", exc)
            log.warning("SSE error for %s: %s — retry in 5s", room_name, exc)
        finally:
            state.rooms_connected.discard(room_name)

        if state.stopping.is_set():
            return
        await asyncio.sleep(5)
