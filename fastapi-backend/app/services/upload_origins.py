# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Where each of a room's uploads was posted: the message that linked it.

A file sent from a message box is uploaded first and linked from the message
as ``[[uploads/<name>]]``, so the message is the only record of where it went.
This reads the room's history once and keeps, for each upload key, the
message it was posted with: the uploader's own first message that links it,
or, when they never linked it themselves (an agent uploads with the CLI and a
teammate shares the link), the first message from anyone. It says who sent it,
when, and the task whose thread it was said in (none when it was said in the
room's channel). An upload saved straight to memory, or one no message links
any more, has none. Who *added* the file is the upload's own ``created_by``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas import PROSE_MESSAGE_TYPES
from app.services import message_format, message_search, persister, uploads

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class Origin:
    message_id: str
    sender: str
    at: datetime
    #: The thread it was said in, or ``None`` for the channel.
    episode: str | None
    #: That thread's board row, by key and title, when a row carries it.
    task: str | None
    task_title: str | None


def origins(room: str, uploaders: dict[str, str] | None = None) -> dict[str, Origin]:
    """``upload key → Origin`` for every upload a message in ``room`` links.

    ``uploaders`` maps a key to who added the upload; their own message wins
    over an earlier one from someone else.
    """
    uploaders = uploaders or {}
    live = message_format.live_episode_urn(room)
    rows = message_search.thread_rows(room)
    first: dict[str, Origin] = {}
    own: dict[str, Origin] = {}
    for m in sorted(persister.room_conversation(room), key=lambda m: m.created_at):
        if m.message_type not in PROSE_MESSAGE_TYPES:
            continue
        keys = [k for k in uploads.linked_keys(m.content or "") if k not in own]
        if not keys:
            continue
        thread = m.episode if m.episode and m.episode != live else None
        row = rows.get(thread) if thread else None
        origin = Origin(
            message_id=str(m.id),
            sender=m.sender_handle,
            at=m.created_at,
            episode=thread,
            task=row[0] if row else None,
            task_title=row[1] if row else None,
        )
        for key in keys:
            first.setdefault(key, origin)
            if uploaders.get(key) == m.sender_handle:
                own[key] = origin
    return first | own
