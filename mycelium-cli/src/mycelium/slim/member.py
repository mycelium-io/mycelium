# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The member-session core — SLIM membership as a runtime-agnostic primitive.

Being a *member* of a room's SLIM group — holding the subscription, staying alive
through idle gaps, receiving addressed messages, publishing L9 replies, applying
carried memory — is generic: it has nothing to do with *how* an agent thinks or
whether it is a cold-spawned subprocess. This module owns that primitive so it is
reachable by any caller:

* the **daemon** runs a :class:`MemberSession` in the background and cold-spawns a
  turn when an addressed message arrives (:mod:`mycelium.daemon.connector`);
* an **already-awake** caller (a Claude Code session, a shell script, a subagent)
  runs the foreground ``await`` / ``respond`` commands, which are thin front doors
  onto this same core (:mod:`mycelium.commands.participate`).

One core, two consumers — so the "CLI member" and the "daemon member" can never
drift. This module depends only on the SLIM transport, the L9 helpers, and the
local file store; it must never import :mod:`mycelium.daemon`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx

from mycelium.filesystem import KnowledgeApplyResult, apply_knowledge, get_room_dir
from mycelium.slim import l9
from mycelium.slim.client import SlimClient, SlimReceiveTimeout, SlimUnavailableError
from mycelium.slim.naming import DEFAULT_WORKSPACE, SlimIdentity

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

log = logging.getLogger("mycelium.slim.member")

# A content-dict sink: a consumer binds this to a channel broadcast (the daemon
# passes ``MemberSession.publish``); tests bind a recorder. Always handed a full
# ``{content, l9: <envelope>}`` dict.
PublishFn = Callable[[dict], Awaitable[None]]

# Reconnect backoff after a dropped/failed subscription. The backend re-invites a
# returning member and re-serves its missed tail (durable inbox), so a reconnect
# is cheap and safe to retry.
RECONNECT_BACKOFF_S = 5.0

# The presence "hello" a member broadcasts once it is in the group. It seeds the
# backend persister's reply route for this handle (the persister caches a reply
# context per *sender*), so a member that then drops and rejoins is re-served the
# tail it missed. Without a first message the persister has no point-to-point
# route to a never-spoke member — this closes that gap.
_HELLO_TEXT = "joined the room"

# SLIM marks a group member offline after 3 missed heartbeats at a 10s interval
# (~30s) — a compile-time constant in the node, not configurable, and the bindings
# expose no heartbeat sender for a joining participant. But *any* received message
# resets a member's liveness (SLIM's ``notify_received_activity``). So a member
# that only ever waits on ``receive`` (the normal idle state of a waiting member)
# gets reaped after 30s of quiet — which silently breaks any coordination with a
# gap longer than that (e.g. a multi-round mediated negotiation). We keep the
# member alive by publishing a tiny keepalive well inside that window. It carries
# ``payload_type="keepalive"`` so the backend persister skips recording it (no
# transcript spam) and the receive stream drops it (not an addressed exchange).
#
# The interval must sit *comfortably* under the 3×10s window: the node increments
# a miss every 10s, so a 20s ping races the tick and can still accrue 3 misses.
# Default 8s (miss count never exceeds 1). Env-tunable for load/latency trade-offs.
KEEPALIVE_INTERVAL_S = float(os.getenv("MYCELIUM_KEEPALIVE_INTERVAL_S", "8"))
KEEPALIVE_TYPE = "keepalive"


# ── Episode / topic derivation ───────────────────────────────────────────────
# Match the backend's ``l9.episode_urn`` / ``l9.topic_urn`` forms so a reply
# stays inside the same episode/concept the room is coordinating under.


def room_episode(room: str) -> str:
    return f"urn:ioc:mycelium:episode:{room}:live"


def room_topic(room: str) -> str:
    return f"urn:concept:mycelium:{room}"


# ── Handle normalization + wake decision (pure) ──────────────────────────────


def normalize_handle(handle: str) -> str:
    """Fold a handle to its comparison form (drop a leading ``@``, lowercase)."""
    return handle.lstrip("@").lower()


def should_wake(content: dict, handle: str) -> bool:
    """True if an inbound message is a room turn addressed to ``handle``.

    True only for an ``exchange`` (a room turn) that is **not the handle's own**
    reply (loop guard: sender != handle) and is **addressed to the handle** —
    either via the L9 ``participants`` recipients or a raw ``@handle`` token in
    the human-facing text. System envelopes (``commit``/``knowledge``) are
    observed but never count as an addressed turn.
    """
    if l9.kind_of(content) != l9.EXCHANGE_KIND:
        return False
    sender = l9.sender_of(content)
    if sender is not None and normalize_handle(sender) == normalize_handle(handle):
        return False
    norm = normalize_handle(handle)
    if any(normalize_handle(r) == norm for r in l9.recipients_of(content)):
        return True
    return _mentions(l9.human_text_of(content), handle)


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


# A member volunteers a negotiation position by ending its reply with a marker
# like ``[[mycelium: confidence=0.85 stance=accept]]``. Those fields are lifted
# onto the exchange's L9 payload so the aligner can score convergence (without
# them every position folds to a reject — MPC is undefined). The marker is
# stripped before the reply is posted, so the room shows clean prose.
_POSITION_MARKER_RE = re.compile(r"\[\[\s*mycelium\s*:(.*?)\]\]", re.IGNORECASE | re.DOTALL)
_STANCE_TO_ACTION = {
    "accept": "accept",
    "agree": "accept",
    "yes": "accept",
    "reject": "reject",
    "block": "reject",
    "no": "reject",
}


def parse_position_marker(text: str) -> tuple[dict[str, Any], str]:
    """Split a reply into (epistemic payload, human-facing text).

    Lifts ``confidence`` (a 0–1 float) and ``stance`` (→ L9 ``action``) out of any
    ``[[mycelium: …]]`` markers and strips every marker from the text. Forgiving
    by design — a malformed value is dropped, not raised, mirroring the backend's
    ``l9_episode.sanitize_epistemic_fields``. No marker → ``({}, text)`` (a plain
    reply, unchanged behaviour).
    """
    payload: dict[str, Any] = {}
    for match in _POSITION_MARKER_RE.finditer(text):
        for key, raw in re.findall(r"(\w+)\s*=\s*(\S+)", match.group(1)):
            k = key.lower()
            if k == "confidence":
                try:
                    val = float(raw)
                except ValueError:
                    continue
                if 0.0 <= val <= 1.0:
                    payload["confidence"] = val
            elif k in ("stance", "action"):
                action = _STANCE_TO_ACTION.get(raw.lower())
                if action:
                    payload["action"] = action
    clean = _POSITION_MARKER_RE.sub("", text).strip() or text.strip()
    return payload, clean


def build_reply(
    *, handle: str, room: str, woke: dict, text: str, message_id: str | None = None
) -> dict:
    """Build the L9 ``exchange`` reply content for ``handle``, parented on ``woke``.

    Threads causality (``parents = [woke message id]``) and stays in the woke
    message's episode/topic so the backend's causal buffer + transcript remain
    correct. Any volunteered position marker in ``text`` is lifted into the L9
    payload (so the aligner can score it) and stripped from the posted prose.
    """
    payload_data, clean_text = parse_position_marker(text)
    woke_id = l9.message_id_of(woke)
    sender = l9.sender_of(woke)
    return l9.build_reply_content(
        sender=handle,
        recipients=[sender] if sender else [],
        episode=l9.episode_of(woke) or room_episode(room),
        parents=[woke_id] if woke_id else [],
        topic=l9.topic_of(woke) or room_topic(room),
        text=clean_text,
        payload_data=payload_data or None,
        message_id=message_id,
    )


# ── Memory sync ──────────────────────────────────────────────────────────────


def apply_knowledge_message(room: str, content: dict) -> KnowledgeApplyResult | None:
    """Write a ``knowledge`` message's carried memory into the local store.

    The message *carries* the markdown, so this is a pure local file write —
    never a fetch back over HTTP. Returns the
    :class:`~mycelium.filesystem.KnowledgeApplyResult` (or ``None`` when the
    message carried no write) so the caller can trigger a reindex on a real apply.

    Reindexing the JSONL is **not** done here: on the moderator host the always-on
    backend's file watcher re-embeds a write, but a member host that runs no
    watcher relies on :func:`reindex_after_knowledge` after a successful apply, so
    search sees the new content.

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
    created_by = str(data.get("created_by") or "system")
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
    index is derived and must be refreshed or a member host's ``memory search``
    never sees the new content. On the moderator host a file watcher would do
    this; a member host that runs no watcher relies on this reindex call.

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


# ── Presence ─────────────────────────────────────────────────────────────────


async def keepalive_loop(
    publish: PublishFn, room: str, handle: str, stopping: asyncio.Event
) -> None:
    """Publish a keepalive every ``KEEPALIVE_INTERVAL_S`` until ``stopping`` is set.

    Keeps SLIM from reaping an idle-but-connected member (see :data:`KEEPALIVE_TYPE`).
    Ends cleanly on a publish failure — the message stream owns reconnect, so a
    failed keepalive just retires this task quietly. Reads the interval from the
    module global at call time so it stays tunable (and test-overridable).
    """
    while not stopping.is_set():
        await asyncio.sleep(KEEPALIVE_INTERVAL_S)
        try:
            log.debug("keepalive → %s/%s", room, handle)
            await publish(
                l9.build_reply_content(
                    sender=handle,
                    recipients=[],
                    episode=room_episode(room),
                    parents=[],
                    topic=room_topic(room),
                    text="",
                    payload_type=KEEPALIVE_TYPE,
                )
            )
        except Exception:  # noqa: BLE001 - session dropping; stream handles reconnect
            return


async def announce_presence(config: MyceliumConfig, room: str, handle: str) -> None:
    """Announce ``handle`` to the backend so it (re)invites the member.

    Called on every (re)connect *before* listening for the session. The backend's
    join endpoint (re)invites the handle onto the room's SLIM group — so a member
    that was dropped while the laptop slept (or on any session close) rejoins on
    its own, and the durable inbox re-serves the tail it missed, without waiting
    for a human ``@mention``. Best-effort: no backend / no-node dev just means the
    member falls back to waiting to be invited, exactly as before.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{config.server.api_url}/api/rooms/{room}/sessions",
                json={"agent_handle": handle},
            )
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - presence announce is best-effort
        log.debug("announce presence for %s/%s failed (best-effort): %s", room, handle, exc)


# ── The member session ───────────────────────────────────────────────────────

_ErrorSink = Callable[[str, Exception], None]


def _log_error(where: str, exc: Exception) -> None:
    log.warning("%s: %s", where, exc)


class MemberSession:
    """A live SLIM membership for one ``(room, handle)`` — the shared core.

    Encapsulates the whole membership lifecycle so a consumer only has to decide
    *what to do with an addressed message*:

    * :meth:`connect` establishes the group session (announce → listen → keepalive
      → presence hello) and :meth:`aclose` tears it down; the pair is usable as an
      async context manager for a one-shot publish (``respond``).
    * :meth:`messages` is a self-managing async stream that yields wake-candidate
      **exchanges**, transparently reconnecting on drop, dropping keepalives, and
      applying carried ``knowledge`` as local memory (never yielding it — it is
      memory sync, not an addressed turn). Both the daemon and ``await`` iterate
      it; neither reimplements the loop.
    * :meth:`publish` broadcasts a content dict on the current session (rebound
      across reconnects, so a reply always goes out on the live session).
    """

    def __init__(
        self,
        config: MyceliumConfig,
        room: str,
        handle: str,
        *,
        endpoint: str | None = None,
        workspace: str = DEFAULT_WORKSPACE,
        stopping: asyncio.Event | None = None,
        connect_timeout_s: float | None = None,
        on_error: _ErrorSink | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self.room = room
        self.handle = handle
        self._endpoint = endpoint or config.slim.node_endpoint
        self._workspace = workspace
        self._stopping = stopping or asyncio.Event()
        self._connect_timeout_s = connect_timeout_s
        self._on_error = on_error or _log_error
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._client: SlimClient | None = None
        self._session: Any | None = None
        self._keepalive_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def __aenter__(self) -> MemberSession:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """Join the room's SLIM group: announce → listen → keepalive → hello.

        Idempotent while connected. Raises :class:`SlimUnavailableError` where no
        native SLIM wheel exists, or :class:`TimeoutError` if the moderator never
        invites us within ``connect_timeout_s`` (when set).
        """
        if self._session is not None:
            return
        identity = SlimIdentity(self._workspace, self.room, self.handle)
        client = await SlimClient(identity).connect(self._endpoint)
        # Self-rejoin: tell the backend we're (re)connecting so it invites us — a
        # slept/dropped member rejoins without needing a fresh @mention.
        await announce_presence(self._config, self.room, self.handle)
        listen = client.listen_for_session()
        if self._connect_timeout_s is not None:
            session = await asyncio.wait_for(listen, timeout=self._connect_timeout_s)
        else:
            session = await listen
        self._client = client
        self._session = session
        log.info("member joined: %s/%s", self.room, self.handle)
        if self._on_connected is not None:
            self._on_connected()
        # Keep the member alive through idle gaps (SLIM reaps quiet members after
        # ~30s — see KEEPALIVE_TYPE). Cancelled in :meth:`aclose`.
        self._keepalive_task = asyncio.create_task(
            keepalive_loop(self.publish, self.room, self.handle, self._stopping)
        )
        # Seed the re-serve route so a later reconnect is re-served its tail.
        await self.publish(
            l9.build_reply_content(
                sender=self.handle,
                recipients=[],
                episode=room_episode(self.room),
                parents=[],
                topic=room_topic(self.room),
                text=_HELLO_TEXT,
                payload_type="presence",
            )
        )

    async def aclose(self) -> None:
        """Cancel the keepalive and leave the group. Idempotent; never raises."""
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._keepalive_task
            self._keepalive_task = None
        client = self._client
        was_connected = self._session is not None
        self._client = None
        self._session = None
        if client is not None:
            await client.close()
        if was_connected and self._on_disconnected is not None:
            self._on_disconnected()

    async def publish(self, content: dict) -> None:
        """Broadcast a content dict on the current session."""
        if self._session is None:
            raise RuntimeError("MemberSession.publish before connect")
        await SlimClient.publish(self._session, l9.serialize(content))

    async def messages(self) -> AsyncIterator[dict]:
        """Yield wake-candidate exchanges, holding membership across reconnects.

        Keepalives are dropped and ``knowledge`` messages are applied to the local
        store (memory sync) and swallowed — a consumer only ever sees room turns
        it might need to act on. Runs until the ``stopping`` event is set (or the
        SLIM wheel is missing); reconnects with backoff on a dropped session, and
        the backend re-serves the missed tail on rejoin.
        """
        while not self._stopping.is_set():
            try:
                await self.connect()
            except SlimUnavailableError:  # pragma: no cover - platform dependent
                log.warning(
                    "slim-bindings unavailable; member %s/%s disabled", self.room, self.handle
                )
                return
            except asyncio.CancelledError:
                await self.aclose()
                raise
            except Exception as exc:  # noqa: BLE001 - resilient reconnect loop
                self._on_error(f"member[{self.room}/{self.handle}]", exc)
                await self.aclose()
                if self._stopping.is_set():
                    return
                await asyncio.sleep(RECONNECT_BACKOFF_S)
                continue

            try:
                async for content in self._receive_loop():
                    yield content
            except asyncio.CancelledError:
                await self.aclose()
                raise
            except Exception as exc:  # noqa: BLE001 - resilient reconnect loop
                self._on_error(f"member[{self.room}/{self.handle}]", exc)
            finally:
                await self.aclose()

            if self._stopping.is_set():
                return
            await asyncio.sleep(RECONNECT_BACKOFF_S)

    async def _receive_loop(self) -> AsyncIterator[dict]:
        """Pump the current session, yielding only wake-candidate exchanges."""
        assert self._session is not None
        while not self._stopping.is_set():
            try:
                message = await SlimClient.receive_message(self._session)
            except SlimReceiveTimeout:
                # Idle window elapsed with no message — the session is alive, just
                # quiet. Keep waiting on it; do NOT drop and rejoin (which churns
                # group membership every timeout window — participant flapping).
                continue
            content = l9.parse(message.payload)
            if content is None:
                continue
            if l9.payload_type_of(content) == KEEPALIVE_TYPE:
                continue  # another member's liveness ping — never an addressed turn
            if l9.kind_of(content) == l9.KNOWLEDGE_KIND:
                # Memory sync: a knowledge message carries markdown; apply it to
                # the local store (idempotent by version) and reindex so a member
                # host with no file watcher still surfaces it in search. Never an
                # addressed turn, so it is swallowed rather than yielded.
                result = apply_knowledge_message(self.room, content)
                if result is not None and result.applied:
                    await reindex_after_knowledge(self._config, self.room)
                continue
            yield content


async def await_addressed(
    config: MyceliumConfig,
    room: str,
    handle: str,
    *,
    timeout_s: float | None = None,
    endpoint: str | None = None,
    workspace: str = DEFAULT_WORKSPACE,
    stopping: asyncio.Event | None = None,
) -> dict | None:
    """Join ``room`` as ``handle`` and return the first message addressed to it.

    Returns the wake-worthy exchange content, or ``None`` if ``timeout_s`` elapses
    (or ``stopping`` is set) before one arrives. This *is* SLIM membership for the
    duration; on reconnect the missed tail is re-served, so a member never drops
    coordination between an ``await`` and the next.
    """
    session = MemberSession(
        config, room, handle, endpoint=endpoint, workspace=workspace, stopping=stopping
    )

    async def _first_addressed() -> dict | None:
        async for content in session.messages():
            if should_wake(content, handle):
                return content
        return None

    try:
        if timeout_s is not None:
            return await asyncio.wait_for(_first_addressed(), timeout=timeout_s)
        return await _first_addressed()
    except TimeoutError:
        return None
    finally:
        await session.aclose()


async def publish_reply(
    config: MyceliumConfig,
    room: str,
    handle: str,
    content: dict,
    *,
    endpoint: str | None = None,
    workspace: str = DEFAULT_WORKSPACE,
    connect_timeout_s: float | None = 30.0,
) -> None:
    """Join ``room`` as ``handle``, publish one content dict, and leave.

    A short-lived membership: a caller that has already reasoned about an awaited
    message uses this to put its L9 reply on the channel without holding a
    long-running session. ``connect_timeout_s`` bounds the wait for the moderator
    to invite us so a missing backend fails loudly instead of hanging.
    """
    async with MemberSession(
        config,
        room,
        handle,
        endpoint=endpoint,
        workspace=workspace,
        connect_timeout_s=connect_timeout_s,
    ) as session:
        await session.publish(content)
