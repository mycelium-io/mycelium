# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The "is responding…" signal: a participant is generating, right now.

The channel renders discrete events — a reply lands, a tick, a consensus — and
between them the room is silent even when someone is mid-turn: the aligner
running a Pi round, a resident agent that just took an ``await`` wake and has
not yet posted its ``respond``. This is the presence-style signal that fills
that gap, and it is deliberately **not a message**.

It rides the in-process bus only (:mod:`app.bus`, so the SSE stream and
nothing else), never the transcript, never ``in_memory_store``: a typing
indicator that survived a reload as a line in the room would be a lie about
what was said. A frame carries the handle, whether it started or finished, the
thread it is in, and a TTL — a reader drops a ``responding`` it has heard nothing
about for that long, so a turn that dies mid-generation cannot leave a stuck
indicator behind. The seams that raise it are the ones that already know the
window: ``await`` returning a turn and ``reply`` posting one
(:mod:`app.routes.participate`), and the aligner's own LLM calls
(:meth:`app.services.aligner.Aligner._open_llm_session`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.bus import bus, room_channel

#: The frame's ``type``/``message_type``. Not an L9 kind and not a raise-up type:
#: the GUI intercepts it before its message parser, the CLI's ``room watch``
#: drops a frame with no ``content``, and the notification classifier ignores
#: what it does not name.
ACTIVITY_TYPE = "agent_activity"

State = Literal["responding", "done"]

#: How long a ``responding`` stands with no ``done`` and no message from the
#: handle before a reader treats it as stale. Generous for a Pi turn, short
#: enough that a dead turn does not sit there all afternoon. Carried on the
#: frame so the two sides never disagree about it.
TTL_S = 90


def signal(room: str, handle: str, state: State, *, episode: str | None = None) -> dict[str, Any]:
    """Publish one activity frame on the room's bus channel. Returns the frame."""
    frame: dict[str, Any] = {
        "type": ACTIVITY_TYPE,
        "message_type": ACTIVITY_TYPE,
        "room_name": room,
        "sender_handle": handle,
        "handle": handle,
        "state": state,
        "episode": episode,
        "ttl_s": TTL_S,
        "created_at": datetime.now(UTC).isoformat(),
    }
    bus.publish(room_channel(room), frame)
    return frame
