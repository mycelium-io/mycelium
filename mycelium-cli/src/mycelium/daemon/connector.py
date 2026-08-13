# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The daemon's waker — a background consumer of the member-session core.

Membership (holding the SLIM subscription, keepalive, receiving addressed
messages, publishing replies, memory sync) lives in
:mod:`mycelium.slim.member`; this module is the one thing that is genuinely about
*waking*: on an inbound L9 message addressed to an owned handle, it cold-spawns a
``claude -p`` turn and publishes the turn's reply back onto the channel as an L9
``exchange``.

:func:`run_connector` runs a :class:`~mycelium.slim.member.MemberSession` in the
background and, for each addressed message it yields, applies the daemon-only
concerns — ownership, ``allow_from``/budget/depth gates, the per-handle serial
lock, control verbs, cold-spawn (from :mod:`mycelium.daemon.dispatch`). An
already-awake caller skips all of this and participates through the foreground
``await`` / ``respond`` commands, which sit on the same core. The agent's contract
is unchanged: it never speaks SLIM or L9.

The pure membership helpers are re-exported here under their historical names so
callers (and tests) that reach for ``connector.should_wake`` etc. keep working —
the single implementation lives in the core.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx  # re-exported for tests that monkeypatch ``connector.httpx``  # noqa: F401

from mycelium.daemon.dispatch import (
    _CONTROL_ABORT,
    _CONTROL_STATUS,
    _extract_body,
    _fetch_agent_context,
    _leading_verb,
    _post_log,
    _render_plan_block,
    gate_allow_from,
    gate_budget,
    gate_depth,
    list_agent_handles,
    load_manifest,
    load_notes,
)
from mycelium.integrations import get_integration
from mycelium.integrations._spawn_common import SpawnRequest
from mycelium.slim import l9

# Re-exported for import compatibility so callers/tests that import these
# membership helpers from ``connector`` keep working; the single implementation
# lives in ``mycelium.slim.member``.
from mycelium.slim.member import (  # noqa: F401
    KEEPALIVE_TYPE as _KEEPALIVE_TYPE,
)
from mycelium.slim.member import (
    MemberSession,
    PublishFn,
    announce_presence,
    apply_knowledge_message,
    build_reply,
    normalize_handle,
    parse_position_marker,
    reindex_after_knowledge,
    should_wake,
)
from mycelium.slim.member import (  # noqa: F401
    keepalive_loop as _keepalive_loop,
)
from mycelium.slim.member import (  # noqa: F401
    room_episode as _room_episode,
)
from mycelium.slim.member import (  # noqa: F401
    room_topic as _room_topic,
)
from mycelium.slim.naming import DEFAULT_WORKSPACE

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.daemon.config import DaemonConfig
    from mycelium.daemon.state import DaemonState
    from mycelium.protocol import AgentManifest

log = logging.getLogger("mycelium.daemon")

# Kept as a module alias so ``connector.should_wake``-style call sites (and the
# gate below) fold handles the same way the core does.
_normalize_sender = normalize_handle

__all__ = [
    "MemberSession",
    "announce_presence",
    "apply_knowledge_message",
    "build_reply",
    "connector_targets",
    "handle_inbound",
    "parse_position_marker",
    "reindex_after_knowledge",
    "run_connector",
    "should_wake",
]


# ── Connector target discovery ───────────────────────────────────────────────


def connector_targets(
    daemon_cfg: DaemonConfig, *, engine_runtime: str = "backend"
) -> list[tuple[str, str]]:
    """The ``(room, handle)`` pairs this daemon should hold a connector for.

    A handle qualifies when it is (a) registered in the room's local mirror,
    (b) owned by this daemon (``daemon.toml`` handles), and (c) a **cold_spawn**
    family (claude_code / cursor) — or a first-party **engine** when
    ``engine_runtime == "host"`` (the daemon holds the engine's connector and
    drives NEGMAS on the host instead of the backend running it).
    ``long_lived_gateway`` families own their own delivery and
    are skipped, exactly as the old SSE dispatch skipped them.
    """
    targets: list[tuple[str, str]] = []
    for room in daemon_cfg.rooms:
        for handle in list_agent_handles(room):
            if handle not in daemon_cfg.handles:
                continue
            manifest = load_manifest(room, handle)
            if manifest is None:
                continue
            try:
                integration = get_integration(manifest.adapter)
            except ValueError:
                log.warning(
                    "unknown adapter %r on @%s in %s — skipping", manifest.adapter, handle, room
                )
                continue
            is_host_engine = integration.lifecycle == "backend_engine" and engine_runtime == "host"
            if integration.lifecycle == "cold_spawn" or is_host_engine:
                targets.append((room, handle))
    return targets


# ── Per-message dispatch (the waking half) ───────────────────────────────────


async def handle_inbound(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room: str,
    handle: str,
    content: dict,
    publish: PublishFn,
) -> None:
    """Wake ``handle`` for an inbound message and publish its reply.

    The live daemon path never hands a ``knowledge`` message here (the core
    applies + swallows it as memory sync). The branch below stays so a direct
    caller can route one, and so the two behave identically: both delegate to the
    same :func:`apply_knowledge_message` / :func:`reindex_after_knowledge`.
    """
    if l9.kind_of(content) == l9.KNOWLEDGE_KIND:
        result = apply_knowledge_message(room, content)
        if result is not None and result.applied and config is not None:
            await reindex_after_knowledge(config, room)
        return

    if not should_wake(content, handle):
        return

    manifest = load_manifest(room, handle)
    if manifest is None:
        log.warning("woke @%s in %s but no manifest in local mirror — skipping", handle, room)
        return

    # Host-run engine: an ``@``-summon of a first-party engine runs the NEGMAS
    # drive over *this* connector's session rather than cold-spawning a
    # subprocess. The drive registers a queue on the daemon state; the receive
    # loop then routes agent replies into it. Skips the cold-spawn gates/verbs
    # below — an engine drive is one long-lived turn, not a spawn.
    if manifest.adapter == "engine":
        from mycelium.integrations.engine.host import dispatch_engine

        await dispatch_engine(
            config=config,
            state=state,
            room=room,
            handle=handle,
            kind=manifest.kind,
            publish=publish,
        )
        return

    sender_handle = l9.sender_of(content) or "(anonymous)"
    body = _extract_body(l9.human_text_of(content), handle)
    verb = _leading_verb(body)

    # Control verbs run OUTSIDE the per-handle lock (act on a running spawn /
    # answer instantly) and skip the budget + depth caps — they don't spend or
    # advance a chain.
    if verb in _CONTROL_ABORT:
        await _handle_abort(state, room, handle, sender_handle, content, publish)
        return
    if verb in _CONTROL_STATUS:
        await _handle_status(state, room, handle, content, publish)
        return

    if not gate_allow_from(manifest, sender_handle):
        log.info("denied @%s ← %s (allow_from)", handle, sender_handle)
        return
    if not gate_budget(state, manifest):
        log.warning("denied @%s (budget exceeded)", handle)
        return
    if not gate_depth(state, sender_handle, daemon_cfg.depth_cap):
        log.warning(
            "denied @%s ← %s (depth cap %d in 60s)", handle, sender_handle, daemon_cfg.depth_cap
        )
        return

    await _dispatch_one(
        config=config,
        daemon_cfg=daemon_cfg,
        state=state,
        room=room,
        manifest=manifest,
        sender_handle=sender_handle,
        woke=content,
        publish=publish,
    )


async def _dispatch_one(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room: str,
    manifest: AgentManifest,
    sender_handle: str,
    woke: dict,
    publish: PublishFn,
) -> None:
    """Cold-spawn a turn under the per-handle serial lock; publish the reply."""
    lock = state.lock_for(manifest.handle)
    async with lock:
        state.recent_dispatches[_normalize_sender(sender_handle)].append(time.monotonic())
        notes = load_notes(room, manifest.handle)
        prompt = l9.human_text_of(woke)
        body = _extract_body(prompt, manifest.handle) or prompt
        log.info("wake @%s ← %s (room=%s)", manifest.handle, sender_handle, room)

        ctx, generated_at = await _fetch_agent_context(config.server.api_url, room, manifest.handle)
        integration = get_integration(manifest.adapter)
        request = SpawnRequest(
            handle=manifest.handle,
            room=room,
            cwd=manifest.cwd or "",
            prompt=body,
            description=manifest.description,
            sender=sender_handle,
            notes=notes,
            plan_block=_render_plan_block(ctx, generated_at),
            binary=daemon_cfg.binary_for(manifest.adapter),
            state=state,
        )
        result = await integration.spawn(request=request)

        if result.aborted:
            # The abort verb already published its own reply; just record it.
            log.info("abort acknowledged for @%s", manifest.handle)
            state.record_dispatch(
                handle=manifest.handle,
                room=room,
                result="aborted",
                duration_s=result.duration_s,
                cost_usd=0.0,
            )
            return

        ym = datetime.now(UTC).strftime("%Y-%m")
        state.budget_used_usd[(manifest.handle, ym)] = (
            state.budget_used_usd.get((manifest.handle, ym), 0.0) + result.cost_usd
        )
        state.record_dispatch(
            handle=manifest.handle,
            room=room,
            result="ok" if result.ok else "error",
            duration_s=result.duration_s,
            cost_usd=result.cost_usd,
        )

        try:
            await _post_log(
                config, room, manifest, prompt=prompt, sender_handle=sender_handle, result=result
            )
        except Exception as exc:  # noqa: BLE001 - a log write must never sink the reply
            state.record_error("post_log", exc)
            log.warning("could not write log entry for @%s: %s", manifest.handle, exc)

        try:
            reply = build_reply(
                handle=manifest.handle, room=room, woke=woke, text=result.final_message
            )
            await publish(reply)
        except Exception as exc:  # noqa: BLE001 - best-effort channel publish
            state.record_error("publish_reply", exc)
            log.warning("could not publish reply for @%s: %s", manifest.handle, exc)


async def _handle_abort(
    state: DaemonState, room: str, handle: str, sender_handle: str, woke: dict, publish: PublishFn
) -> None:
    """``@handle abort|cancel|stop`` — SIGTERM the agent's running spawn."""
    running = state.running.get(handle)
    if running is None:
        await _reply(
            publish, handle, room, woke, f"○ nothing to abort (no run in flight) — {sender_handle}"
        )
        return
    try:
        running.process.terminate()
    except ProcessLookupError:
        pass
    log.info(
        "abort @%s ← %s (running %.1fs)",
        handle,
        sender_handle,
        time.monotonic() - running.started_at,
    )
    await _reply(publish, handle, room, woke, f"✗ aborted by {sender_handle}")


async def _handle_status(
    state: DaemonState, room: str, handle: str, woke: dict, publish: PublishFn
) -> None:
    """``@handle status`` — describe the agent's current state."""
    running = state.running.get(handle)
    if running is not None:
        elapsed = time.monotonic() - running.started_at
        reply = (
            f"● running for {elapsed:.0f}s (prompt: {running.prompt[:80]!r}, from {running.sender})"
        )
    else:
        last = state.last_dispatch or {}
        if last.get("agent") == handle:
            reply = (
                f"○ idle · last run: {last.get('result')} in "
                f"{last.get('duration_s', 0):.1f}s (cost ${last.get('cost_usd', 0):.4f})"
            )
        else:
            reply = "○ idle · no recent runs"
    await _reply(publish, handle, room, woke, reply)


async def _reply(publish: PublishFn, handle: str, room: str, woke: dict, text: str) -> None:
    await publish(build_reply(handle=handle, room=room, woke=woke, text=text))


# ── The long-lived waker loop ────────────────────────────────────────────────


async def run_connector(
    *,
    config: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room: str,
    handle: str,
    endpoint: str | None = None,
    workspace: str = DEFAULT_WORKSPACE,
) -> None:
    """Hold ``handle``'s SLIM membership in ``room`` and wake it on inbound L9.

    Runs a :class:`~mycelium.slim.member.MemberSession` — which owns connect,
    keepalive, reconnect + re-serve, and memory sync — and for each addressed
    message it yields, spawns the owned turn off the loop so control verbs
    (abort/status) stay responsive while a turn runs.
    """
    session = MemberSession(
        config,
        room,
        handle,
        endpoint=endpoint,
        workspace=workspace,
        stopping=state.stopping,
        on_error=state.record_error,
        on_connected=lambda: state.rooms_connected.add(room),
        on_disconnected=lambda: state.rooms_connected.discard(room),
    )
    async for content in session.messages():
        # Drive-active routing: while this handle is a host engine driving a
        # negotiation, inbound agent replies (addressed to the engine) belong to
        # the drive, not a re-dispatch. Hand them to the drive's queue and skip
        # the normal wake path.
        drive_queue = state.active_drives.get(handle)
        if drive_queue is not None:
            drive_queue.put_nowait(content)
            continue
        asyncio.create_task(  # noqa: RUF006 - fire-and-forget; loop stays responsive
            _guarded_inbound(
                config=config,
                daemon_cfg=daemon_cfg,
                state=state,
                room=room,
                handle=handle,
                content=content,
                publish=session.publish,
            )
        )


async def _guarded_inbound(**kwargs: Any) -> None:
    """Run :func:`handle_inbound`, logging (never raising) on failure."""
    state: DaemonState = kwargs["state"]
    room, handle = kwargs["room"], kwargs["handle"]
    try:
        await handle_inbound(**kwargs)
    except Exception as exc:  # noqa: BLE001 - one bad message must not kill the loop
        state.record_error(f"inbound[{room}/{handle}]", exc)
        log.exception("inbound dispatch error in %s/%s: %s", room, handle, exc)
