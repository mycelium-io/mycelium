# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Schedules: an agent's recurring check-in, owned and fired by the hub.

A schedule says "wake @handle every 17 minutes (or on this cron line), and tell
it this". The hub keeps it, so it outlives the agent's session, shows up for
anyone looking at the room, and can be paused, edited or run by a person.

**The hub fires it, through the wake path a mention uses.** A herdr-present
owner gets its doorbell rung (``reason: schedule``), which herdr holds while the
agent is mid-turn; any other owner gets the wake handed to it by its next
``await``, which is when a resident loop is free to take a turn. Either way a
wake already waiting is not queued twice: the run records ``held`` instead.

**Missed runs coalesce.** A schedule that comes due while the hub was down, or
several times over in one look, fires once, with how many runs it stood in for.

**A cheap pre-check decides whether the model wakes at all.** ``check`` names a
query the hub answers in code, from a closed set (:data:`CHECKS`), never a
script: anyone who can reach a hub can write a schedule, so a schedule cannot
be a way to run something on it. When the check finds nothing, the run is
``quiet``: it is recorded on the schedule and costs no model turn. What it
found is handed to the agent with the wake.

**Nothing a schedule does is said in the room.** A quiet run posts nothing, and
a run that wakes reaches only its owner. What changed is published on the
room's event bus (``schedule_changed``) so the app redraws its list.

The store is one JSON file per room (``.schedules.json`` beside ``.room.json``),
not memories: a run writes ``last_run`` and its history every time it fires,
and none of that is something to index, version or link.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.bus import bus, room_channel
from app.config import settings
from app.services import assignments
from app.services.agent_registry import norm_handle
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    list_room_names,
    room_exists,
)

logger = logging.getLogger(__name__)

STORE_FILE = ".schedules.json"
EVENT_TYPE = "schedule_changed"

#: Runs kept per schedule. Quiet runs are most of them; the app collapses those.
HISTORY_KEPT = 30
#: Findings handed over with one wake; the rest are counted.
FINDINGS_SHOWN = 10

Result = Literal["woke", "quiet", "held", "busy", "error"]

#: The pre-checks a schedule can name. ``search:<query>`` is the one with an
#: argument: the room's message search grammar, counting only what arrived since
#: the last run.
CHECKS: dict[str, str] = {
    "always": "wake every time (no pre-check)",
    "mentions": "messages addressed to the owner since the last run",
    "assigned": "open rows for the owner that nobody holds",
    "stale": "rows the owner holds whose lease is stale or expired",
    "silent": "rows someone else holds whose lease lapsed while they are absent",
    "task": "the schedule's task thread moved since the last run",
    "search:<query>": "messages matching a room search since the last run",
}


class ScheduleError(ValueError):
    """A schedule the hub refuses, with the reason a caller is shown."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


# ── the stored shape ─────────────────────────────────────────────────────────


class ScheduleRun(BaseModel):
    """One time a schedule came due (or was run by hand)."""

    at: datetime
    result: Result
    trigger: Literal["schedule", "manual"] = "schedule"
    #: Runs this one stood in for (missed while the hub was down, or between looks).
    missed: int = 0
    #: What the pre-check found, cut to :data:`FINDINGS_SHOWN` lines.
    found: list[str] = Field(default_factory=list)
    found_total: int = 0
    detail: str | None = None


class Schedule(BaseModel):
    name: str
    owner: str
    every_s: int | None = None
    cron: str | None = None
    prompt: str = ""
    check: str = "always"
    task: str | None = None
    paused: bool = False
    created_by: str = "unknown"
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    next_run: datetime | None = None
    last_run: datetime | None = None
    last_result: Result | None = None
    runs: int = 0
    wakes: int = 0
    quiet: int = 0
    history: list[ScheduleRun] = Field(default_factory=list)

    def state(self, now: datetime) -> str:
        if self.expires_at <= now:
            return "expired"
        return "paused" if self.paused else "active"


# ── when: intervals and cron lines ───────────────────────────────────────────

_EVERY = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_every(raw: str) -> int:
    """``"17m"`` → 1020. Seconds, minutes, hours or days, one unit."""
    match = _EVERY.match(raw or "")
    if not match:
        raise ScheduleError(f"every '{raw}' is not an interval like 30m, 2h or 1d")
    return int(match.group(1)) * _UNIT_S[match.group(2)]


def format_every(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


@dataclass(frozen=True)
class Cron:
    """A five-field cron line (minute hour day-of-month month day-of-week), UTC."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    any_day: bool
    any_weekday: bool

    def matches_day(self, when: datetime) -> bool:
        dom = when.day in self.days
        dow = (when.isoweekday() % 7) in self.weekdays
        # Standard cron: when both day fields are restricted, either one matches.
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return dow
        if self.any_weekday:
            return dom
        return dom or dow

    def next_after(self, after: datetime) -> datetime:
        """The first minute strictly after ``after`` this line fires on."""
        when = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = when + timedelta(days=366 * 4)
        while when < limit:
            if when.month not in self.months:
                when = (when.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if not self.matches_day(when):
                when = when.replace(hour=0, minute=0) + timedelta(days=1)
                continue
            if when.hour not in self.hours:
                when = when.replace(minute=0) + timedelta(hours=1)
                continue
            if when.minute not in self.minutes:
                when += timedelta(minutes=1)
                continue
            return when
        raise ScheduleError("cron line never fires")


_CRON_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_CRON_NAMES = ("minute", "hour", "day of month", "month", "day of week")


def _cron_field(raw: str, low: int, high: int, name: str) -> tuple[frozenset[int], bool]:
    values: set[int] = set()
    for part in raw.split(","):
        base, _, step_raw = part.partition("/")
        try:
            step = int(step_raw) if step_raw else 1
            if base == "*":
                start, end = low, high
            elif "-" in base:
                a, b = base.split("-", 1)
                start, end = int(a), int(b)
            else:
                start = int(base)
                end = high if step_raw else start
        except ValueError:
            raise ScheduleError(f"cron {name} '{raw}' is not a number, range or */n") from None
        if step < 1 or start < low or end > high or start > end:
            raise ScheduleError(f"cron {name} '{raw}' is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return frozenset(values), raw == "*"


def parse_cron(raw: str) -> Cron:
    fields = (raw or "").split()
    if len(fields) != 5:
        raise ScheduleError(
            f"cron '{raw}' needs five fields: minute hour day-of-month month day-of-week"
        )
    parsed = [
        _cron_field(f, low, high, name)
        for f, (low, high), name in zip(fields, _CRON_RANGES, _CRON_NAMES, strict=True)
    ]
    weekdays = frozenset(d % 7 for d in parsed[4][0])
    return Cron(
        minutes=parsed[0][0],
        hours=parsed[1][0],
        days=parsed[2][0],
        months=parsed[3][0],
        weekdays=weekdays,
        any_day=parsed[2][1],
        any_weekday=parsed[4][1],
    )


def next_run(schedule: Schedule, after: datetime) -> datetime:
    if schedule.cron:
        return parse_cron(schedule.cron).next_after(after)
    return after + timedelta(seconds=schedule.every_s or settings.SCHEDULE_MIN_INTERVAL_S)


def _shortest_gap(cron: Cron, now: datetime) -> float:
    """The shortest wait between two of the line's next few dozen fires, in seconds."""
    when = cron.next_after(now)
    gap = float("inf")
    for _ in range(48):
        nxt = cron.next_after(when)
        gap = min(gap, (nxt - when).total_seconds())
        when = nxt
    return gap


def validate_when(
    every: str | None, cron: str | None, now: datetime
) -> tuple[int | None, str | None]:
    """The interval or cron line a schedule fires on, held to the minimum interval."""
    if bool(every) == bool(cron):
        raise ScheduleError("a schedule needs exactly one of every or cron")
    floor = settings.SCHEDULE_MIN_INTERVAL_S
    if every:
        seconds = parse_every(every)
        if seconds < floor:
            raise ScheduleError(
                f"every {every} is more often than the hub's minimum, {format_every(floor)}"
            )
        return seconds, None
    line = " ".join((cron or "").split())
    if _shortest_gap(parse_cron(line), now) < floor:
        raise ScheduleError(
            f"cron '{line}' fires more often than the hub's minimum, {format_every(floor)}"
        )
    return None, line


def validate_check(check: str | None) -> str:
    raw = (check or "always").strip()
    if raw.startswith("search:"):
        if not raw.removeprefix("search:").strip():
            raise ScheduleError("check search: needs a query, like search:mentions:me")
        return raw
    if raw not in CHECKS:
        names = ", ".join(CHECKS)
        raise ScheduleError(f"check '{raw}' is not one the hub runs; use one of {names}")
    return raw


# ── the store ────────────────────────────────────────────────────────────────

_locks: dict[str, asyncio.Lock] = {}


def _lock(room: str) -> asyncio.Lock:
    return _locks.setdefault(room, asyncio.Lock())


def _path(room: str):
    return get_room_dir(room) / STORE_FILE


def load(room: str) -> dict[str, Schedule]:
    """Every schedule in ``room``, by name. One that no longer parses is skipped."""
    path = _path(room)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("schedules: %s is unreadable; reading none", path)
        return {}
    out: dict[str, Schedule] = {}
    for item in raw.get("schedules", []) if isinstance(raw, dict) else []:
        try:
            schedule = Schedule.model_validate(item)
        except ValueError:
            logger.warning("schedules: skipping an unreadable schedule in %s", room)
            continue
        out[schedule.name] = schedule
    return out


def _save(room: str, schedules: dict[str, Schedule]) -> None:
    path = _path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schedules": [s.model_dump(mode="json") for s in schedules.values()]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _changed(room: str, name: str, *, removed: bool = False) -> None:
    bus.publish(
        room_channel(room),
        {
            "type": EVENT_TYPE,
            "room_name": room,
            "name": name,
            "removed": removed,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def get(room: str, name: str) -> Schedule:
    schedule = load(room).get(name)
    if schedule is None:
        raise ScheduleError(f"no schedule '{name}' in {room}", status=404)
    return schedule


def _row_exists(room: str, key: str) -> bool:
    return (get_room_dir(room) / f"{key}.md").exists()


async def create(
    room: str,
    *,
    name: str,
    owner: str,
    every: str | None,
    cron: str | None,
    prompt: str,
    check: str | None,
    task: str | None,
    expires_in_days: float | None,
    created_by: str,
    now: datetime | None = None,
) -> Schedule:
    now = now or datetime.now(UTC)
    handle = norm_handle(owner)
    if not handle:
        raise ScheduleError("a schedule needs an owner")
    every_s, line = validate_when(every, cron, now)
    check = validate_check(check)
    if task and not _row_exists(room, task):
        raise ScheduleError(f"no row '{task}' in {room} to bind the schedule to")
    if check == "task" and not task:
        raise ScheduleError("check task needs the schedule bound to a task")
    async with _lock(room):
        schedules = load(room)
        if name in schedules:
            raise ScheduleError(f"a schedule '{name}' already exists in {room}", status=409)
        mine = [s for s in schedules.values() if s.owner == handle and s.state(now) != "expired"]
        if len(mine) >= settings.SCHEDULE_MAX_PER_AGENT:
            raise ScheduleError(
                f"@{handle} already has {len(mine)} schedules in {room}, the most one agent may hold",
                status=409,
            )
        schedule = Schedule(
            name=name,
            owner=handle,
            every_s=every_s,
            cron=line,
            prompt=prompt,
            check=check,
            task=task,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            expires_at=now + _ttl(expires_in_days),
        )
        schedule.next_run = next_run(schedule, now)
        schedules[name] = schedule
        _save(room, schedules)
    _changed(room, name)
    return schedule


def _ttl(days: float | None) -> timedelta:
    default = settings.SCHEDULE_DEFAULT_TTL_DAYS
    most = settings.SCHEDULE_MAX_TTL_DAYS
    chosen = default if days is None else days
    if chosen <= 0 or chosen > most:
        raise ScheduleError(f"a schedule lasts more than 0 and at most {most:g} days")
    return timedelta(days=chosen)


async def update(
    room: str,
    name: str,
    *,
    every: str | None = None,
    cron: str | None = None,
    prompt: str | None = None,
    check: str | None = None,
    task: str | None = None,
    paused: bool | None = None,
    renew_days: float | None = None,
    renew: bool = False,
    now: datetime | None = None,
) -> Schedule:
    """Change what a schedule does; only the fields given move."""
    now = now or datetime.now(UTC)
    async with _lock(room):
        schedules = load(room)
        schedule = schedules.get(name)
        if schedule is None:
            raise ScheduleError(f"no schedule '{name}' in {room}", status=404)
        retimed = False
        if every or cron:
            schedule.every_s, schedule.cron = validate_when(every, cron, now)
            retimed = True
        if prompt is not None:
            schedule.prompt = prompt
        if task is not None:
            if task and not _row_exists(room, task):
                raise ScheduleError(f"no row '{task}' in {room} to bind the schedule to")
            schedule.task = task or None
        if check is not None:
            schedule.check = validate_check(check)
        if schedule.check == "task" and not schedule.task:
            raise ScheduleError("check task needs the schedule bound to a task")
        if renew or renew_days is not None:
            schedule.expires_at = now + _ttl(renew_days)
            retimed = retimed or schedule.next_run is None or schedule.next_run <= now
        if paused is not None and paused != schedule.paused:
            schedule.paused = paused
            # Resuming starts the clock again rather than firing for the pause.
            retimed = retimed or not paused
        if retimed:
            schedule.next_run = next_run(schedule, now)
        schedule.updated_at = now
        _save(room, schedules)
    _changed(room, name)
    return schedule


async def remove(room: str, name: str) -> None:
    async with _lock(room):
        schedules = load(room)
        if schedules.pop(name, None) is None:
            raise ScheduleError(f"no schedule '{name}' in {room}", status=404)
        _save(room, schedules)
    _pending.get(room, {}).pop(name, None)
    _changed(room, name, removed=True)


# ── pre-checks ───────────────────────────────────────────────────────────────


def _records(room: str) -> list[Any]:
    from app.services import room_channels

    managed = room_channels.manager.get(room)
    return managed.persister.log.records if managed and managed.persister else []


def _since_records(room: str, since: datetime | None) -> list[Any]:
    from app.services.persister import parse_recorded_at

    out = []
    for record in _records(room):
        at = parse_recorded_at(record.recorded_at)
        if since is None or (at is not None and at > since):
            out.append(record)
    return out


def _title(key: str, content: str) -> str:
    first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
    return first.lstrip("# ").strip()


def _board(room: str) -> list[tuple[str, dict, str]]:
    room_dir = get_room_dir(room)
    rows: list[tuple[str, dict, str]] = []
    for namespace in assignments.ASSIGNABLE_NAMESPACES:
        rows.extend(list_memory_files(room_dir, prefix=f"{namespace}/"))
    return rows


def _present(room: str) -> set[str]:
    from app.services import room_channels

    manager = room_channels.manager
    return set(manager.members(room)) | set(manager.presence(room))


def _check_mentions(room: str, schedule: Schedule, since: datetime | None) -> list[str]:
    from app.routes.participate import _addressed_to
    from app.services.persister import _conversational_text

    found = []
    for record in _since_records(room, since):
        if not _addressed_to(record.content, schedule.owner):
            continue
        text = (_conversational_text(record.content) or "").strip().splitlines()
        found.append(f"@{record.sender}: {text[0][:120] if text else '(no text)'}")
    return found


def _check_assigned(room: str, schedule: Schedule, now: datetime) -> list[str]:
    found = []
    for key, meta, content in _board(room):
        if assignments.settled(meta, now) or norm_handle(meta.get("assignee")) != schedule.owner:
            continue
        state = assignments.state_of(meta, now)
        if state == "held":
            continue
        found.append(f'{key} "{_title(key, content)}" is for you and {state}')
    return found


def _check_stale(room: str, schedule: Schedule, now: datetime) -> list[str]:
    found = []
    for key, meta, content in _board(room):
        if (
            meta.get(assignments.FIELD) != "held"
            or norm_handle(meta.get("owner")) != schedule.owner
        ):
            continue
        fresh = assignments.freshness(meta, now)
        if fresh in ("stale", "expired", None):
            found.append(f'{key} "{_title(key, content)}": your lease is {fresh or "undated"}')
    return found


def _check_silent(room: str, schedule: Schedule, now: datetime) -> list[str]:
    """Rows held by someone who let the lease lapse and is not in the room."""
    present = _present(room)
    found = []
    for key, meta, content in _board(room):
        if meta.get(assignments.FIELD) != "held" or assignments.settled(meta, now):
            continue
        holder = norm_handle(meta.get("owner"))
        if not holder or holder == schedule.owner:
            continue
        if assignments.freshness(meta, now) not in ("stale", "expired", None):
            continue
        if holder in present:
            continue
        since = assignments._parse(meta.get("claimed_at"))
        age = f", claimed {_ago(since, now)}" if since else ""
        found.append(f'{key} "{_title(key, content)}": @{holder} went quiet{age}')
    return found


def _check_task(room: str, schedule: Schedule, since: datetime | None) -> list[str]:
    from app.services import tasks
    from app.services.persister import _conversational_text, record_episode

    if not schedule.task:
        return []
    episode = tasks.episode_of(room, schedule.task)
    if not episode:
        return []
    found = []
    for record in _since_records(room, since):
        if record_episode(record) != episode or norm_handle(record.sender) == schedule.owner:
            continue
        text = (_conversational_text(record.content) or "").strip().splitlines()
        if text:
            found.append(f"@{record.sender} in {schedule.task}: {text[0][:120]}")
    return found


def _check_search(room: str, query: str, since: datetime | None) -> list[str]:
    from app.routes.messages import _read_messages, _resolve_channel
    from app.services import message_search

    channel, coord = _resolve_channel(room)
    result = message_search.search(channel, _read_messages(channel, coord), query, limit=200)
    found = []
    for hit in result.hits:
        message = hit.doc.message
        at = (
            message.created_at
            if message.created_at.tzinfo
            else message.created_at.replace(tzinfo=UTC)
        )
        if since is not None and at <= since:
            continue
        found.append(f"@{message.sender_handle}: {hit.snippet or message.content}"[:160])
    return found


#: ``me`` in a handle field of a ``search:`` check is the schedule's owner.
_ME = re.compile(r"\b(from|to|mentions):me\b")


def run_check(room: str, schedule: Schedule, now: datetime) -> list[str] | None:
    """What the pre-check found, or ``None`` for a schedule that always wakes."""
    since = schedule.last_run
    check = schedule.check
    if check == "always":
        return None
    if check == "mentions":
        return _check_mentions(room, schedule, since)
    if check == "assigned":
        return _check_assigned(room, schedule, now)
    if check == "stale":
        return _check_stale(room, schedule, now)
    if check == "silent":
        return _check_silent(room, schedule, now)
    if check == "task":
        return _check_task(room, schedule, since)
    if check.startswith("search:"):
        query = _ME.sub(rf"\1:{schedule.owner}", check.removeprefix("search:").strip())
        return _check_search(room, query, since)
    raise ScheduleError(f"check '{check}' is not one the hub runs")


def _ago(then: datetime, now: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 60 * 48:
        return f"{minutes // 60}h ago"
    return f"{minutes // 1440}d ago"


# ── waking the owner ─────────────────────────────────────────────────────────

#: Wakes for owners with no herdr pane, handed over by their next ``await``:
#: room → schedule name → the wake. One per schedule, so missed runs coalesce.
_pending: dict[str, dict[str, dict[str, Any]]] = {}


def pending_for(room: str, handle: str) -> list[dict[str, Any]]:
    return [w for w in _pending.get(room, {}).values() if w["handle"] == handle]


def take_pending(room: str, handle: str, episode: str | None = None) -> dict[str, Any] | None:
    """The oldest schedule wake waiting for ``handle``, taken off the queue.

    ``episode`` is what an ``await`` is scoped to: a room-wide await takes any
    of the handle's wakes, a thread-scoped one only a wake bound to that thread.
    """
    queue = _pending.get(room)
    if not queue:
        return None
    for name, wake in sorted(queue.items(), key=lambda kv: kv[1]["queued_at"]):
        if wake["handle"] != handle:
            continue
        if episode and wake.get("episode") != episode:
            continue
        del queue[name]
        return wake
    return None


def _thread_of(room: str, schedule: Schedule) -> str | None:
    if not schedule.task:
        return None
    from app.services import tasks

    return tasks.episode_of(room, schedule.task)


def wake_text(schedule: Schedule, run: ScheduleRun, room: str) -> str:
    """What the owner is told when its schedule wakes it."""
    when = (
        f"every {format_every(schedule.every_s)}" if schedule.every_s else f"cron {schedule.cron}"
    )
    lines = [f'Your schedule "{schedule.name}" fired ({when}).']
    if run.missed:
        lines.append(f"It stands in for {run.missed} missed run(s).")
    if schedule.prompt:
        lines += ["", schedule.prompt]
    if run.found:
        lines += ["", f"The {schedule.check} check found {run.found_total}:"]
        lines += [f"- {line}" for line in run.found]
        if run.found_total > len(run.found):
            lines.append(f"- and {run.found_total - len(run.found)} more")
    if schedule.task:
        lines += ["", f"Reply in its task: mycelium respond --task {schedule.task} --room {room}"]
    return "\n".join(lines)


def _wake_owner(room: str, schedule: Schedule, run: ScheduleRun, now: datetime) -> Result:
    """Hand the owner its wake, unless one is already waiting for it."""
    from app.services import room_channels

    manager = room_channels.manager
    owner = schedule.owner
    episode = _thread_of(room, schedule)
    if manager.herdr_status(room, owner) is not None:
        if owner in manager.pending_herdr_wakes(room):
            return "held"
        manager.enqueue_herdr_wake(
            room,
            owner,
            reason="schedule",
            key=schedule.task,
            title=schedule.name,
            sender="scheduler",
            episode=episode,
        )
        return "woke"
    queue = _pending.setdefault(room, {})
    if schedule.name in queue:
        return "held"
    queue[schedule.name] = {
        "handle": owner,
        "schedule": schedule.name,
        "episode": episode,
        "task": schedule.task,
        "prompt": wake_text(schedule, run, room),
        "queued_at": now.isoformat(),
    }
    return "woke"


def _busy(room: str, handle: str) -> bool:
    from app.services import room_channels

    return room_channels.manager.herdr_status(room, handle) in {"working", "blocked"}


async def fire(
    room: str,
    name: str,
    *,
    now: datetime | None = None,
    trigger: Literal["schedule", "manual"] = "schedule",
    wake: bool = False,
) -> ScheduleRun:
    """Run one schedule now: its pre-check, then its wake if the check found anything.

    ``wake`` skips the pre-check (a person's "run now and wake it"). A scheduled
    run moves ``next_run`` on past ``now``, coalescing whatever it missed; a
    manual one leaves the timetable alone.
    """
    now = now or datetime.now(UTC)
    async with _lock(room):
        schedules = load(room)
        schedule = schedules.get(name)
        if schedule is None:
            raise ScheduleError(f"no schedule '{name}' in {room}", status=404)
        missed = 0
        if trigger == "schedule" and schedule.next_run is not None:
            when = schedule.next_run
            nxt = next_run(schedule, when)
            while nxt <= now and missed < 10_000:
                missed += 1
                nxt = next_run(schedule, nxt)
            schedule.next_run = nxt if nxt > now else next_run(schedule, now)
        run = ScheduleRun(at=now, result="quiet", trigger=trigger, missed=missed)
        if not wake and _busy(room, schedule.owner):
            # Mid-turn: the agent is already working, so a check-in would only
            # queue behind it. Try again on the next run.
            run.result = "busy"
        else:
            try:
                found = None if wake else run_check(room, schedule, now)
            except Exception as exc:  # a broken check is the schedule's news, not the loop's
                logger.exception("schedule %s/%s: check failed", room, name)
                run.result = "error"
                run.detail = str(exc)[:200]
            else:
                if found is not None:
                    run.found = found[:FINDINGS_SHOWN]
                    run.found_total = len(found)
                if found is None or found:
                    run.result = _wake_owner(room, schedule, run, now)
        schedule.last_run = now
        schedule.last_result = run.result
        schedule.runs += 1
        if run.result == "woke":
            schedule.wakes += 1
        elif run.result == "quiet":
            schedule.quiet += 1
        schedule.history = [run, *schedule.history][:HISTORY_KEPT]
        _save(room, schedules)
    _changed(room, name)
    return run


# ── the loop ─────────────────────────────────────────────────────────────────


def due(room: str, now: datetime) -> list[str]:
    return [
        s.name
        for s in load(room).values()
        if s.state(now) == "active" and s.next_run is not None and s.next_run <= now
    ]


async def sweep(now: datetime | None = None) -> list[tuple[str, str, Result]]:
    """Fire every schedule that has come due, across every room."""
    now = now or datetime.now(UTC)
    fired: list[tuple[str, str, Result]] = []
    for room in list_room_names():
        if not room_exists(room):
            continue
        for name in due(room, now):
            try:
                run = await fire(room, name, now=now)
            except Exception:  # one schedule must not stop the rest
                logger.exception("schedule sweep: %s/%s failed", room, name)
                continue
            fired.append((room, name, run.result))
    return fired


_sweep_task: asyncio.Task[None] | None = None


async def _loop() -> None:
    while True:
        try:
            await sweep()
        except Exception:
            logger.exception("schedule sweep iteration failed")
        await asyncio.sleep(settings.SCHEDULE_TICK_S)


def start_sweep() -> None:
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.get_running_loop().create_task(_loop())


def stop_sweep() -> None:
    global _sweep_task
    if _sweep_task is not None and not _sweep_task.done():
        _sweep_task.cancel()
    _sweep_task = None


def reset() -> None:
    """Forget the in-process wake queue. For tests."""
    _pending.clear()
    _locks.clear()


def owners(room: str, now: datetime | None = None) -> dict[str, int]:
    """Handle → how many live schedules it owns, for the members read."""
    now = now or datetime.now(UTC)
    out: dict[str, int] = {}
    for schedule in load(room).values():
        if schedule.state(now) != "expired":
            out[schedule.owner] = out.get(schedule.owner, 0) + 1
    return out
