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
from app.services.words import a_or_an

#: How much of each message the digest carries. The latest is usually the ask;
#: the ones before it are context.
LATEST_CHARS = 700
EARLIER_CHARS = 280
#: How many messages that asked for the agent are shown, newest kept.
SHOWN = 3
#: How many of the agent's own tasks are listed.
TASKS_SHOWN = 5
#: How many changes to the board are listed, newest kept.
CHANGES_SHOWN = 5
#: How many rows the tally names behind a count someone has to act on.
NAMED = 3
#: How much of a task's title a change line or the tally carries.
TITLE_CHARS = 48
NAME_CHARS = 32
#: The notices that say the board moved. ``floor`` is whose turn it is in a
#: thread, which is not the board's news; ``upstream`` is a row's pull request
#: changing, which :func:`moves` says in its own words.
BOARD_NOTICES = message_format.NOTICE_SUBKINDS - {"floor", "upstream"}
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


def _short(title: str, limit: int) -> str:
    """A title cut to ``limit`` characters on a word, ending in an ellipsis."""
    title = " ".join(title.split())
    if len(title) <= limit:
        return title
    head = title[: limit - 1]
    space = head.rfind(" ")
    return (head[:space] if space > limit * 0.6 else head).rstrip(" ,.;:") + "…"


def _board_notice(record: Any) -> dict[str, Any] | None:
    """The notice ``record`` carries, when it is one about a task on the board."""
    payload = (record.content.get("l9") or {}).get("payload") or {}
    if payload.get("type") != message_format.NOTICE_PAYLOAD_TYPE:
        return None
    data = payload.get("data") or {}
    return data if data.get("subkind") in BOARD_NOTICES else None


def change(data: dict[str, Any]) -> str:
    """One board change as the digest says it: who did what to which task."""
    subkind = str(data["subkind"])
    title = f'"{_short(str(data.get("title") or data.get("key") or "a task"), TITLE_CHARS)}"'
    by = _norm(data.get("by"))
    who = f"@{by}" if by and by != assignments.RUNTIME_AUTHOR else ""
    if subkind == "expired":
        return f"{title} expired" + (f", {who} stopped renewing" if who else "")
    if subkind == "quiet":
        return f"{title} has gone quiet" + (f" ({data['why']})" if data.get("why") else "")
    if not who:
        return f"{title} {subkind}"
    verb = subkind
    if subkind == "filed" and data.get("kind") and data["kind"] != "task":
        verb = f"filed {a_or_an(str(data['kind']))}"
    to = _norm(data.get("for"))
    return f"{who} {verb} {title}" + (f" for @{to}" if subkind == "filed" and to else "")


def changes(since: list[Any]) -> list[str]:
    """What happened on the board in ``since``, newest first."""
    return [change(data) for data in map(_board_notice, reversed(since)) if data]


def board(room: str, handle: str, now: datetime) -> tuple[list[str], str]:
    """The agent's own open tasks, and the room's board as a tally of what's live.

    The tally names the rows behind ``blocked`` and ``expired``, since those are
    the ones someone has to do something about.
    """
    me = _norm(handle)
    mine: list[str] = []
    tally: Counter[str] = Counter()
    named: dict[str, list[str]] = {"blocked": [], "expired": []}
    for key, meta, content in _rows(room):
        if assignments.settled(meta, now):
            continue
        state = assignments.state_of(meta, now)
        blocked = meta.get("blocked_by")
        word = (
            "blocked"
            if blocked
            else {"held": "held", "unclaimed": "new", "released": "released"}.get(state, state)
        )
        tally[word] += 1
        title = _title(key, content)
        if word in named:
            named[word].append(_short(title, NAME_CHARS))
        holder = _norm(assignments.holder(meta, now))
        if me not in (holder, _norm(meta.get("assignee"))):
            continue
        if blocked:
            mine.append(f'blocked "{title}" (waiting on {blocked})')
        elif state == "held" and holder == me:
            # Given to it, or claimed by it: either way it's holding the row (#1136).
            claimed = meta.get("assignment") == "held"
            since = assignments._parse(meta.get("claimed_at") or meta.get("created_at"))
            verb = "claimed" if claimed else "yours"
            mine.append(f'{verb} "{title}" ({age(since, now)})')
        elif state == "held":
            mine.append(f'"{title}" is for you, but @{holder} holds it')
        else:
            mine.append(f'{word} "{title}" (for you; nobody holds it)')
    order = ["held", "blocked", "new", "released", "expired"]
    parts = [f"{tally[w]} {w}{_names(named.get(w, []))}" for w in order if tally[w]]
    return mine, ", ".join(parts) or "nothing open"


def _names(titles: list[str]) -> str:
    """`` (A, B, C and 2 more)`` for the rows behind a count, or nothing."""
    if not titles:
        return ""
    shown = ", ".join(titles[:NAMED])
    more = f" and {len(titles) - NAMED} more" if len(titles) > NAMED else ""
    return f" ({shown}{more})"


#: How each ``upstream`` change reads, around the row's quoted title.
UPSTREAM_LINES = {
    "opened": "pull request opened on {title}",
    "review_requested": "review requested on {title}",
    "approved": "{title} approved",
    "changes_requested": "changes requested on {title}",
    "ci_failed": "CI went red on {title}",
    "ci_passed": "CI went green on {title}",
    "merged": "{title} merged",
    "closed": "{title} closed without merging",
}


def upstream_line(data: dict[str, Any], when: datetime | None, now: datetime) -> str:
    """One ``upstream`` notice as the digest says it:
    ``CI went red on "Turn on Apple Pay" (acme/shop#12, 4m ago)``."""
    change = str(data.get("change") or "")
    title = f'"{_short(str(data.get("title") or data.get("key") or "a task"), TITLE_CHARS)}"'
    line = UPSTREAM_LINES.get(change, f"{change} on {{title}}").format(title=title)
    who = [w for w in str(data.get("who") or "").split(",") if w]
    if change == "review_requested" and who:
        line += " from " + ", ".join(f"@{w}" for w in who)
    ref = data.get("ref")
    return f"{line} ({ref}, {age(when, now)})" if ref else f"{line} ({age(when, now)})"


def _upstream_notice(record: Any) -> dict[str, Any] | None:
    """The notice ``record`` carries, when it says a row's pull request changed."""
    payload = (record.content.get("l9") or {}).get("payload") or {}
    if payload.get("type") != message_format.NOTICE_PAYLOAD_TYPE:
        return None
    data = payload.get("data") or {}
    return data if data.get("subkind") == "upstream" else None


def moves(room: str, handle: str, since: list[Any], now: datetime) -> list[str]:
    """Everything that moved in ``since``, newest first: the board's changes and
    the changes to the pull requests behind the agent's rows, in one list.

    A pull request is only the agent's news on a row it holds, was given or
    filed: a review asked for on someone else's row is theirs to hear about. A
    merge is everyone's, since work landing changes what the room builds on.
    """
    from app.services.filesystem import get_room_dir, read_memory_file

    me = _norm(handle)
    mine: dict[str, bool] = {}

    def is_mine(key: str) -> bool:
        if key not in mine:
            found = read_memory_file(get_room_dir(room), key) if key else None
            meta = found[0] if found else {}
            people = (meta.get("owner"), meta.get("assignee"), meta.get("created_by"))
            mine[key] = me in {_norm(str(p)) for p in people if p}
        return mine[key]

    lines: list[str] = []
    for record in reversed(since):
        board_data = _board_notice(record)
        if board_data:
            lines.append(change(board_data))
            continue
        data = _upstream_notice(record)
        if not data:
            continue
        if data.get("change") != "merged" and not is_mine(str(data.get("key") or "")):
            continue
        when = parse_recorded_at(str(data["at"])) if data.get("at") else None
        lines.append(upstream_line(data, when or parse_recorded_at(record.recorded_at), now))
    return lines


def _schedule_lines(room: str, name: str) -> tuple[list[str], str | None]:
    """The schedule's prompt and its latest findings, as the owner is told them,
    and the line saying how to change it, which the digest puts last."""
    from app.services import schedules

    try:
        schedule = schedules.get(room, name)
    except schedules.ScheduleError:
        return [], None
    change = schedules.change_line(schedule, room)
    run = schedule.history[0] if schedule.history else None
    if run is None:
        return ([schedule.prompt] if schedule.prompt else []), change
    return schedules.wake_text(schedule, run, room, change=False).splitlines()[1:], change


def _thread_of(room: str, record: Any) -> str | None:
    """The thread ``record`` was said in; ``None`` for the room itself."""
    ep = record_episode(record)
    return None if not ep or message_format.is_live_episode(room, ep) else ep


def _reply_thread(room: str, asked: list[Any]) -> str | None:
    """Where the digest tells its agent to reply: the thread of the newest
    message that asked for it, or the room (``None``) when none did. The
    digest's ``Reply:`` line and the room's "is responding in" line both come
    from here, so they can't disagree."""
    return _thread_of(room, asked[-1]) if asked else None


def reply_episode(room: str, wake: dict[str, Any], records: list[Any]) -> str | None:
    """The thread ``wake``'s agent is told to reply in, for the room's "is
    responding in" line; ``None`` for the room itself (:func:`_reply_thread`)."""
    _, _, _, asked = _since(str(wake.get("handle") or ""), records)
    return _reply_thread(room, asked)


def _since(handle: str, records: list[Any]) -> tuple[list[Any], int, list[Any], list[Any]]:
    """What happened since ``handle``'s last turn: the window read, the index of
    its last message in it (-1 for none), the records after it, and the ones
    among them that asked for it."""
    from app.routes.participate import _addressed_to

    me = _norm(handle)
    window = records[-SCAN:]
    # Since its last turn: after the last thing it said.
    last = max((i for i, r in enumerate(window) if _norm(r.sender) == me), default=-1)
    since = window[last + 1 :]
    asked = [
        r for r in since if _addressed_to(r.content, handle) and _conversational_text(r.content)
    ]
    return window, last, since, asked


def coverage(wake: dict[str, Any], records: list[Any]) -> dict[str, Any]:
    """Which messages a wake covers, as ids: the ones that asked for its agent,
    and the range its digest summarized (from just after its last turn to the
    newest). Text stays in the transcript; the wake log keeps these."""
    _, _, since, asked = _since(str(wake.get("handle") or ""), records)
    covered: dict[str, Any] = {"messages": [r.message_id for r in asked]}
    if since:
        covered["range"] = [since[0].message_id, since[-1].message_id]
    return covered


def build(room: str, wake: dict[str, Any], records: list[Any], now: datetime | None = None) -> str:
    """The digest typed into ``wake``'s agent: why, what changed, what asked for it."""
    now = now or datetime.now(UTC)
    handle = str(wake.get("handle") or "")
    me = _norm(handle)
    reason = wake.get("reason") or "mention"
    window, last, since, asked = _since(handle, records)
    last_at = parse_recorded_at(window[last].recorded_at) if last >= 0 else None
    episode = record_episode(asked[-1]) if asked else wake.get("episode")
    where = _where(room, episode)

    def place_of(record: Any) -> str | None:
        return _thread_of(room, record)

    here = _reply_thread(room, asked)
    said = [r for r in since if _conversational_text(r.content)]
    in_here = [r for r in said if place_of(r) == here]
    elsewhere = len(said) - len(in_here)
    by = Counter(r.sender for r in in_here if r.sender)

    lines = [f"mycelium wake for @{me} in {room}", ""]

    # Why it woke.
    sender = f"@{wake['from']}" if wake.get("from") else "someone"
    if reason == "assigned":
        task = f'"{wake.get("title") or wake.get("key")}" ({wake.get("key")})'
        why = f"{sender} gave you a task: {task}"
    elif reason == "schedule":
        why = f'your schedule "{wake.get("title")}" fired'
    elif reason == "turn":
        who = f"@{asked[-1].sender}" if asked and asked[-1].sender else sender
        why = f"it's your turn in {_place(room, where)}; {who} is asking"
    elif reason == "interrupt":
        # Its turn was probably stopped to deliver this, so say why: without it an
        # agent reads the stop as "the person stopped me" and waits. Worded as
        # what was sent, since the hub only knows the key was asked for (the
        # agent may have gone idle first, or its runner may predate interrupts).
        why = (
            f"{sender} sent you an urgent message with @! in {_place(room, where)}, "
            "which stops your turn if you were working. Read it and act on it, then "
            "carry on with what you were doing unless it says otherwise."
        )
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
    lines.append(f"Since:   {first}: " + ", ".join(rest))
    # Someone else pausing one of its schedules is said here, once, rather than
    # with a message that woke it (the herdr-wakes route marks it said).
    from app.services import schedules

    lines += [
        f"Schedule: {schedules.pause_line(s, room, now)}"
        for s in schedules.untold_pauses(room, handle)
    ]

    mine, tally = board(room, handle, now)
    if mine:
        lines.append(f"Tasks:   {mine[0]}")
        lines.extend(f"         {t}" for t in mine[1:TASKS_SHOWN])
        if len(mine) > TASKS_SHOWN:
            lines.append(f"         and {len(mine) - TASKS_SHOWN} more")
    # What changed on the board since its last turn, and on the pull requests
    # behind its rows, then what's open now, so the agent doesn't have to read
    # the board to learn what moved.
    moved = moves(room, handle, since, now)
    if moved:
        lines.append(f"Board:   {moved[0]}")
        lines.extend(f"         {c}" for c in moved[1:CHANGES_SHOWN])
        if len(moved) > CHANGES_SHOWN:
            lines.append(f"         and {len(moved) - CHANGES_SHOWN} more")
        lines.append(f"         open now: {tally}")
    else:
        lines.append(f"Board:   {tally}")
    # What the team agreed for the task it's about, so it works to that.
    task_key = wake.get("key") if reason == "assigned" else (where[0] if where else None)
    if task_key:
        from app.services import agreed

        pointers = agreed.pointer(room, str(task_key))
        if pointers:
            lines.append(f"Agreed:  {pointers[0]}")
            lines.extend(f"         {p}" for p in pointers[1:])

    # What the schedule says to do, and what its pre-check found.
    schedule_change = None
    if reason == "schedule" and wake.get("title"):
        found, schedule_change = _schedule_lines(room, str(wake["title"]))
        lines += ["", *found]

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
        # Given to it, it already holds the row: there is nothing to claim (#1136).
        lines += [
            "Held:   it's yours until you resolve it or hand it back; no claim needed",
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
    # A scheduled wake ends on the schedule being the agent's own to change.
    if schedule_change:
        lines += ["", schedule_change]
    return "\n".join(lines)
