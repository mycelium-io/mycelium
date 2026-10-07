# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
What a woken agent is told: a digest of what happened while it was away.

A wake is typed into the agent's terminal by its host (herdr, Omnigent). It
used to be a doorbell ("you have messages, go read the room"), which left the
agent to rebuild where it was before it could act. The reader is a model that
can take in a lot at once, so the digest gives it the picture up front, laid
out like a mailing-list digest: a few ``Label: value`` lines (why it woke,
what changed since its last turn, its tasks, the board), then the messages
that asked for it, each under a ``---`` line with who, when and how long, cut
with an exact count of what's left out. It ends on the commands to read the
rest and to reply. ``await`` still hands over everything in full; the digest
is for knowing what you're walking into.

Built when the wake is delivered, not when it was queued, since a wake can wait
while its agent is busy and the room moves on meanwhile.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.services import assignments, message_format
from app.services.agent_registry import norm_handle
from app.services.persister import _conversational_text, parse_recorded_at, record_episode

#: How much of each message the digest carries. The latest is usually the ask;
#: the ones before it are context.
LATEST_CHARS = 700
EARLIER_CHARS = 280
#: How many messages that asked for the agent are shown, newest kept.
SHOWN = 3
#: How many of the agent's own tasks are listed.
TASKS_SHOWN = 5
#: How far back the transcript is read for the agent's last turn.
SCAN = 2000


def _norm(handle: str | None) -> str:
    return norm_handle(handle or "") or ""


def age(then: datetime | None, now: datetime) -> str:
    """How long ago, as the digest says it: now, 4m ago, 2h ago, 3d ago."""
    if then is None:
        return "a while ago"
    minutes = int(max(0.0, (now - then).total_seconds()) // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def cut(text: str, limit: int) -> str:
    """``text`` up to ``limit`` characters, ending on a word, with the rest counted."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ")
    if space > limit * 0.6:
        head = head[:space]
    head = head.rstrip()
    return f"{head}… [+{len(text) - len(head):,} chars]"


def _where(room: str, episode: str | None) -> tuple[str, str] | None:
    """The ``(key, title)`` of the task a thread belongs to; ``None`` for the room."""
    if not episode or message_format.is_live_episode(room, episode):
        return None
    from app.services.tasks import row_of_episode

    try:
        return row_of_episode(room, episode)
    except Exception:  # a digest without a place is still a digest
        return None


def _place(room: str, where: tuple[str, str] | None) -> str:
    return f'"{where[1]}" ({where[0]})' if where else f"the room ({room})"


def _rows(room: str) -> list[tuple[str, dict, str]]:
    from app.services.filesystem import get_room_dir, list_memory_files, room_exists

    if not room_exists(room):
        return []
    return [
        (key, meta, content)
        for key, meta, content in list_memory_files(get_room_dir(room), limit=None)
        if assignments.assignable(key)
    ]


def _title(key: str, content: str) -> str:
    first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
    return first.lstrip("# ").strip()


def board(room: str, handle: str, now: datetime) -> tuple[list[str], str]:
    """The agent's own open tasks, and the room's board as a tally of what's live."""
    me = _norm(handle)
    mine: list[str] = []
    tally: Counter[str] = Counter()
    for key, meta, content in _rows(room):
        if assignments.settled(meta, now):
            continue
        state = assignments.state_of(meta, now)
        blocked = meta.get("blocked_by")
        word = (
            "blocked"
            if blocked
            else {"held": "claimed", "unclaimed": "new", "released": "released"}.get(state, state)
        )
        tally[word] += 1
        holder = _norm(meta.get("owner")) if state == "held" else ""
        if me not in (holder, _norm(meta.get("assignee"))):
            continue
        title = _title(key, content)
        if blocked:
            mine.append(f'blocked "{title}" (waiting on {blocked})')
        elif state == "held":
            since = assignments._parse(meta.get("claimed_at"))
            mine.append(f'claimed "{title}" ({age(since, now)})')
        else:
            mine.append(f'{word} "{title}" (for you, unclaimed)')
    order = ["claimed", "blocked", "new", "released", "expired"]
    parts = [f"{tally[w]} {w}" for w in order if tally[w]]
    return mine, ", ".join(parts) or "nothing open"


def build(room: str, wake: dict[str, Any], records: list[Any], now: datetime | None = None) -> str:
    """The digest typed into ``wake``'s agent: why, what changed, what asked for it."""
    from app.routes.participate import _addressed_to

    now = now or datetime.now(UTC)
    handle = str(wake.get("handle") or "")
    me = _norm(handle)
    reason = wake.get("reason") or "mention"
    window = records[-SCAN:]

    # Since its last turn: after the last thing it said.
    last = max((i for i, r in enumerate(window) if _norm(r.sender) == me), default=-1)
    since = window[last + 1 :]
    last_at = parse_recorded_at(window[last].recorded_at) if last >= 0 else None

    asked = [
        r for r in since if _addressed_to(r.content, handle) and _conversational_text(r.content)
    ]
    episode = record_episode(asked[-1]) if asked else wake.get("episode")
    where = _where(room, episode)

    def place_of(record: Any) -> str | None:
        ep = record_episode(record)
        return None if not ep or message_format.is_live_episode(room, ep) else ep

    here = place_of(asked[-1]) if asked else None
    said = [r for r in since if _conversational_text(r.content)]
    in_here = [r for r in said if place_of(r) == here]
    elsewhere = len(said) - len(in_here)
    moves = sum(
        1
        for r in since
        if ((r.content.get("l9") or {}).get("payload") or {}).get("type")
        == message_format.NOTICE_PAYLOAD_TYPE
    )
    by = Counter(r.sender for r in in_here if r.sender)

    lines = [f"mycelium wake for @{me} in {room}", ""]

    # Why it woke.
    sender = f"@{wake['from']}" if wake.get("from") else "someone"
    if reason == "assigned":
        task = f'"{wake.get("title") or wake.get("key")}" ({wake.get("key")})'
        why = f"{sender} gave you a task: {task}"
    elif reason == "turn":
        who = f"@{asked[-1].sender}" if asked and asked[-1].sender else sender
        why = f"it's your turn in {_place(room, where)}; {who} is asking"
    else:
        n = len(asked)
        latest = f", latest {age(parse_recorded_at(asked[-1].recorded_at), now)}" if asked else ""
        count = f"{n} messages mention" if n > 1 else f"{sender} mentioned"
        why = f"{count} you in {_place(room, where)}{latest}"
    lines.append(f"Why:     {why}")

    # What changed since its last turn.
    who = ", ".join(f"@{h} {c}" for h, c in by.most_common())
    first = f"your last turn, {age(last_at, now)}" if last >= 0 else "you joined"
    here_word = "this thread" if here else "the room"
    changed = f"{len(in_here)} in {here_word}" + (f" ({who})" if who else "")
    rest = [changed]
    if elsewhere:
        rest.append(f"{elsewhere} elsewhere in the room")
    if moves:
        rest.append(f"{moves} board {'move' if moves == 1 else 'moves'}")
    lines.append(f"Since:   {first}: " + ", ".join(rest))

    mine, tally = board(room, handle, now)
    if mine:
        lines.append(f"Tasks:   {mine[0]}")
        lines.extend(f"         {t}" for t in mine[1:TASKS_SHOWN])
        if len(mine) > TASKS_SHOWN:
            lines.append(f"         and {len(mine) - TASKS_SHOWN} more")
    lines.append(f"Board:   {tally}")
    # What the team agreed for the task it's about, so it works to that.
    task_key = wake.get("key") if reason == "assigned" else (where[0] if where else None)
    if task_key:
        from app.services import agreed

        pointers = agreed.pointer(room, str(task_key))
        if pointers:
            lines.append(f"Agreed:  {pointers[0]}")
            lines.extend(f"         {p}" for p in pointers[1:])

    # The messages that asked for it, newest kept, the latest given the most room.
    shown = asked[-SHOWN:]
    if len(asked) > len(shown):
        lines += ["", f"({len(asked) - len(shown)} earlier ones asking for you aren't shown)"]
    for i, record in enumerate(shown):
        latest = i == len(shown) - 1
        text = (_conversational_text(record.content) or "").strip()
        at = age(parse_recorded_at(record.recorded_at), now)
        tag = ", latest" if latest else ""
        lines += ["", f"--- @{record.sender}, {at}, {len(text):,} chars{tag} ---"]
        lines.append(cut(text, LATEST_CHARS if latest else EARLIER_CHARS))

    lines.append("")
    if reason == "assigned" and wake.get("key"):
        key = wake["key"]
        lines += [
            f"Claim:  mycelium board claim {key} --room {room} --to @{me}",
            f"Read:   mycelium board messages {key} --room {room}",
            f'Post:   mycelium board send {key} --room {room} --as {me} --body "..."',
        ]
    else:
        more = len(since) and len(said) - len(shown)
        noun = "message" if more == 1 else "messages"
        extra = f", plus {more} other {noun} since your last turn" if more > 0 else ""
        # The target is named outright: ``respond`` lands in a task's thread only
        # with ``--task``, and in the room without it, whatever ``await`` handed
        # over last. A thread no row carries can't be named, so its reply goes
        # to the room, and the line says so.
        task = f" --task {where[0]}" if here and where else ""
        lands = f'"{where[1]}"' if here and where else "the room"
        lines += [
            f"First:  mycelium await --room {room} --handle {me} --json --timeout 5",
            f"        (everything above in full{extra}; it marks these read and tells"
            " the room you're on it)",
            f'Reply:  mycelium respond --room {room} --handle {me}{task} --body "..."   (lands in {lands})',
        ]
    # One line, so an agent that needs more than this digest holds knows the
    # room's whole history can be asked rather than paged through.
    lines.append(
        f'Find:   mycelium room search "<words> from:<handle> task:<row> after:1d" --room {room}'
        "   (any message, any field; --facets for counts)"
    )
    return "\n".join(lines)
