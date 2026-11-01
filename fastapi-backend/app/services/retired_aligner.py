# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The answer a room gets when it summons the aligner, which was retired.

Negotiation is the conductor's now (its ``concord`` and ``accord`` flows). A
room made before that can still hold an ``agents/aligner`` manifest, and a
summon of it would otherwise start nothing and say nothing. This handler sits
on the same summon seam as the engines and says, where it was asked, what to
run instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.services import message_format
from app.services.engine_kinds import norm, registered_engine_kind

if TYPE_CHECKING:
    from app.services.message_models import MyceliumMessage
    from app.services.room_channels import RoomChannelManager

logger = logging.getLogger(__name__)

#: The kind an ``agents/<handle>`` manifest named for the retired engine.
RETIRED_KIND = "aligner"

RETIRED_TEXT = (
    "The aligner was retired, so nothing started. To negotiate, run "
    '`mycelium board coordinate <row> conductor "concord …"` to help members '
    'agree, or `"accord …"` to get them on the same page.'
)


def _summons_retired(room: str, handle: str) -> bool:
    if registered_engine_kind(room, handle) == RETIRED_KIND:
        return True
    if norm(handle) != norm(settings.ALIGNER_HANDLE):
        return False
    from app.services.filesystem import get_room_dir

    return not (get_room_dir(room) / "agents" / f"{handle}.md").exists()


class RetiredAligner:
    """Answers a summon of a room's ``aligner`` manifest with what to run instead."""

    def __init__(self, manager: RoomChannelManager) -> None:
        self._manager = manager
        # Strong refs to scheduled posts so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

    def handle_summon(
        self,
        room: str,
        handle: str,
        envelope: MyceliumMessage,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        """Reply when ``handle``'s manifest names the retired kind, or when it is
        the aligner's usual handle and nobody in the room has that handle."""
        if not _summons_retired(room, handle):
            return
        from app.services.persister import envelope_sender

        sender = envelope_sender(envelope)
        if sender is not None and norm(sender) == norm(message_format.SYSTEM_ACTOR_ID):
            return
        managed = self._manager.get(room)
        if managed is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        where = envelope.header.message.episode if envelope.header.message else None
        env = message_format.build_envelope(
            kind=message_format.Kind.exchange,
            episode=where or message_format.live_episode_urn(room),
            sender=message_format.SYSTEM_ACTOR_ID,
            topic=message_format.topic_urn(room),
            payload_type="message",
        )
        task = loop.create_task(managed.post(env, RETIRED_TEXT))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
