# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""MyceliumRoomAdapter — hermes-side ``BasePlatformAdapter`` implementation.

Owns the side-effecting half of the plugin:
  - ``connect()`` — open one :func:`room_sse.subscribe_room` task per
    configured room (plus session sub-room subscribers spawned lazily on
    ``coordination_join`` / ``coordination_start``), and a shared
    ``aiohttp.ClientSession`` for outbound POSTs.
  - ``disconnect()`` — cancel all SSE tasks, close the HTTP session.
  - ``send()`` — POST the agent's reply to ``/api/rooms/{room}/messages``;
    cache the returned message id in ``_own_message_ids`` so the SSE echo
    of the same message doesn't re-trigger a dispatch.
  - inbound delivery — translate each :class:`route.RouteAction` into the
    appropriate hermes call (``handle_message`` for ``Dispatch``,
    :func:`notify_home.deliver_notify_home` for ``NotifyHome``).

The chat_id convention is ``<room>`` for the parent room and
``<room>:session:<id>`` for session sub-rooms — same wire identifier
the backend uses, so it round-trips cleanly through hermes's session
keying and our own outbound POST routing.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

import aiohttp
from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)

from .post_to_room import post_to_room
from .return_address import ReturnAddressBook, stash_return_address
from .room_sse import subscribe_room
from .route import (
    Dispatch,
    Ignore,
    NotifyHome,
    RoomConfig,
    StashReturnAddress,
    SubscribeSession,
    route_message,
)
from .session_sse import subscribe_session

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

PLATFORM_NAME = "mycelium-room"


class MyceliumRoomAdapter(BasePlatformAdapter):
    """Hermes platform adapter that surfaces Mycelium rooms as chats."""

    name = PLATFORM_NAME

    def __init__(self, config: PlatformConfig) -> None:
        super().__init__(config, Platform(PLATFORM_NAME))
        extra: dict[str, Any] = dict(config.extra or {})
        self._backend_url: str = str(extra.get("backend_url") or "").rstrip("/")
        self._api_token: str | None = extra.get("api_token") or None
        require_mention = extra.get("require_mention")
        self._require_mention = bool(require_mention) if isinstance(require_mention, bool) else True
        self._rooms: list[RoomConfig] = list(self._coerce_rooms(extra.get("rooms")))

        # Owns its own aiohttp.ClientSession because hermes adapters are
        # expected to manage their own networking (no shared connector
        # available at the BasePlatformAdapter level). We don't reuse the
        # gateway's session because its lifetime is tied to the runner.
        self._session: aiohttp.ClientSession | None = None
        self._sse_tasks: list[asyncio.Task] = []
        self._session_sub_tasks: dict[str, asyncio.Task] = {}
        self._own_message_ids: set[str] = set()
        self._own_message_id_queue: deque[str] = deque()
        self._return_addresses = ReturnAddressBook()

    # ── config coercion ─────────────────────────────────────────────────────

    def _coerce_rooms(self, raw: Any) -> Iterable[RoomConfig]:
        if not isinstance(raw, list):
            return ()
        out: list[RoomConfig] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            room = entry.get("room")
            if not isinstance(room, str) or not room:
                continue
            agents_raw = entry.get("agents") or []
            agents = tuple(str(a) for a in agents_raw if isinstance(a, (str, int)) and a)
            if not agents:
                # No agents listed → nothing for the plugin to dispatch.
                logger.debug("mycelium-room: skipping %s with no agents", room)
                continue
            out.append(
                RoomConfig(
                    room=room,
                    agents=agents,
                    require_mention=self._require_mention,
                    backend_url=self._backend_url,
                )
            )
        return out

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        if not self._backend_url:
            logger.error(
                "mycelium-room: backend_url is empty — set platforms.mycelium-room.extra.backend_url"
            )
            self._set_fatal_error(
                "no_backend_url",
                "platforms.mycelium-room.extra.backend_url is empty",
                retryable=False,
            )
            return False
        if not self._rooms:
            logger.warning(
                "mycelium-room: no rooms configured — adapter is idle until "
                "platforms.mycelium-room.extra.rooms is populated"
            )

        self._session = aiohttp.ClientSession()
        for rcfg in self._rooms:
            task = asyncio.create_task(
                subscribe_room(
                    session=self._session,
                    backend_url=self._backend_url,
                    room=rcfg.room,
                    on_message=self._make_room_handler(rcfg),
                    api_token=self._api_token,
                ),
                name=f"mycelium-room:{rcfg.room}",
            )
            self._sse_tasks.append(task)
        # Coordination joins are dual-persisted (session sub-room + parent
        # room) but the live NOTIFY only fires on the session sub-room
        # channel. The parent-room SSE never sees coordination_join, so we
        # can't bootstrap session sub-room subscriptions from join events.
        # Mirror the openclaw plugin's pattern: poll
        # ``/api/coordination-sessions`` and (re-)subscribe to every active
        # session sub-room. ``_spawn_session_sub`` is idempotent.
        if self._rooms:
            poll_task = asyncio.create_task(
                self._poll_active_sessions(),
                name="mycelium-room:session-poller",
            )
            self._sse_tasks.append(poll_task)
        self._mark_connected()
        logger.info(
            "mycelium-room: connected to %s — subscribed to %d room(s)",
            self._backend_url,
            len(self._rooms),
        )
        return True

    _POLL_INTERVAL_S: float = 5.0
    _TERMINAL_STATES: frozenset[str] = frozenset(("agreed", "failed", "idle"))

    async def _poll_active_sessions(self) -> None:
        """Discover and subscribe to every active session sub-room.

        Polls ``/api/coordination-sessions`` every ``_POLL_INTERVAL_S`` and:

        - opens a session sub-room SSE for any session in state
          ``waiting`` or ``negotiating`` we're not yet subscribed to
        - cancels subscriptions for sessions in terminal states
        - matches the session to one of our configured rooms by the
          ``<parent>:session:<short>`` prefix so the dispatch routes ticks
          to the right :class:`RoomConfig`'s agent list

        Polling failures (network blips, backend restarts) are logged at
        DEBUG and retried on the next tick — we never let one bad poll
        kill the task.
        """
        rooms_by_parent = {rcfg.room: rcfg for rcfg in self._rooms}
        url = f"{self._backend_url}/api/coordination-sessions?limit=200"
        headers: dict[str, str] = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        while True:
            try:
                await asyncio.sleep(self._POLL_INTERVAL_S)
                if self._session is None:
                    return
                try:
                    async with self._session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            logger.debug("mycelium-room: session poll → HTTP %s", resp.status)
                            continue
                        sessions = await resp.json()
                except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                    logger.debug("mycelium-room: session poll failed: %s", exc)
                    continue
                if not isinstance(sessions, list):
                    continue
                active: set[str] = set()
                for entry in sessions:
                    if not isinstance(entry, dict):
                        continue
                    display_name = entry.get("display_name")
                    state = entry.get("state")
                    parent = entry.get("parent_room_name")
                    if not (
                        isinstance(display_name, str)
                        and ":session:" in display_name
                        and isinstance(parent, str)
                        and parent in rooms_by_parent
                    ):
                        continue
                    if state in ("waiting", "negotiating"):
                        active.add(display_name)
                        if display_name not in self._session_sub_tasks:
                            self._spawn_session_sub(rooms_by_parent[parent], display_name)
                    elif isinstance(state, str) and state in self._TERMINAL_STATES:
                        existing = self._session_sub_tasks.pop(display_name, None)
                        if existing is not None:
                            existing.cancel()
                # Stop subscriptions for sessions no longer in the active list.
                for stale in list(self._session_sub_tasks.keys()):
                    if stale not in active:
                        task = self._session_sub_tasks.pop(stale, None)
                        if task is not None:
                            task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let polling die silently
                logger.exception("mycelium-room: session poller hit unexpected error")

    async def disconnect(self) -> None:
        for task in list(self._sse_tasks):
            task.cancel()
        for task in list(self._session_sub_tasks.values()):
            task.cancel()
        # gather() with return_exceptions so a CancelledError from one
        # task never short-circuits the cleanup loop.
        all_tasks: list[asyncio.Task] = [*self._sse_tasks, *self._session_sub_tasks.values()]
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._sse_tasks.clear()
        self._session_sub_tasks.clear()
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._mark_disconnected()
        logger.info("mycelium-room: disconnected")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,  # noqa: ARG002 — mycelium rooms have no reply threading
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """POST *content* into the Mycelium room identified by *chat_id*.

        The chat_id wire format is ``<room>:<agent>`` (see
        :meth:`_dispatch`) — hermes needs per-agent session keys, but the
        backend only accepts a plain room slug. Split here on the *last*
        ``:`` so room names that themselves contain a colon (e.g. session
        sub-rooms ``parent:session:<uuid>``) still round-trip cleanly.
        The trailing component is also our best signal for which handle
        the reply belongs to — use it as the default ``sender_handle``
        when the caller hasn't supplied one in metadata.
        """
        if self._session is None or not self._backend_url:
            return SendResult(success=False, error="mycelium-room adapter not connected")
        room, _sep, default_sender = chat_id.rpartition(":")
        if not room:
            # No ``:`` — chat_id is a bare room slug, treat the whole
            # thing as the room and leave the sender to fall through.
            room = chat_id
            default_sender = ""
        sender_handle = default_sender or "hermes-agent"
        if isinstance(metadata, dict):
            raw = metadata.get("sender_handle") or metadata.get("agent_id")
            if isinstance(raw, str) and raw:
                sender_handle = raw

        message_id = await post_to_room(
            session=self._session,
            backend_url=self._backend_url,
            room=room,
            sender_handle=sender_handle,
            content=content,
            api_token=self._api_token,
        )
        if message_id is None:
            return SendResult(
                success=False,
                error="mycelium room POST failed",
                retryable=True,
            )
        # Loop suppression: the SSE will echo this message back at us.
        self._own_message_ids.add(message_id)
        self._own_message_id_queue.append(message_id)
        while len(self._own_message_ids) > 1024:
            self._own_message_ids.discard(self._own_message_id_queue.popleft())
        return SendResult(success=True, message_id=message_id)

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        """Return a minimal descriptor for *chat_id*.

        Rooms don't have a friendly display name distinct from the room
        slug, so we return the slug verbatim plus a coarse ``type`` that
        distinguishes parent rooms from session sub-rooms.
        """
        chat_type = "session" if ":session:" in chat_id else "group"
        return {"name": chat_id, "type": chat_type}

    # ── inbound: route → side effects ──────────────────────────────────────

    def _make_room_handler(self, rcfg: RoomConfig):
        """Return a coroutine that processes one parent-room SSE event."""

        async def _handle(msg: dict[str, Any]) -> None:
            actions = route_message(rcfg, msg, self._own_message_ids)
            await self._execute_actions(rcfg, actions)

        return _handle

    def _make_session_handler(self, rcfg: RoomConfig):
        """Return a coroutine that processes one session-sub-room SSE event.

        The session sub-room shares the parent's RoomConfig (same agents
        list, same require_mention policy) so the router treats ticks
        for sub-rooms identically to ticks for the parent. The
        :class:`route.NotifyHome` and :class:`route.StashReturnAddress`
        actions already key off the message's ``room_name`` field, which
        is the sub-room name on the wire.
        """
        return self._make_room_handler(rcfg)

    async def _execute_actions(self, rcfg: RoomConfig, actions: list[Any]) -> None:
        for action in actions:
            if isinstance(action, Ignore):
                logger.debug("mycelium-room: ignore — %s", action.reason)
                continue
            if isinstance(action, Dispatch):
                await self._dispatch(rcfg, action)
                continue
            if isinstance(action, SubscribeSession):
                self._spawn_session_sub(rcfg, action.room_name)
                continue
            if isinstance(action, StashReturnAddress):
                stash_return_address(
                    self._return_addresses,
                    session_room=action.session_room,
                    agent_id=action.agent_id,
                    log=logger,
                )
                continue
            if isinstance(action, NotifyHome):
                from .notify_home import deliver_notify_home

                await deliver_notify_home(action=action, addresses=self._return_addresses)
                continue

    async def _dispatch(self, rcfg: RoomConfig, action: Dispatch) -> None:
        """Translate a :class:`route.Dispatch` into a hermes ``MessageEvent``.

        ``chat_id`` encodes both the Mycelium room and the addressed
        agent: ``<room>:<agent>`` keeps hermes's per-session keying
        cleanly separated when several handles share one configured
        room. Hermes treats this as one chat_id per agent, so each
        handle gets its own session.
        """
        chat_id = f"{rcfg.room}:{action.agent_id}"
        source = self.build_source(
            chat_id=chat_id,
            chat_name=f"{rcfg.room}/{action.agent_id}",
            chat_type="group",
            user_id=action.sender,
            user_name=action.sender,
            message_id=action.message_id,
        )
        event = MessageEvent(
            text=action.content,
            message_type=MessageType.TEXT,
            source=source,
            raw_message=None,
            message_id=action.message_id,
        )
        # handle_message is the BasePlatformAdapter entry into the
        # gateway dispatch loop. It returns immediately after queuing.
        await self.handle_message(event)

    def _spawn_session_sub(self, rcfg: RoomConfig, session_room: str) -> None:
        if session_room in self._session_sub_tasks:
            return
        if self._session is None:
            return
        task = asyncio.create_task(
            subscribe_session(
                session=self._session,
                backend_url=self._backend_url,
                session_room=session_room,
                on_message=self._make_session_handler(rcfg),
                api_token=self._api_token,
            ),
            name=f"mycelium-room-session:{session_room}",
        )
        self._session_sub_tasks[session_room] = task
        task.add_done_callback(lambda _t, key=session_room: self._session_sub_tasks.pop(key, None))
        logger.debug("mycelium-room: opened session SSE for %s", session_room)
