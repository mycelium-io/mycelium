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
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import typer

from mycelium.client import answered
from mycelium.client import typed_client as _typed_client
from mycelium.names import who

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
    from mycelium_backend_client.models import MessageCreate, MessageCreateMessageType, MessageRead
    from mycelium_backend_client.types import UNSET

    with _typed_client(config) as client:
        body = MessageCreate(
            sender_handle=sender_handle,
            message_type=MessageCreateMessageType.BROADCAST,
            content=content,
            episode=episode or UNSET,
        )
        result = answered(
            send_api.sync_detailed(room_name=room_name, client=client, body=body), MessageRead
        )

    if json_output:
        typer.echo(json_module.dumps(result.to_dict(), indent=2, default=str))
        return

    preview = content[:80] + ("…" if len(content) > 80 else "")
    typer.echo(f"  ↑  {sender_handle} → {destination or room_name}: {preview}")


_RELATIVE = re.compile(r"^(\d+)\s*([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_stamp(text: str, *, now: datetime | None = None) -> datetime:
    """A point in time as a reader types one: an ISO 8601 stamp, or an age.

    ``2026-09-03T16:40:00Z`` is the shape every message line's cursor comes back
    in, so a stamp copied off one page pastes straight into the next. ``2h``,
    ``30m``, ``1d`` mean that long ago, for the common "what happened before
    lunch" read where nobody has a stamp yet. Naive stamps are taken as UTC,
    which is how the hub records them.
    """
    raw = text.strip()
    match = _RELATIVE.match(raw)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return (now or datetime.now(UTC)) - timedelta(**{_UNITS[unit]: amount})
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter(
            f"{text!r} is neither an ISO 8601 stamp nor an age like 2h, 30m or 1d"
        ) from exc
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def _checks(config: MyceliumConfig, room_name: str, *, since: datetime) -> dict[str, list[str]]:
    """The verifier's lines still shown in ``room_name``, by the message they go
    under. Empty when the room has none, or the hub has no verifier."""
    from mycelium_backend_client.api.verifier import (
        list_flags_api_rooms_room_name_verifier_flags_get as flags_api,
    )

    try:
        with _typed_client(config) as client:
            flags = answered(
                flags_api.sync_detailed(room_name=room_name, client=client, since=since), list
            )
    except Exception:  # noqa: BLE001 - a line under a message is never worth failing the read
        return {}
    from mycelium_backend_client.models import VerifierFlagRead

    out: dict[str, list[str]] = {}
    for flag in flags:
        if isinstance(flag, VerifierFlagRead) and flag.state == "shown":
            out.setdefault(flag.message_id, []).append(flag.line)
    return out


def readable(message_type: str, content: str) -> str:
    """The words a person reads for a message, never a raw protocol record.

    A memory update or the end of a negotiation arrives as its whole envelope
    (``l9_knowledge``, ``l9_commit``), which printed as a screen of JSON. The
    line it carries is what's said; one with none is named plainly.
    """
    if not message_type.startswith("l9_"):
        return content
    try:
        frame = json_module.loads(content)
    except ValueError:
        return content
    if not isinstance(frame, dict):
        return content
    text = frame.get("content")
    if isinstance(text, str) and text.strip():
        return text
    header = (frame.get("l9") or {}).get("header") or {}
    if message_type == "l9_commit":
        outcome = header.get("subkind") or "ended"
        return f"Negotiation {outcome}."
    if message_type == "l9_knowledge":
        data = ((frame.get("l9") or {}).get("payload") or {}).get("data") or {}
        return f"Memory updated: {data.get('key') or 'a memory'}."
    return f"({message_type.removeprefix('l9_')} record)"


#: Messages somebody said, drawn as boxes; anything else is a one-line record.
SAID_TYPES = frozenset({"broadcast", "direct", "announce", "delegate"})


#: Control characters, C0 and C1, except the tab: an escape in a message
#: would move the cursor back over the gutter in a terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def plain(text: str) -> str:
    """``text`` on one line: no control characters, its whitespace (every
    kind of line break included) run together."""
    return " ".join(_CONTROL.sub("", text).split())


def box(header: str, text: str, footer: str = "") -> list[str]:
    """``text`` as a box: the header, each line behind a ``│``, then the close.

    The same box the hub's wake draws (``wake_digest.box``): the gutter is on
    every line, every kind of line break starts a new one (U+2028 too), and
    control characters are dropped, so nothing a message says can pass for
    the frame around it, another message's header or a line of the CLI's own.
    """
    lines = [f"┌ {plain(header)}"]
    for line in text.splitlines() or [""]:
        line = _CONTROL.sub("", line.replace("\t", "    ")).rstrip()
        lines.append(f"│ {line}" if line.strip() else "│")
    lines.append(f"└ {plain(footer)}" if footer else "└")
    return lines


def read(
    config: MyceliumConfig,
    room_name: str,
    *,
    limit: int,
    sender: str | None = None,
    message_type: str | None = None,
    message_id: str | None = None,
    episode: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    label: str | None = None,
    empty_note: str | None = None,
    older_with: str | None = None,
    json_output: bool = False,
) -> None:
    """Print a channel's recent messages, newest first.

    Each message is a box, its text behind a ``│`` gutter, the way the hub's
    wake draws one; a record nobody said (a memory saved) is one quiet line.
    ``message_id`` reads one message, by the start of its id.

    With ``episode`` this is one thread's transcript and nothing else — the point
    of a thread being that the room stays legible while the argument happens
    somewhere a reader can still open.

    ``before`` is the backward cursor: a page defined by content rather than
    position, so walking back does not shift under messages arriving live.
    ``since`` bounds the other end. When the page is full and older messages
    exist, the footer names the command that reads the next page back
    (``older_with`` is that command's stem; the cursor is appended), and the
    JSON shape carries the same cursor as ``older_before``.
    """
    from mycelium.commands.room import _agent_owner_map
    from mycelium_backend_client.api.messages import (
        list_messages_api_rooms_room_name_messages_get as list_api,
    )
    from mycelium_backend_client.models import MessageListResponse
    from mycelium_backend_client.types import UNSET

    with _typed_client(config) as client:
        listed = answered(
            list_api.sync_detailed(
                room_name=room_name,
                client=client,
                limit=limit,
                sender=sender or UNSET,
                message_type=message_type or UNSET,
                episode=episode or UNSET,
                since=since or UNSET,
                before=before or UNSET,
                id=message_id or UNSET,
            ),
            MessageListResponse,
        )

    msgs = listed.messages
    # Newest first, so the last line is the oldest shown; ``total`` counts every
    # message the filters matched, so a total past the page means older ones exist.
    total = listed.total if msgs else 0
    older_before = msgs[-1].created_at.isoformat() if msgs and total > len(msgs) else None

    if json_output:
        payload: dict[str, Any] = listed.to_dict()
        payload["older_before"] = older_before
        typer.echo(json_module.dumps(payload, indent=2, default=str))
        return

    where = label or room_name
    if not msgs:
        typer.echo(f"  {where}: {empty_note or 'no messages'}")
        return

    plural = "message" if len(msgs) == 1 else "messages"
    owners = _agent_owner_map(room_name)
    checks = _checks(config, room_name, since=msgs[-1].created_at)
    typer.secho(f"\n  {where}  ", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho(f"({len(msgs)} {plural}, newest first)\n", fg=typer.colors.BRIGHT_BLACK)
    for m in msgs:
        stamp = m.created_at.strftime("%H:%M")
        rid = str(m.id)[:8]
        # Show the full message; this is the read-the-transcript command, so
        # never truncate.
        text = readable(str(m.message_type), m.content or "")
        if str(m.message_type) not in SAID_TYPES:
            # A memory saved, a negotiation ended: one quiet line, never a box,
            # so it can't be taken for something somebody said.
            first = next((ln for ln in text.splitlines() if ln.strip()), "")
            typer.secho(f"  · {stamp}  {first}  {rid}\n", fg=typer.colors.BRIGHT_BLACK)
            continue
        owner = owners.get(m.sender_handle)
        name = who(m.sender_handle)
        header = name if name != m.sender_handle else f"@{m.sender_handle}"
        if owner:
            header += f" (owned by @{owner})"
        if m.recipient_handle:
            header += f" → @{m.recipient_handle}"
        header += f" · {stamp} · {rid}"
        if getattr(m, "edited_at", None):
            header += " · edited"
        lines = box(header, text)
        typer.echo("\n".join(f"  {line}" for line in lines))
        for line in checks.get(str(m.id), []):
            typer.secho(f"    ⚠ verifier: {line}", fg=typer.colors.YELLOW)
        typer.echo()
    if older_before and older_with:
        remaining = total - len(msgs)
        typer.secho(
            f"\n  {remaining} older · {older_with} --before {older_before}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.echo()
