# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
What a woken agent is told: a digest of what happened while it was away.

A wake is typed into the agent's terminal by its host (herdr, Omnigent). It
used to be a doorbell ("you have messages, go read the room"), which left the
agent to rebuild where it was before it could act. The reader is a model that
can take in a lot at once, so the digest gives it the picture up front, in the
order it acts on it: why it woke and what changed, then the message that woke
it, whole, then what to do next (``await``, then ``respond``), then the other
messages asking for it, then its tasks and the board.

Every message is a box: a header line, every line of its text behind a ``│``
gutter, and a closing line. Nothing another member writes can reach the first
column, so no message can pass itself off as a header, a ``Next:`` step or a
second message, whatever it contains, and no escaping rule can slip. The ask is
given in full up to :data:`LATEST_CHARS`; the others share :data:`OTHERS_CHARS`,
newest first, and each one that doesn't fit is named with the command that
prints it. Asks the agent has replied to (it posted in their thread after
them) are counted, not shown. A task's title is given whole once, on the
``Why:`` line, and shortened after. What changed (``Since:``, ``Board:``)
counts from the agent's last turn.

Built when the wake is delivered, not when it was queued, since a wake can wait
while its agent is busy and the room moves on meanwhile.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.services import assignments, message_format
from app.services.agent_registry import norm_handle
from app.services.persister import (
    _conversational_text,
    parse_recorded_at,
    read_id,
    record_episode,
)
from app.services.words import a_or_an

#: How much of the message that woke the agent is shown: in full, unless it is
#: longer than this (a pasted log, say), since a wake is typed into its terminal.
LATEST_CHARS = 6000
#: How much room the other messages asking for it share, newest first.
OTHERS_CHARS = 4000
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
#: changing, which :func:`moves` says in its own words; ``check`` is the verifier
#: on one message, which the agent it is about reads as its ``Check:`` line.
BOARD_NOTICES = message_format.NOTICE_SUBKINDS - {"floor", "upstream", "check"}
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


#: Control characters, C0 and C1, except the tab: a wake is typed into the
#: agent's terminal, where an escape can stop its turn or end a bracketed
#: paste, so what a member wrote never carries one there.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def plain(text: str) -> str:
    """``text`` on one line: its control characters gone and its whitespace,
    line breaks of every kind included, run together. For anything a member
    wrote that lands in the digest's own lines (a task's title, a name)."""
    return " ".join(_CONTROL.sub("", text).split())


def box(header: str, text: str, footer: str = "") -> list[str]:
    """``text`` as a box: the header, each line behind a ``│``, then the close.

    The gutter is on every line, so nothing in the text can reach the first
    column, where the digest's own lines start. Every kind of line break
    starts a new gutter line (``splitlines``: U+2028 and the rest, not only
    ``\\n``), control characters are dropped, and the header and footer are
    kept to one line, so no character in a message can step outside its box.
    """
    lines = [f"┌ {plain(header)}"]
    for line in text.splitlines() or [""]:
        line = _CONTROL.sub("", line.replace("\t", "    ")).rstrip()
        lines.append(f"│ {line}" if line.strip() else "│")
    lines.append(f"└ {plain(footer)}" if footer else "└")
    return lines


def short_id(record: Any) -> str:
    """The id a message goes by in the digest: the start of its read id, which
    ``mycelium room messages --id`` takes and the room's history shows."""
    return str(read_id(record))[:8]


def _where(room: str, episode: str | None) -> tuple[str, str] | None:
    """The ``(key, title)`` of the task a thread belongs to; ``None`` for the room."""
    if not episode or message_format.is_live_episode(room, episode):
        return None
    from app.services.tasks import row_of_episode

    try:
        row = row_of_episode(room, episode)
    except Exception:  # a digest without a place is still a digest
        return None
    # A title is a member's text on one of the digest's own lines.
    return (row[0], plain(row[1])) if row else None


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
    # A member's text on the digest's own line: no control character reaches it.
    return plain(first.lstrip("# "))


def _short(title: str, limit: int) -> str:
    """A title cut to ``limit`` characters on a word, ending in an ellipsis,
    on one line and with no control characters (:func:`plain`)."""
    title = plain(title)
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
    from here, so they can't disagree. A notice (one a subscription caught) is
    answered in the thread of the task it is about."""
    if not asked:
        return None
    notice = _board_notice(asked[-1]) or _upstream_notice(asked[-1])
    if notice and notice.get("key"):
        from app.services import tasks

        return tasks.episode_of(room, str(notice["key"]))
    return _thread_of(room, asked[-1])


def _floor_line(room: str, thread: str | None, me: str) -> str | None:
    """Whose turn it is in ``thread``, when its floor doesn't admit ``me``."""
    if thread is None:
        return None
    from app.services.room_channels import manager

    floor = manager.floor(room, thread)
    if floor is None or floor.admits(me):
        return None
    return f"{floor.describe()}. Wait for your turn; a write before it is refused."


def reply_episode(room: str, wake: dict[str, Any], records: list[Any]) -> str | None:
    """The thread ``wake``'s agent is told to reply in, for the room's "is
    responding in" line; ``None`` for the room itself (:func:`_reply_thread`)."""
    handle = str(wake.get("handle") or "")
    _, _, since, asked = _since(handle, records, wake.get(READ_FROM))
    return _reply_thread(room, asked or [r for r, _ in _watched(room, handle, since)])


def _watched(room: str, handle: str, since: list[Any]) -> list[tuple[Any, Any]]:
    """The records in ``since`` that woke ``handle`` through a subscription it
    made rather than by asking it, each with its wake (``asks.wakes_for``, the
    rule ``await`` and the doorbell read too)."""
    from app.services import subscriptions
    from app.services.asks import wakes_for

    me = _norm(handle)
    mine = [s for s in subscriptions.load(room) if s.handle == me]
    if not mine:
        return []
    found = [(r, wakes_for(room, r, handle, mine)) for r in since]
    return [(r, w) for r, w in found if w is not None and w.reason == "subscribed"]


#: The key on a wake holding its agent's read position in the transcript: the
#: durable inbox cursor ``await`` advances (``persister.log.position``). Set
#: by the route handing wakes over, when the hub has one for the agent.
READ_FROM = "read_from"


def _since(
    handle: str, records: list[Any], read_from: int | None = None
) -> tuple[list[Any], int, list[Any], list[Any]]:
    """What ``handle`` hasn't seen: the window read, the index of its last
    message in it (-1 for none), the records it hasn't read, and the ones among
    them that asked for it (:func:`app.services.asks.asks`, which ``await`` and
    the doorbell decide by too).

    With ``read_from`` (its read position in ``records``), that is everything
    after it, except what it said itself: an agent can post a reply without
    having read a message that arrived just before it. Without one it's what
    came after its last message, the best guess the transcript alone allows.
    """
    from app.services.asks import asks

    me = _norm(handle)
    window = records[-SCAN:]
    last = max((i for i, r in enumerate(window) if _norm(r.sender) == me), default=-1)
    if read_from is None:
        since = window[last + 1 :]
    else:
        start = max(0, read_from - (len(records) - len(window)))
        since = [r for r in window[start:] if _norm(r.sender) != me]
    asked = [r for r in since if asks(r.content, handle)]
    return window, last, since, asked


def coverage(wake: dict[str, Any], records: list[Any], room: str | None = None) -> dict[str, Any]:
    """Which messages a wake covers, as ids: the ones that asked for its agent,
    with ``room`` the ones its subscriptions caught (``watching``), and the
    range its digest summarized (what its agent hadn't read, oldest to
    newest). Text stays in the transcript; the wake log keeps these."""
    handle = str(wake.get("handle") or "")
    _, _, since, asked = _since(handle, records, wake.get(READ_FROM))
    covered: dict[str, Any] = {"messages": [r.message_id for r in asked]}
    if room is not None:
        covered["watching"] = [r.message_id for r, _ in _watched(room, handle, since)]
    if since:
        covered["range"] = [since[0].message_id, since[-1].message_id]
    return covered


def _named(where: tuple[str, str]) -> str:
    """A task named after the ``Why:`` line has given it whole: its title,
    shortened, so a long one doesn't bury a short message on every line."""
    return f'"{_short(where[1], TITLE_CHARS)}"'


def _in(room: str, record: Any) -> str:
    """Where ``record`` was said, for a box's header."""
    where = _where(room, record_episode(record))
    return f"in {_named(where)}" if where else "in the room"


def _ask_box(room: str, record: Any, now: datetime, limit: int) -> list[str]:
    """One message asking for the agent, as a box: who, when, where and its id,
    then its text in full, or up to ``limit`` with the command that reads the rest."""
    # What asked (``asks.py``) always has text, an aligner's tick included.
    text = str(record.content.get("content") or "").strip()
    rid = short_id(record)
    place = _in(room, record)
    header = (
        f"@{record.sender} · {age(parse_recorded_at(record.recorded_at), now)} · {place} · {rid}"
    )
    if len(text) <= limit:
        return box(header, text)
    head = text[:limit]
    # On a line's end where there is one near the limit, so a table or a code
    # block isn't left with half a row.
    newline = head.rfind("\n")
    if newline > limit * 0.6:
        head = head[:newline]
    head = head.rstrip()
    footer = (
        f"cut at {len(head):,} of {len(text):,} characters · read it all: "
        f"mycelium room messages {room} --id {rid}"
    )
    return box(header, head, footer)


def _shown(room: str, me: str) -> dict[str, datetime]:
    """``{message id: when a wake first put it in front of me}``: the messages
    each wake handed to its runner covered (``wake_log``). A wake that was
    dropped, or never reached the agent, showed it nothing.

    Asks an ``await`` handed over need nothing here: it moves the agent's read
    position past them, so no later digest considers them again."""
    from app.services import wake_log

    shown: dict[str, datetime] = {}
    for w in wake_log.read(room, agent=me, limit=200):
        when = parse_recorded_at(str(w.get("at") or ""))
        if w.get("outcome") not in ("handed", "delivered") or when is None:
            continue
        for mid in w.get("messages") or []:
            if str(mid) not in shown or when < shown[str(mid)]:
                shown[str(mid)] = when
    return shown


def _replied(room: str, window: list[Any], asked: list[Any], me: str) -> set[int]:
    """The asks the agent has replied to since: a wake showed it the ask, and
    after that it posted where the ask was made. The hub can see that much;
    whether the reply answered is the agent's to say.

    An ask that arrived while the agent was busy with an earlier one was never
    shown to it, and a post it made before being shown one isn't an answer to
    it: several mentions in a row all reach the next wake."""
    at = {id(r): i for i, r in enumerate(window)}
    shown = _shown(room, me)
    replied: set[int] = set()
    for record in asked:
        i = at.get(id(record))
        seen = shown.get(record.message_id)
        if i is None or seen is None:
            continue
        here = _thread_of(room, record)
        if any(
            _norm(later.sender) == me
            and _thread_of(room, later) == here
            and (posted := parse_recorded_at(later.recorded_at)) is not None
            and posted > seen
            for later in window[i + 1 :]
        ):
            replied.add(id(record))
    return replied


def _reply_lines(room: str, me: str, window: list[Any], asked: list[Any]) -> list[tuple[str, str]]:
    """Where to reply, and the ``respond`` that puts it there, for each place
    an ask the agent hasn't replied to was made, the newest ask's place first.

    The place is who wrote and where (``@julia wrote, in "Fix the tax"``),
    since the rule is to answer where the message was written. ``respond``
    lands in a task's thread only with ``--task``, so the target is named
    outright; a thread no row carries can't be named, so its reply goes to the
    room, and the place says so."""
    replied = _replied(room, window, asked[:-1], me)
    lines: list[tuple[str, str]] = []
    seen: set[str | None] = set()
    for record in reversed(asked):
        if id(record) in replied:
            continue
        thread = _thread_of(room, record)
        where = _where(room, thread)
        target = where[0] if where else None
        if target in seen:
            continue
        seen.add(target)
        task = f" --task {where[0]}" if where else ""
        wrote = f"@{plain(record.sender)} wrote"
        if where:
            place = f"{wrote}, in {_named(where)}"
        elif thread:
            place = f"{wrote} in a thread no task carries, so this lands in the room"
        else:
            place = f"{wrote}, in the room"
        lines.append((place, f'mycelium respond --room {room} --handle {me}{task} --body "..."'))
    return lines


def _other_asks(
    room: str, window: list[Any], asked: list[Any], me: str, now: datetime
) -> list[str]:
    """The messages asking for the agent besides the one that woke it.

    Newest first, each whole while they fit in :data:`OTHERS_CHARS` together;
    the rest are named, one line each, with the command that prints them. The
    ones it has replied to since are counted and left out.
    """
    earlier = asked[:-1]
    if not earlier:
        return []
    replied = _replied(room, window, earlier, me)
    others = [r for r in reversed(earlier) if id(r) not in replied]
    left_out = len(earlier) - len(others)
    lines = [""]
    if not others:
        said = (
            "1 earlier ask you've replied to isn't"
            if left_out == 1
            else (f"{left_out} earlier asks you've replied to aren't")
        )
        return [*lines, f"({said} shown)"]
    count = f"Also asking you ({len(others)}"
    if left_out:
        count += f"; {left_out} earlier you've replied to aren't shown"
    lines.append(count + "):")
    budget = OTHERS_CHARS
    named: list[str] = []
    for record in others:
        size = len(str(record.content.get("content") or "").strip())
        if size <= budget:
            budget -= size
            lines += ["", *_ask_box(room, record, now, OTHERS_CHARS)]
            continue
        rid = short_id(record)
        place = _in(room, record)
        when = age(parse_recorded_at(record.recorded_at), now)
        named.append(
            f"  @{record.sender} · {when} · {place} · {size:,} characters: "
            f"mycelium room messages {room} --id {rid}"
        )
    if named:
        lines += ["", "Not shown here, to keep this short:", *named]
    return lines


def _watching_lines(room: str, me: str, watched: list[tuple[Any, Any]], now: datetime) -> list[str]:
    """What the agent's subscriptions caught since it last read, newest kept,
    one line each with the subscription that matched: apart from what asks it,
    since nobody asked it anything."""
    if not watched:
        return []
    shown = watched[-CHANGES_SHOWN:]
    out = [""]
    for i, (record, wake) in enumerate(shown):
        when = age(parse_recorded_at(record.recorded_at), now)
        # "work/x: @r posted in it": the heading says these are subscriptions.
        what = plain(str(wake.why)).removeprefix("you subscribed to ")
        line = f"{what} · {when} · {short_id(record)} · subscription {wake.subscription}"
        out.append(f"{'Watching:' if i == 0 else '':<10}{line}")
    if len(watched) > CHANGES_SHOWN:
        out.append(f"{'':<10}and {len(watched) - CHANGES_SHOWN} earlier")
    out.append(f"{'':<10}stop one: mycelium subscribe rm <id> --room {room} --as {me}")
    return out


def build(
    room: str,
    wake: dict[str, Any],
    records: list[Any],
    now: datetime | None = None,
    *,
    awaited: bool = False,
) -> str:
    """The digest typed into ``wake``'s agent: why, what changed, what asked for it.

    ``awaited`` is the same digest printed by ``await``, which has already
    handed these messages over, so it doesn't say to run ``await`` first.
    """
    now = now or datetime.now(UTC)
    handle = str(wake.get("handle") or "")
    me = _norm(handle)
    reason = wake.get("reason") or "mention"
    window, last, since, asked = _since(handle, records, wake.get(READ_FROM))
    # What its subscriptions caught, kept apart from what asks it. With no ask,
    # the newest of these is what it answers, so it sets where to reply.
    watched = _watched(room, handle, since)
    answering = asked or [r for r, _ in watched[-1:]]
    last_at = parse_recorded_at(window[last].recorded_at) if last >= 0 else None
    here = _reply_thread(room, answering)
    episode = here or (record_episode(answering[-1]) if answering else wake.get("episode"))
    where = _where(room, episode)

    def place_of(record: Any) -> str | None:
        return _thread_of(room, record)

    # What was said since its last *turn*: its read position can lag behind
    # that (an ``await`` it never ran), and what it saw before it last spoke
    # is no news. The asks still come from the read position, since ``await``
    # hands those over.
    after_turn = {id(r) for r in window[last + 1 :]}
    said = [
        r for r in since if id(r) in after_turn and (_conversational_text(r.content) or r in asked)
    ]
    in_here = [r for r in said if place_of(r) == here]
    elsewhere = len(said) - len(in_here)
    by = Counter(r.sender for r in in_here if r.sender)

    lines = [f"mycelium wake for @{me} in {room}", ""]

    # Why it woke.
    sender = f"@{wake['from']}" if wake.get("from") else "someone"
    # A task's title is a member's text, on the digest's own line.
    title = plain(str(wake.get("title") or wake.get("key") or ""))
    if reason == "assigned":
        why = f'{sender} gave you a task: "{title}" ({wake.get("key")})'
    elif reason == "handback":
        why = f'{sender} handed your task back to you in its thread: "{title}" ({wake.get("key")})'
    elif reason == "schedule":
        why = f'your schedule "{title}" fired'
    elif reason == "subscribed":
        # The subscription's own line ("you subscribed to work/x: @r posted
        # in it"), the newest one's when several fired.
        why = plain(
            str(watched[-1][1].why if watched else wake.get("why") or "a subscription fired")
        )
        if len(watched) > 1:
            why += f" (and {len(watched) - 1} more below)"
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
    elif reason == "resumed":
        # The other half of a pause (``pauses``): it was told to stop and wait,
        # so it needs telling that it may carry on, and what came in meanwhile.
        why = (
            f"{sender} resumed you from Mycelium. Carry on where you stopped. "
            "Below is what arrived while you were paused."
        )
    else:
        n = len(asked)
        latest = f", latest {age(parse_recorded_at(asked[-1].recorded_at), now)}" if asked else ""
        count = f"{n} messages mention" if n > 1 else f"{sender} mentioned"
        why = f"{count} you in {_place(room, where)}{latest}"
    lines.append(f"Why:     {why}")
    # A thread whose floor is held for someone else: it was named, but the
    # conductor (or whoever holds it) asks in turn, so its writes wait till then.
    if (turn := _floor_line(room, here, me)) is not None:
        lines.append(f"Floor:   {turn}")

    # What the verifier couldn't confirm in what it said since its last turn. It
    # rides along on whatever wake comes next; a flag never wakes anyone itself.
    from app.services.verifier import check_lines

    for i, check in enumerate(check_lines(room, handle, since)):
        lines.append(f"{'Check:' if i == 0 else '':<9}{check}")

    # What changed since its last turn.
    who = ", ".join(f"@{h} {c}" for h, c in by.most_common())
    first = f"your last turn, {age(last_at, now)}" if last >= 0 else "you joined"
    here_word = "this thread" if here else "the room"
    changed = f"{len(in_here)} in {here_word}" + (f" ({who})" if who else "")
    rest = [changed]
    if elsewhere:
        rest.append(f"{elsewhere} elsewhere")
    lines.append(f"Since:   {first}: " + ", ".join(rest))
    # Someone else pausing one of its schedules is said here, once, rather than
    # with a message that woke it (the herdr-wakes route marks it said).
    from app.services import schedules

    lines += [
        f"Schedule: {schedules.pause_line(s, room, now)}"
        for s in schedules.untold_pauses(room, handle)
    ]

    # What the schedule says to do, and what its pre-check found.
    schedule_change = None
    if reason == "schedule" and wake.get("title"):
        found, schedule_change = _schedule_lines(room, str(wake["title"]))
        lines += ["", *found]

    # The message that woke it, whole, then what to do about it.
    if asked:
        lines += ["", *_ask_box(room, asked[-1], now, LATEST_CHARS)]
    elif answering and _conversational_text(answering[-1].content):
        lines += ["", *_ask_box(room, answering[-1], now, LATEST_CHARS)]
    lines.append("")
    if reason == "assigned" and wake.get("key"):
        key = wake["key"]
        # Given to it, it already holds the row: there is nothing to claim (#1136).
        lines += [
            "Held:   it's yours until you resolve it or hand it back; no claim needed",
            f"Read:   mycelium board messages {key} --room {room}",
            f'Post:   mycelium board send {key} --room {room} --as {me} --body "..."',
        ]
    elif reason == "handback" and wake.get("key"):
        key = wake["key"]
        lines += [
            f"Read:   mycelium board messages {key} --room {room}",
            f'Post:   mycelium board send {key} --room {room} --as {me} --body "..."',
        ]
    else:
        asking = {id(r) for r in asked}
        more = sum(id(r) not in asking for r in said)
        # Said, not "shows": ``await`` prints only some of them (``earlier`` is
        # capped and stops at the previous ask).
        noun = "was" if more == 1 else "were"
        extra = f"; {more} more {noun} said since your last turn" if more > 0 else ""
        # ``await`` comes first: it is what marks these read and says the agent
        # is on it. Then a reply where each unanswered ask was made, the one
        # that woke it first: an older ask can be a flow's turn in another
        # thread, with a floor and a deadline there.
        replies = _reply_lines(room, me, window, asked)
        # Handed over by ``await``, these are already read: the reply is all
        # that's left to do, and it is the one step.
        step = "Next:    " if awaited else "         2. "
        if not awaited:
            lines += [
                f"Next:    1. mycelium await --room {room} --handle {me} --json --timeout 5",
                f"            (marks these read and says you're on it{extra})",
            ]
        # An agent asked in a task's thread tends to answer in the main
        # channel, weighing a hint against its own sense of where a topic
        # belongs. The wake is the one place it learns where the person
        # wrote, so step 2 says it as the rule the skill gives: reply there.
        if not replies:
            task = f" --task {where[0]}" if here and where else ""
            lands = _named(where) if here and where else "the room"
            lines.append(
                f'{step}mycelium respond --room {room} --handle {me}{task} --body "..."'
                f"   (lands in {lands})"
            )
        elif len(replies) == 1:
            place, command = replies[0]
            lines += [f"{step}reply where {place}:", f"            {command}"]
        else:
            lines.append(f"{step}reply where each was written:")
            lines += [f"            {command}   ({place})" for place, command in replies]

    # The others asking for it: whole while they fit, newest first, then named.
    lines += _other_asks(room, window, asked, me, now)
    lines += _watching_lines(room, me, watched, now)

    mine, tally = board(room, handle, now)
    lines.append("")
    if mine:
        lines.append(f"Tasks:   {mine[0]}")
        lines.extend(f"         {t}" for t in mine[1:TASKS_SHOWN])
        if len(mine) > TASKS_SHOWN:
            lines.append(f"         and {len(mine) - TASKS_SHOWN} more")
    # What changed on the board since its last turn, and on the pull requests
    # behind its rows, then what's open now, so the agent doesn't have to read
    # the board to learn what moved. Since its last *turn*, not its read
    # position: what it saw before it last spoke is no news, even unread.
    moved = moves(room, handle, [r for r in since if id(r) in after_turn], now)
    if moved:
        lines.append(f"Board:   {moved[0]}")
        lines.extend(f"         {c}" for c in moved[1:CHANGES_SHOWN])
        if len(moved) > CHANGES_SHOWN:
            lines.append(f"         and {len(moved) - CHANGES_SHOWN} more")
        lines.append(f"         open now: {tally}")
    else:
        lines.append(f"Board:   {tally}")
    # What the team agreed for the task it's about, so it works to that.
    task_key = (
        wake.get("key") if reason in ("assigned", "handback") else (where[0] if where else None)
    )
    if task_key:
        from app.services import agreed

        pointers = agreed.pointer(room, str(task_key))
        if pointers:
            lines.append(f"Agreed:  {pointers[0]}")
            lines.extend(f"         {p}" for p in pointers[1:])

    # One line, so an agent that needs more than this digest holds knows the
    # room's whole history can be asked rather than paged through.
    lines.append(
        f'Find:    mycelium room search "<words> from:<handle> task:<row> after:1d" --room {room}'
        "   (any message, any field; --facets for counts)"
    )
    # A scheduled wake ends on the schedule being the agent's own to change.
    if schedule_change:
        lines += ["", schedule_change]
    return "\n".join(lines)
