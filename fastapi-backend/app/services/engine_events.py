# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room lifecycle events, and the pluggable hooks engines install off them.

Engines have always been *summoned*: dormant until an ``@``-mention reaches the
persister's summon seam. That covers an engine that acts **on** a room, but not
one that changes how the room itself behaves. The summonguard is the second
shape: registering it has to install a filter into the room's own summon path,
and de-registering it has to take that filter back out.

This module is the seam for that, deliberately small — two concepts, no
scheduler, no persistence:

* **Lifecycle events.** :meth:`RoomLifecycle.emit` announces something happening
  to a room (an engine manifest written, a channel provisioned). Listeners are
  process-wide and room-agnostic; they filter on the payload themselves. A
  listener that raises is logged and skipped — a broken engine can never break a
  memory write.

* **Room hooks.** A listener responds by *installing* a named function into one
  room (:meth:`install`), keyed by the installing engine's handle so the same
  engine registering twice replaces its own hook rather than stacking. The
  room's machinery then looks the hook up by name (:meth:`hooks`) and — this is
  the property that keeps the feature honest — finds **nothing** when no engine
  installed one, so the un-guarded path stays exactly what it was.

Hook names are constants here rather than free strings so the extension points a
room exposes are enumerable in one place. Today there is one, ``SUMMON_FILTER``;
the shape generalizes (a reply filter, a memory-write filter) without changing
this module.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RoomEvent(StrEnum):
    """Lifecycle moments a room announces."""

    #: An ``agents/<handle>`` manifest with ``adapter: engine`` was written.
    #: Fired on every write, not only the first — engines treat it as "re-sync
    #: this room", which is what makes installation idempotent.
    ENGINE_REGISTERED = "engine.registered"
    #: An engine manifest was deleted from the room.
    ENGINE_REMOVED = "engine.removed"
    #: A room's SLIM channel came up (backend start, or first use). Engines use
    #: it to re-install hooks for manifests written while the backend was down.
    ROOM_PROVISIONED = "room.provisioned"


@dataclass(frozen=True)
class RoomEventContext:
    """What a lifecycle listener is told."""

    event: RoomEvent
    room: str
    #: The engine handle the event concerns, when it concerns one.
    handle: str | None = None
    #: That engine's manifest ``kind``, when known at emit time.
    kind: str | None = None


Listener = Callable[[RoomEventContext], None]

#: Extension point: filter which ``@``-mentions in a message are genuine summons.
#: Signature ``(SummonContext) -> Awaitable[Mapping[str, str]]``, mapping each
#: candidate handle to ``"wake"`` or ``"mention"`` (see
#: :mod:`app.services.summonguard`).
SUMMON_FILTER = "summon.filter"


class RoomLifecycle:
    """Process-wide event bus + per-room hook registry.

    In-memory and per-process by design: hooks are derived state, rebuilt from
    the room's manifests on the next ``ROOM_PROVISIONED``, exactly like the link
    index is rebuilt from the markdown.
    """

    def __init__(self) -> None:
        self._listeners: dict[RoomEvent, list[Listener]] = defaultdict(list)
        # (room, hook name) -> {owner handle: function}
        self._hooks: dict[tuple[str, str], dict[str, Any]] = {}

    # -- events --

    def subscribe(self, event: RoomEvent, listener: Listener) -> None:
        """Register ``listener`` for ``event``. Idempotent per callable."""
        listeners = self._listeners[event]
        if listener not in listeners:
            listeners.append(listener)

    def emit(
        self, event: RoomEvent, room: str, *, handle: str | None = None, kind: str | None = None
    ) -> None:
        """Announce ``event`` on ``room``; never raises into the caller."""
        listeners = self._listeners.get(event)
        if not listeners:
            return
        ctx = RoomEventContext(event=event, room=room, handle=handle, kind=kind)
        for listener in list(listeners):
            try:
                listener(ctx)
            except Exception:
                logger.exception("lifecycle listener failed for %s on room %s", event, room)

    # -- room hooks --

    def install(self, room: str, hook: str, owner: str, fn: Any) -> None:
        """Install ``fn`` as ``room``'s ``hook``, owned by engine ``owner``."""
        slot = self._hooks.setdefault((room, hook), {})
        first = owner not in slot
        slot[owner] = fn
        if first:
            logger.info("room %s: @%s installed the %s hook", room, owner, hook)

    def uninstall(self, room: str, hook: str, owner: str) -> None:
        """Remove ``owner``'s ``hook`` from ``room`` (no-op when absent)."""
        slot = self._hooks.get((room, hook))
        if not slot or slot.pop(owner, None) is None:
            return
        logger.info("room %s: @%s removed the %s hook", room, owner, hook)
        if not slot:
            self._hooks.pop((room, hook), None)

    def hooks(self, room: str, hook: str) -> list[Any]:
        """Every function installed as ``room``'s ``hook``, install order."""
        return list(self._hooks.get((room, hook), {}).values())

    def owners(self, room: str, hook: str) -> list[str]:
        """The engine handles that installed ``room``'s ``hook``."""
        return list(self._hooks.get((room, hook), {}))

    def clear(self) -> None:
        """Drop every listener and hook (tests)."""
        self._listeners.clear()
        self._hooks.clear()


#: The process-wide lifecycle. Engines subscribe at startup (``main.py``); the
#: memory-write path and the channel manager emit.
lifecycle = RoomLifecycle()
