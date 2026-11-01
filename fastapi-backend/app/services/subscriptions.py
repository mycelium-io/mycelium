# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What an agent has asked to be woken for, beyond what asks it.

An agent is woken when something asks it: a mention, a turn put to it, a task
filed for it. A **subscription** is the other way in: the agent says what it is
watching, and anything matching it wakes the agent the same way, through
``await`` and herdr's doorbell. Four kinds:

- ``task``: a task's thread and the notices about it, and with ``parts`` its
  parts too (the rows ``part-of`` it, including ones filed later);
- ``notice``: board notices of one kind (``resolved``, ``filed``…) or a pull
  request's change (``upstream:merged``, ``upstream:ci_passed``…), optionally
  only about one task;
- ``member``: anything one member says in the room or its threads;
- ``search``: messages matching a ``mycelium room search`` query.

It is opt-in and per agent: a notice still wakes nobody who didn't subscribe to
it, and nothing the hub does on its own subscribes anyone. A record never wakes
its own sender, and only records made after a subscription began match it.

A subscription ends without being deleted: its ``ended_at`` says when, and only
records from before then match. ``await`` reads records lazily, after the
doorbell has seen them, so a subscription deleted the moment its task resolved
would hide that last notice from ``await``. A task subscription ends once the
task (and with ``parts`` every part) is settled; ``until`` ends any of them at a
set time. Ended ones are kept a day, so both readers see the end, then dropped.

The store is one JSON file per room (``.subscriptions.json``), beside
``.schedules.json``; nothing here is a memory to index or version.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from app.services import assignments, message_format
from app.services.agent_registry import norm_handle
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file

logger = logging.getLogger(__name__)

STORE_FILE = ".subscriptions.json"
#: How long an ended subscription is kept so a lazy ``await`` still sees its end.
KEEP_ENDED = timedelta(days=1)

Kind = Literal["task", "notice", "member", "search"]

#: Notices an agent can subscribe to by kind: the wire's closed set
#: (``contracts/slim-wire.json``), less turn-taking, hub bookkeeping and the
#: verifier's word on one message, which are nobody's news, and ``upstream``,
#: which is named by its change.
UNTOLD = frozenset({"floor", "quiet", "check"})
NOTICE_KINDS = message_format.NOTICE_SUBKINDS - UNTOLD - {"upstream"}
#: A pull request's changes, subscribed to as ``upstream:<change>``.
UPSTREAM_CHANGES = message_format.UPSTREAM_CHANGES
#: How long a member or search subscription lasts unless told otherwise. Those
#: are the open-ended kinds, the ones left running after they stop mattering;
#: a task subscription ends with its task.
DEFAULT_SPAN = timedelta(hours=24)
#: Search clauses about time mean nothing for one new message.
TIMELESS = ("after:", "before:", "on:", "sort:")


class SubscriptionError(ValueError):
    """A subscription the hub refuses, with the reason a caller is shown."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


class Subscription(BaseModel):
    id: str
    handle: str
    kind: Kind
    #: The task key, the notice kind, the member's handle, or the search query.
    target: str
    #: For ``task``: its parts too.
    parts: bool = False
    #: For ``notice``: only notices about this task.
    task: str | None = None
    created_at: datetime
    #: Ends then, if set when it was made.
    until: datetime | None = None
    #: When it ended, for a task subscription whose work is done.
    ended_at: datetime | None = None

    def describe(self) -> str:
        """The subscription as a person reads it: ``work/x and its parts``."""
        if self.kind == "task":
            return f"{self.target}{' and its parts' if self.parts else ''}"
        if self.kind == "notice":
            return f"{self.target} notices" + (f" on {self.task}" if self.task else "")
        if self.kind == "member":
            return f"what @{self.target} says"
        return f'messages matching "{self.target}"'

    def live_at(self, when: datetime) -> bool:
        """Whether a record made at ``when`` falls inside this subscription."""
        if when < self.created_at:
            return False
        if self.until is not None and when >= self.until:
            return False
        return not (self.ended_at is not None and when > self.ended_at)


# ── the store ────────────────────────────────────────────────────────────────

_locks: dict[str, asyncio.Lock] = {}


def _lock(room: str) -> asyncio.Lock:
    return _locks.setdefault(room, asyncio.Lock())


def _path(room: str):
    return get_room_dir(room) / STORE_FILE


def load(room: str) -> list[Subscription]:
    """Every subscription in ``room``. One that no longer parses is skipped."""
    path = _path(room)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("subscriptions: %s is unreadable; reading none", path)
        return []
    out: list[Subscription] = []
    for item in raw.get("subscriptions", []) if isinstance(raw, dict) else []:
        try:
            out.append(Subscription.model_validate(item))
        except ValueError:
            logger.warning("subscriptions: skipping an unreadable one in %s", room)
    return out


def _save(room: str, subs: list[Subscription]) -> None:
    path = _path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"subscriptions": [s.model_dump(mode="json") for s in subs]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def of(room: str, handle: str, now: datetime | None = None) -> list[Subscription]:
    """``handle``'s subscriptions in ``room`` that haven't ended."""
    now = now or datetime.now(UTC)
    me = norm_handle(handle) or ""
    return [s for s in load(room) if s.handle == me and s.live_at(now)]


def _validate(room: str, kind: Kind, target: str, task: str | None) -> str:
    """``target`` as stored, or why it can't be subscribed to."""
    target = target.strip()
    if not target:
        raise SubscriptionError("say what to subscribe to")
    if kind == "task":
        if read_memory_file(get_room_dir(room), target) is None or not assignments.assignable(
            target
        ):
            raise SubscriptionError(f"no task {target} in {room}", status=404)
        return target
    if kind == "notice":
        if target.startswith("upstream:"):
            if target.removeprefix("upstream:") not in UPSTREAM_CHANGES:
                raise SubscriptionError(
                    f"{target} isn't a pull-request change: upstream:{', upstream:'.join(sorted(UPSTREAM_CHANGES))}"
                )
        elif target not in NOTICE_KINDS:
            raise SubscriptionError(
                f"{target} isn't a notice kind: {', '.join(sorted(NOTICE_KINDS))}, or upstream:<change>"
            )
        if task and read_memory_file(get_room_dir(room), task) is None:
            raise SubscriptionError(f"no task {task} in {room}", status=404)
        return target
    if kind == "member":
        member = norm_handle(target)
        if not member:
            raise SubscriptionError(f"@{target} isn't a handle")
        return member
    from app.services import message_search

    timed = [w for w in target.split() if w.lstrip("-").lower().startswith(TIMELESS)]
    if timed:
        raise SubscriptionError(
            f"a subscription matches each new message, so {', '.join(timed)} means nothing here"
        )
    problems = message_search.parse(target).problems
    if problems:
        raise SubscriptionError(f"that search doesn't parse: {'; '.join(problems)}")
    return target


def parse_span(raw: str | None, now: datetime) -> tuple[datetime | None, bool]:
    """``--for``: ``(until, forever)`` from ``2h``, ``3d`` or ``never``; neither
    for nothing, which leaves the kind's default."""
    raw = (raw or "").strip().lower()
    if not raw:
        return None, False
    if raw == "never":
        return None, True
    from app.services import schedules

    try:
        return now + timedelta(seconds=schedules.parse_every(raw)), False
    except schedules.ScheduleError as err:
        raise SubscriptionError(f"for '{raw}' is not a span like 2h or 3d, or never") from err


async def add(
    room: str,
    handle: str,
    kind: Kind,
    target: str,
    *,
    parts: bool = False,
    task: str | None = None,
    until: datetime | None = None,
    forever: bool = False,
    now: datetime | None = None,
) -> Subscription:
    """Subscribe ``handle`` to ``target``. The same subscription twice is one.

    A member or search subscription ends after :data:`DEFAULT_SPAN` unless
    ``until`` says when or ``forever`` says never."""
    now = now or datetime.now(UTC)
    if until is None and not forever and kind in ("member", "search"):
        until = now + DEFAULT_SPAN
    me = norm_handle(handle) or ""
    if not me:
        raise SubscriptionError("a subscription needs a handle")
    if kind != "task" and parts:
        raise SubscriptionError("only a task subscription can cover its parts")
    if kind != "notice" and task:
        raise SubscriptionError("only a notice subscription can be about one task")
    if until is not None and until <= now:
        raise SubscriptionError("it would end before it began")
    target = _validate(room, kind, target, task)
    async with _lock(room):
        subs = [s for s in load(room) if not _expired(s, now)]
        for i, s in enumerate(subs):
            same = (s.handle, s.kind, s.target, s.parts, s.task) == (me, kind, target, parts, task)
            if same and s.live_at(now):
                # Subscribing again renews it, to the end asked for this time.
                if s.until != until:
                    subs[i] = s.model_copy(update={"until": until})
                    _save(room, subs)
                return subs[i]
        sub = Subscription(
            id=secrets.token_hex(4),
            handle=me,
            kind=kind,
            target=target,
            parts=parts,
            task=task,
            created_at=now,
            until=until,
        )
        _save(room, [*subs, sub])
    return sub


async def remove(room: str, handle: str, sub_id: str | None = None) -> list[Subscription]:
    """Drop one of ``handle``'s subscriptions, or all of them; return what went."""
    me = norm_handle(handle) or ""
    async with _lock(room):
        subs = load(room)
        gone = [s for s in subs if s.handle == me and (sub_id is None or s.id == sub_id)]
        if sub_id is not None and not gone:
            raise SubscriptionError(f"@{me} has no subscription {sub_id} in {room}", status=404)
        _save(room, [s for s in subs if s not in gone])
    return gone


def _expired(sub: Subscription, now: datetime) -> bool:
    end = sub.ended_at or sub.until
    return end is not None and now - end > KEEP_ENDED


# ── matching one record ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Match:
    """A subscription a record falls under, and the line saying why."""

    sub: Subscription
    why: str


def _payload(record: Any) -> dict[str, Any]:
    return (record.content.get("l9") or {}).get("payload") or {}


def _notice(record: Any) -> dict[str, Any] | None:
    payload = _payload(record)
    if payload.get("type") != message_format.NOTICE_PAYLOAD_TYPE:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _recorded_at(record: Any) -> datetime:
    from app.services.persister import parse_recorded_at

    return parse_recorded_at(record.recorded_at) or datetime.now(UTC)


class _Room:
    """What matching needs to know about a room, read once per record."""

    def __init__(self, room: str) -> None:
        self.room = room
        self._rows: list[tuple[str, dict]] | None = None
        self._threads: dict[str, str] = {}

    def rows(self) -> list[tuple[str, dict]]:
        if self._rows is None:
            room_dir = get_room_dir(self.room)
            self._rows = [
                (key, meta)
                for namespace in assignments.ASSIGNABLE_NAMESPACES
                for key, meta, _content in list_memory_files(room_dir, prefix=f"{namespace}/")
            ]
        return self._rows

    def keys(self, task: str, parts: bool) -> set[str]:
        """``task``, and with ``parts`` every row part-of it, at any depth."""
        keys = {task}
        if not parts:
            return keys
        grew = True
        while grew:
            more = {
                key
                for key, meta in self.rows()
                if str(meta.get(assignments.PARENT_RELATION) or "").strip() in keys
                and key not in keys
            }
            keys |= more
            grew = bool(more)
        return keys

    def thread_of(self, key: str) -> str | None:
        if key not in self._threads:
            from app.services import tasks

            self._threads[key] = tasks.episode_of(self.room, key) or ""
        return self._threads[key] or None

    def settled(self, keys: set[str], now: datetime) -> bool:
        rows = dict(self.rows())
        return all(key in rows and assignments.settled(rows[key], now) for key in keys)


# ── what a post answers ──────────────────────────────────────────────────────
#
# A subscription wakes you for what others start, never for an answer to you.
# ``respond`` marks its answer (a ``reply`` to whoever woke the agent), but
# ``board send`` and ``room send`` post a plain message, so the rule is kept on
# what caused the post rather than on its payload: while an agent is answering
# a wake, what it posts doesn't wake, by subscription, anyone whose message
# was in that wake. ``await`` and the doorbell's delivery say whose messages
# they handed over (:func:`answering`); each record is stamped with that when
# it is recorded (:func:`note_posted`), since ``await`` reads it later, after
# the turn that wrote it may have ended. Both live in memory: after a restart
# an answer can wake its asker once, which is the worst it does.

#: How long after a wake an agent's posts count as answering it, unless its
#: next wake comes first.
ANSWERING_FOR_S = 20 * 60
#: How many recorded posts per room keep their stamp.
_STAMPS_KEPT = 5000

_answering: dict[tuple[str, str], tuple[frozenset[str], float]] = {}
_stamps: dict[str, dict[str, frozenset[str]]] = {}


def answering(room: str, handle: str, senders: set[str]) -> None:
    """``handle`` was just handed messages from ``senders`` to answer."""
    import time

    me = norm_handle(handle) or ""
    them = frozenset(n for s in senders if (n := norm_handle(s)) and n != me)
    _answering[(room, me)] = (them, time.monotonic() + ANSWERING_FOR_S)


def note_posted(room: str, record: Any) -> None:
    """Stamp ``record`` with whom its sender was answering when it was posted."""
    import time

    sender = norm_handle(record.sender or "") or ""
    held = _answering.get((room, sender))
    if held is None or held[1] < time.monotonic() or not held[0]:
        return
    stamps = _stamps.setdefault(room, {})
    stamps[record.message_id] = held[0]
    if len(stamps) > _STAMPS_KEPT:
        for old in list(stamps)[: len(stamps) - _STAMPS_KEPT]:
            del stamps[old]


def _answered(room: str, record: Any) -> set[str]:
    """Who ``record`` answers: a ``reply``'s recipients, whom ``respond`` sets
    to the member whose message woke the replier, and whoever its sender was
    answering when it posted it (:func:`note_posted`)."""
    return _reply_to(record) | set(_stamps.get(room, {}).get(record.message_id, ()))


def _reply_to(record: Any) -> set[str]:
    """Who a ``reply`` answers: its recipients, whom ``respond`` sets to the
    member whose message woke the replier. Empty for anything but a reply."""
    if _payload(record).get("type") != "reply":
        return set()
    header = (record.content.get("l9") or {}).get("header") or {}
    actors = (header.get("participants") or {}).get("actors") or []
    return {norm_handle(a.get("id")) or "" for a in actors[1:] if isinstance(a, dict)}


def _outside(room: str, episode: str | None, handle: str) -> bool:
    """Whether ``episode`` is a frozen negotiation's thread ``handle`` isn't in.
    A subscription delivers only what its subscriber could read there."""
    if not episode:
        return False
    from app.services.room_channels import manager

    managed = manager.get(room)
    lifecycle = managed.lifecycle if managed is not None else None
    if lifecycle is None or not lifecycle.frozen or lifecycle.episode != episode:
        return False
    return handle not in {norm_handle(m) for m in lifecycle.members}


def _said(record: Any) -> str | None:
    from app.services.persister import _conversational_text

    return _conversational_text(record.content)


def _search_hits(room: str, record: Any, queries: list[str]) -> set[str]:
    """Which of ``queries`` the one message ``record`` matches."""
    from app.services import message_search
    from app.services.persister import stored_message_from_record

    message = stored_message_from_record(room, record)
    if message is None:
        return set()
    return {q for q in queries if message_search.search(room, [message], q, limit=1).hits}


def _why(sub: Subscription, record: Any, notice: dict[str, Any] | None) -> str:
    who = f"@{record.sender}"
    if notice is not None:
        from app.services import wake_digest

        if notice.get("subkind") == "upstream":
            line = wake_digest.upstream_line(notice, _recorded_at(record), _recorded_at(record))
        else:
            line = wake_digest.change(notice)
        return f"you subscribed to {sub.describe()}: {line}"
    if sub.kind == "task":
        return f"you subscribed to {sub.describe()}: {who} posted in it"
    if sub.kind == "member":
        return f"you subscribed to {sub.describe()}: {who} posted"
    return f"you subscribed to {sub.describe()}: {who} posted one"


def matches(room: str, record: Any, subs: list[Subscription] | None = None) -> list[Match]:
    """Every subscription ``record`` falls under, one per subscriber.

    A record never matches its own sender's subscriptions, nor those of whoever
    it answers (:func:`_answered`): a subscription wakes you for what others
    start, never for an answer to you, which reaches you only by mentioning
    you. That is what stops two agents subscribed to each other waking each
    other forever, whichever command the answer is posted with. Signals
    (presence, keepalive, pings) match nothing; a notice matches task and
    notice subscriptions; a message matches task, member and search ones.
    """
    subs = load(room) if subs is None else subs
    when = _recorded_at(record)
    sender = norm_handle(record.sender or "") or ""
    answered = _answered(room, record)
    live = [s for s in subs if s.handle != sender and s.handle not in answered and s.live_at(when)]
    if not live:
        return []
    notice = _notice(record)
    said = None if notice is not None else _said(record)
    if notice is None and said is None:
        return []
    from app.services.persister import record_episode

    episode = record_episode(record)
    info = _Room(room)
    queries = [s.target for s in live if s.kind == "search"] if said else []
    hits = _search_hits(room, record, queries) if queries else set()

    found: dict[str, Match] = {}
    for sub in live:
        if sub.handle in found or _outside(room, episode, sub.handle):
            continue
        if sub.kind == "task":
            keys = info.keys(sub.target, sub.parts)
            if notice is not None:
                hit = notice.get("key") in keys and notice.get("subkind") not in UNTOLD
            else:
                hit = episode is not None and any(info.thread_of(k) == episode for k in keys)
        elif sub.kind == "notice":
            if notice is None:
                continue
            kind = str(notice.get("subkind") or "")
            if kind == "upstream":
                kind = f"upstream:{notice.get('change') or ''}"
            hit = kind == sub.target and (sub.task is None or notice.get("key") == sub.task)
        elif sub.kind == "member":
            hit = said is not None and sender == sub.target
        else:
            hit = sub.target in hits
        if hit:
            found[sub.handle] = Match(sub, _why(sub, record, notice))
    return list(found.values())


def end_settled(room: str, record: Any, now: datetime | None = None) -> list[Subscription]:
    """End the task subscriptions whose work a ``resolved`` notice just finished.

    Called once per recorded notice, from the persister's hook, which is not a
    coroutine. It takes no lock: nothing here awaits, and neither does
    :func:`add` or :func:`remove` while holding theirs, so on the one event
    loop a write can't land between this read and this save. The subscription
    is marked ended at that notice, not deleted, so the notice itself still
    matches it for a reader that gets to it later."""
    notice = _notice(record)
    if notice is None or notice.get("subkind") != "resolved":
        return []
    now = now or datetime.now(UTC)
    when = _recorded_at(record)
    info = _Room(room)
    ended: list[Subscription] = []
    subs = load(room)
    for i, sub in enumerate(subs):
        if sub.kind != "task" or sub.ended_at is not None:
            continue
        keys = info.keys(sub.target, sub.parts)
        if notice.get("key") in keys and info.settled(keys, now):
            subs[i] = sub.model_copy(update={"ended_at": when})
            ended.append(subs[i])
    if ended:
        _save(room, [s for s in subs if not _expired(s, now)])
    return ended


def reset() -> None:
    """For tests: forget the room locks and what each agent was answering."""
    _locks.clear()
    _answering.clear()
    _stamps.clear()
