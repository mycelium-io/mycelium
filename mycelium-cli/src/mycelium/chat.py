# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Posting into a channel and reading it back, wherever the verb was typed.

``mycelium room send`` and ``mycelium board send`` are the same write, and
``room messages`` and ``board messages`` are the same read.  What differs is one
argument: a **thread** — the episode URN of a task — narrows both to that
task's conversation instead of the room's.  A thread is a tag over the room's own
channel, not a second transport, so one implementation handles both scoped and
room-wide reads/writes.

So the surface is chosen by the caller and the transport lives here.  The board's
verbs are the room's verbs, scoped to a row.
"""

from __future__ import annotations

import json as json_module
from typing import TYPE_CHECKING, Any

import typer

from mycelium.client import typed_client as _typed_client

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def post(
    config: MyceliumConfig,
    room_name: str,
    *,
    sender_handle: str,
    content: str,
    episode: str | None = None,
    destination: str | None = None,
    json_output: bool = False,
) -> None:
    """Post a broadcast into a room, or into one thread inside it.

    ``destination`` is what the confirmation line calls where it landed; it says
    the row a board send was scoped to, which the room name alone would not.
    """
    from mycelium_backend_client.api.messages import (
        send_message_api_rooms_room_name_messages_post as send_api,
    )
    from mycelium_backend_client.models import MessageCreate, MessageCreateMessageType
    from mycelium_backend_client.types import UNSET

    with _typed_client(config) as client:
        body = MessageCreate(
            sender_handle=sender_handle,
            message_type=MessageCreateMessageType.BROADCAST,
            content=content,
            episode=episode or UNSET,
        )
        result = send_api.sync(room_name=room_name, client=client, body=body)

    if json_output and result:
        msg_dict = result.to_dict() if hasattr(result, "to_dict") else str(result)
        typer.echo(json_module.dumps(msg_dict, indent=2, default=str))
        return

    preview = content[:80] + ("…" if len(content) > 80 else "")
    typer.echo(f"  ↑  {sender_handle} → {destination or room_name}: {preview}")


def read(
    config: MyceliumConfig,
    room_name: str,
    *,
    limit: int,
    sender: str | None = None,
    message_type: str | None = None,
    episode: str | None = None,
    label: str | None = None,
    empty_note: str | None = None,
    json_output: bool = False,
) -> None:
    """Print a channel's recent messages, newest first.

    With ``episode`` this is one thread's transcript and nothing else — the point
    of a thread being that the room stays legible while the argument happens
    somewhere a reader can still open.
    """
    from mycelium.commands.room import _agent_owner_map
    from mycelium_backend_client.api.messages import (
        list_messages_api_rooms_room_name_messages_get as list_api,
    )
    from mycelium_backend_client.models import HTTPValidationError
    from mycelium_backend_client.types import UNSET

    with _typed_client(config) as client:
        result = list_api.sync(
            room_name=room_name,
            client=client,
            limit=limit,
            sender=sender or UNSET,
            message_type=message_type or UNSET,
            episode=episode or UNSET,
        )

    msgs = [] if not result or isinstance(result, HTTPValidationError) else result.messages

    if json_output:
        payload: dict[str, Any] = (
            result.to_dict()
            if result and not isinstance(result, HTTPValidationError)
            else {"messages": [], "total": 0}
        )
        typer.echo(json_module.dumps(payload, indent=2, default=str))
        return

    where = label or room_name
    if not msgs:
        typer.echo(f"  {where}: {empty_note or 'no messages'}")
        return

    plural = "message" if len(msgs) == 1 else "messages"
    owners = _agent_owner_map(room_name)
    typer.secho(f"\n  {where}  ", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho(f"({len(msgs)} {plural}, newest first)\n", fg=typer.colors.BRIGHT_BLACK)
    for m in msgs:
        stamp = m.created_at.strftime("%H:%M:%S")
        # Show the full message; this is the read-the-transcript command, so
        # never truncate. Keep multi-line content readable by indenting any
        # continuation lines under the first.
        first, *rest = (m.content or "").split("\n")
        owner = owners.get(m.sender_handle)
        own = f" owned by @{owner}" if owner else ""
        edited = " (edited)" if getattr(m, "edited_at", None) else ""
        typer.echo(
            f"  {stamp}  {m.sender_handle}{own} [{m.message_type}]"
            f"  {str(m.id)[:8]}: {first}{edited}"
        )
        for line in rest:
            typer.echo(f"              {line}")
    typer.echo()
