# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SLIM connector + wake bridge — the daemon's member half (Step 5, bible §12).

Step 4 made the backend the room's always-on **moderator** (persister + durable
inbox). This module is the **member** the backend invites: per ``(room, handle)``
it holds a SLIM group subscription and, on an inbound L9 message addressed to the
handle, **wakes** the agent — cold-spawning a ``claude -p`` turn and publishing
its reply back onto the channel as an L9 ``exchange`` (the backend persister
records it, so other members see it).

This replaces the daemon's old httpx SSE stream (``dispatch.py``). The dispatch
**decision** machinery — ownership, ``allow_from``/budget/depth gates, the
per-handle serial lock, control verbs, cold-spawn — is reused wholesale from
``dispatch.py``; only the transport (SLIM instead of SSE) and the reply sink
(channel publish instead of an HTTP POST) change. The agent's contract is
unchanged: it never speaks SLIM or L9.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from mycelium.daemon.dispatch import (
    _CONTROL_ABORT,
    _CONTROL_STATUS,
    _extract_body,
    _fetch_agent_context,
    _leading_verb,
    _normalize_sender,
    _post_log,
    _render_plan_block,
    gate_allow_from,
    gate_budget,
    gate_depth,
    list_agent_handles,
    load_manifest,
    load_notes,
)
from mycelium.filesystem import KnowledgeApplyResult, apply_knowledge, get_room_dir
from mycelium.integrations import get_integration
from mycelium.integrations._spawn_common import SpawnRequest
from mycelium.slim import l9
from mycelium.slim.client import SlimClient, SlimReceiveTimeout, SlimUnavailableError
from mycelium.slim.naming import DEFAULT_WORKSPACE, SlimIdentity

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.daemon.config import DaemonConfig
    from mycelium.daemon.state import DaemonState
    from mycelium.protocol import AgentManifest

log = logging.getLogger("mycelium.daemon")

# A content dict sink — the loop binds this to a channel broadcast; tests bind a
# recorder. The connector always hands it a full ``{content, l9: <envelope>}``.
PublishFn = Callable[[dict], Awaitable[None]]

# Reconnect backoff after a dropped/failed subscription. The backend re-invites
# a returning member and re-serves its missed tail (durable inbox, Step 4), so a
# reconnect is cheap and safe to retry.
_RECONNECT_BACKOFF_S = 5.0

# The presence "hello" a connector broadcasts once it is in the group. It seeds
# the backend persister's reply route for this handle (it caches a reply context
# per *sender*), so a connector that then drops and rejoins is re-served the tail
# it missed. Without a first message the persister has no point-to-point route to
# a never-spoke member — this closes that gap (Step 5 trap, option (a)).
_HELLO_TEXT = "joined the room"


# ── Episode / topic derivation ───────────────────────────────────────────────
# Match the backend's ``l9.episode_urn`` / ``l9.topic_urn`` forms so a reply
# stays inside the same episode/concept the room is coordinating under.


def _room_episode(room: str) -> str:
    return f"urn:ioc:mycelium:episode:{room}:live"


def _room_topic(room: str) -> str:
    return f"urn:concept:mycelium:{room}"


# ── Connector target discovery ───────────────────────────────────────────────


def connector_targets(daemon_cfg: DaemonConfig) -> list[tuple[str, str]]:
    """The ``(room, handle)`` pairs this daemon should hold a connector for.

    A handle qualifies when it is (a) registered in the room's local mirror,
    (b) owned by this daemon (``daemon.toml`` handles), and (c) a **cold_spawn**
    family (claude_code / cursor). ``long_lived_gateway`` families (openclaw,
    hermes) own their own delivery and are skipped, exactly as the old SSE
    dispatch skipped them.
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
            if integration.lifecycle != "cold_spawn":
                continue
            targets.append((room, handle))
    return targets


# ── Wake decision (pure) ─────────────────────────────────────────────────────


def should_wake(content: dict, handle: str) -> bool:
    """True if an inbound message should wake ``handle``.

    Wakes only on an ``exchange`` (a room turn) that is **not the agent's own**
    reply (loop guard: sender != handle) and is **addressed to the handle** —
    either via the L9 ``participants`` recipients or a raw ``@handle`` token in
    the human-facing text. System envelopes (``commit``/``knowledge``) are
    observed but never spawn a turn.
    """
    if l9.kind_of(content) != l9.EXCHANGE_KIND:
        return False
    sender = l9.sender_of(content)
    if sender is not None and _normalize_sender(sender) == _normalize_sender(handle):
        return False
    norm = _normalize_sender(handle)
    if any(_normalize_sender(r) == norm for r in l9.recipients_of(content)):
        return True
    text = l9.human_text_of(content)
    return _mentions(text, handle)


def _mentions(text: str, handle: str) -> bool:
    """True if ``text`` contains an ``@handle`` token (not mid-word)."""
    lower = text.lower()
    needle = f"@{handle.lower()}"
    idx = lower.find(needle)
    if idx == -1:
        return False
    end = idx + len(needle)
    nxt = lower[end] if end < len(lower) else ""
    return not (nxt and (nxt.isalnum() or nxt in "_-"))


# ── Reply building ───────────────────────────────────────────────────────────


def build_reply(
    *, handle: str, room: str, woke: dict, text: str, message_id: str | None = None
) -> dict:
    """Build the L9 ``exchange`` reply content for ``handle``, parented on ``woke``.

    Threads causality (``parents = [woke message id]``) and stays in the woke
    message's episode/topic so the backend's causal buffer + transcript remain
    correct.
    """
    woke_id = l9.message_id_of(woke)
    sender = l9.sender_of(woke)
    return l9.build_reply_content(
        sender=handle,
        recipients=[sender] if sender else [],
        episode=l9.episode_of(woke) or _room_episode(room),
        parents=[woke_id] if woke_id else [],
        topic=l9.topic_of(woke) or _room_topic(room),
        text=text,
        message_id=message_id,
    )


# ── Memory sync (bible §11) ──────────────────────────────────────────────────


def apply_knowledge_message(room: str, content: dict) -> KnowledgeApplyResult | None:
    """Write a ``knowledge`` message's carried memory into the local store.

    Push-with-content (bible §11): the message *carries* the markdown, so this is
    a pure local file write — never a fetch back over HTTP. Returns the
    :class:`~mycelium.filesystem.KnowledgeApplyResult` (or ``None`` when the
    message carried no write) so the caller can trigger a reindex on a real apply.

    Reindexing the JSONL is **not** done here: on the moderator host the always-on
    backend's file watcher re-embeds a write, but a member host that runs a
    daemon-only knows no watcher — so the connector reindexes explicitly after a
    successful apply (see :func:`reindex_after_knowledge`). This closes the
    "markdown lands but search never sees it" gap (Step 9, bible §11).

    Conflict policy is enforced in :func:`mycelium.filesystem.apply_knowledge`
    (last-write-wins; a stale-base write is kept out, logged, and dropped).
    """
    data = l9.payload_data_of(content)
    key = data.get("key")
    body = data.get("content")
    if not isinstance(key, str) or not key or not isinstance(body, str):
        log.debug("knowledge message in %s carried no memory write — ignoring", room)
        return None
    try:
        version = int(data.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    created_by = str(data.get("created_by") or "CognitiveEngine")
    updated_by = str(data.get("updated_by") or created_by)
    result = apply_knowledge(
        get_room_dir(room),
        key=key,
        content=body,
        version=version,
        created_by=created_by,
        updated_by=updated_by,
    )
    if result.conflict:
        cur = result.current or {}
        log.warning(
            "knowledge write to %s/%s rejected (stale base): local v%s by %s at %s (incoming v%s)",
            room,
            key,
            cur.get("version"),
            cur.get("updated_by"),
            cur.get("updated_at"),
            version,
        )
    elif result.applied:
        log.info("knowledge write applied: %s/%s (v%d)", room, key, version)
    return result


async def reindex_after_knowledge(config: MyceliumConfig, room: str) -> None:
    """Re-embed a room's markdown into its JSONL index after a knowledge apply.

    The receiver half of memory sync writes canonical markdown; the JSONL search
    index is derived and must be refreshed or the member host's ``memory search``
    never sees the new content (bible §11, Step 9). On the moderator host a file
    watcher would do this; a member host that runs no watcher relies on the
    connector calling its backend's reindex endpoint here.

    The CLI has no local embedder (embeddings live in the backend), so — like
    ``mycelium memory reindex`` — this is an HTTP call to the co-located backend,
    scoped to the one room. **Best-effort:** a reindex failure must never sink the
    write (the markdown is already durable and rebuildable), so it is logged and
    swallowed. Reindex is idempotent, so a retry-on-reconnect re-serve is safe.
    """
    api_url = config.server.api_url
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{api_url}/api/rooms/{room}/reindex")
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - reindex is best-effort; markdown is canonical
        log.warning("reindex after knowledge write failed for room %s: %s", room, exc)
        return
    log.debug("reindexed room %s after knowledge write", room)


# ── Per-message dispatch (transport-agnostic) ────────────────────────────────


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

    Mirrors ``dispatch.on_message`` + ``_dispatch_one`` but SLIM-native: the
    ownership check is implicit (this connector owns ``handle``), control verbs
    and gates are unchanged, and the reply is published to the channel rather
    than POSTed over HTTP.
    """
    # Memory sync (bible §11): a ``knowledge`` message carries markdown content —
    # write it into the local store so the agent's working set updates mid-task.
    # It never wakes a turn. Co-located connectors each apply it, but the apply is
    # idempotent by version, so only the first actually writes; the rest skip.
    # On a real write, reindex so a member host with no file watcher still surfaces
    # the new content in search (Step 9 — close the daemon-only reindex gap).
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


# ── The long-lived member loop ───────────────────────────────────────────────


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
    """Hold ``handle``'s SLIM subscription in ``room`` and wake it on inbound L9.

    Connects the member app, waits to be invited by the backend moderator, sends
    a presence hello (seeding the durable-inbox route), then pumps ``get_message``
    forever — spawning owned turns off the loop so control verbs (abort/status)
    stay responsive while a turn runs. Reconnects on drop; the backend re-serves
    the missed tail.
    """
    node = endpoint or config.slim.node_endpoint
    identity = SlimIdentity(workspace, room, handle)

    while not state.stopping.is_set():
        client: SlimClient | None = None
        try:
            client = await SlimClient(identity).connect(node)
            session = await client.listen_for_session()
            log.info("connector joined: %s/%s", room, handle)
            state.rooms_connected.add(room)

            async def publish(content: dict, _session=session, _client=client) -> None:
                await SlimClient.publish(_session, l9.serialize(content))

            # Seed the re-serve route so a later reconnect is re-served its tail.
            await publish(
                l9.build_reply_content(
                    sender=handle,
                    recipients=[],
                    episode=_room_episode(room),
                    parents=[],
                    topic=_room_topic(room),
                    text=_HELLO_TEXT,
                    payload_type="presence",
                )
            )

            while not state.stopping.is_set():
                try:
                    message = await SlimClient.receive_message(session)
                except SlimReceiveTimeout:
                    # Idle window elapsed with no message — the session is alive,
                    # just quiet. Keep waiting on it; do NOT fall through to the
                    # reconnect path, which would drop and rejoin the group every
                    # timeout window and churn membership (participant flapping).
                    continue
                content = l9.parse(message.payload)
                if content is None:
                    continue
                asyncio.create_task(  # noqa: RUF006 - fire-and-forget; loop stays responsive
                    _guarded_inbound(
                        config=config,
                        daemon_cfg=daemon_cfg,
                        state=state,
                        room=room,
                        handle=handle,
                        content=content,
                        publish=publish,
                    )
                )
        except asyncio.CancelledError:
            raise
        except SlimUnavailableError:  # pragma: no cover - platform dependent
            log.warning("slim-bindings unavailable; connector for %s/%s disabled", room, handle)
            return
        except Exception as exc:  # noqa: BLE001 - resilient reconnect loop
            state.record_error(f"connector[{room}/{handle}]", exc)
            log.warning(
                "connector %s/%s error: %s — reconnecting in %.0fs",
                room,
                handle,
                exc,
                _RECONNECT_BACKOFF_S,
            )
        finally:
            state.rooms_connected.discard(room)
            if client is not None:
                await client.close()

        if state.stopping.is_set():
            return
        await asyncio.sleep(_RECONNECT_BACKOFF_S)


async def _guarded_inbound(**kwargs) -> None:
    """Run :func:`handle_inbound`, logging (never raising) on failure."""
    state: DaemonState = kwargs["state"]
    room, handle = kwargs["room"], kwargs["handle"]
    try:
        await handle_inbound(**kwargs)
    except Exception as exc:  # noqa: BLE001 - one bad message must not kill the loop
        state.record_error(f"inbound[{room}/{handle}]", exc)
        log.exception("inbound dispatch error in %s/%s: %s", room, handle, exc)
