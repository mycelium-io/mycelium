# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The room's day, and the days behind it.

The board answers "what needs me".  This answers "what did we do" — the same
room state, bucketed by calendar day in the reader's own timezone and attributed
to whoever moved it.  Agents and people are the same kind of row here, because
on a shared board they are the same kind of worker.

A day is a *calendar* day, which is why the timezone matters: an agent finishing
at 23:40 in Dublin and a person starting at 08:00 in Denver are only on the same
day if you say which clock you meant.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Frozen in contracts/board-vocabulary.json; the GUI carries the same numbers.
DAILY_GOAL = 6
HEAT_THRESHOLDS = [0, 2, 5, 9]
WEEK_STARTS_ON = "monday"

ENGINES = {"aligner", "synthesizer"}
CHAT_TYPES = {"broadcast", "direct", "announce", "delegate"}

#: Facts the log reads from a truer source than the wire.  A memory write is
#: already counted from the store itself, and a consensus from its episode —
#: re-counting the message announcing each would log the work twice.
SKIP_TYPES = {
    "memory_changed",
    "coordination_consensus",
    "consent_request",
    "presence",
}


@dataclass
class ActivityEvent:
    id: str
    at: datetime
    actor: str
    actor_kind: str
    verb: str
    title: str
    source: str


@dataclass
class ActivitySummary:
    frm: date
    to: date
    events: list[ActivityEvent] = field(default_factory=list)
    active_days: int = 0

    @property
    def by_actor(self) -> list[tuple[str, str, list[ActivityEvent]]]:
        """One lane per actor, busiest first — attribution, not a leaderboard."""
        lanes: dict[str, list[ActivityEvent]] = defaultdict(list)
        kinds: dict[str, str] = {}
        for event in self.events:
            key = event.actor.lower()
            lanes[key].append(event)
            kinds[key] = event.actor_kind
        ordered = sorted(lanes.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        return [(actor, kinds[actor], events) for actor, events in ordered]

    @property
    def by_verb(self) -> list[tuple[str, int]]:
        return Counter(e.verb for e in self.events).most_common()


def zone(name: str | None) -> ZoneInfo:
    """The requested zone, or UTC when it isn't one this machine knows."""
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def parse_instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def day_of(at: datetime, tz: ZoneInfo) -> date:
    """The day an instant falls on, read in ``tz``."""
    return at.astimezone(tz).date()


def actor_kind(handle: str, agents: set[str]) -> str:
    clean = handle.lstrip("@").lower()
    if clean in ENGINES:
        return "engine"
    return "agent" if clean in agents else "human"


def heat_level(count: int) -> int:
    """Five steps, because a heat scale people can read has about five."""
    for level, upper in enumerate(HEAT_THRESHOLDS):
        if count <= upper:
            return level
    return 4


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped.lstrip("# ").strip()[:110]
    return ""


def _describe(message_type: str, content: Any) -> tuple[str, str] | None:
    """What a message says, in the log's terms.

    Coordination payloads are JSON on the wire, so they are read by type rather
    than printed — a log line is who did what, not the envelope they did it in.
    """
    if message_type in CHAT_TYPES:
        text = content if isinstance(content, str) else ""
        return ("posted", _first_line(text) or "a message")
    if not message_type.startswith("coordination_"):
        return None

    raw: dict[str, Any] = {}
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            raw = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            raw = {}
    elif isinstance(content, dict):
        raw = content

    if message_type == "coordination_tick":
        nested = raw.get("payload")
        tick: dict[str, Any] = nested if isinstance(nested, dict) else raw
        who = f"@{tick.get('participant_id')}" if tick.get("participant_id") else "a participant"
        return (
            "negotiated",
            f"round {tick.get('round', '?')} · {who} {tick.get('action', 'replied')}",
        )
    if message_type == "coordination_join":
        return ("joined", str(raw.get("intent") or "the episode"))
    if message_type == "coordination_start":
        return ("opened", f"an episode with {raw.get('agent_count', '?')} agents")
    return (message_type.removeprefix("coordination_"), "")


def project_activity(
    *,
    messages: list[dict],
    memories: list[dict],
    episodes: list[dict],
    agent_handles: list[str],
) -> list[ActivityEvent]:
    """Flatten every timestamped fact the room can tell us into one attributed
    stream.  Nothing is invented: a source that doesn't record who or when
    produces no event."""
    agents = {h.lower() for h in agent_handles}
    events: list[ActivityEvent] = []

    for i, message in enumerate(messages):
        actor = str(message.get("sender_handle") or "").lstrip("@")
        kind = str(message.get("message_type") or message.get("type") or "")
        at = parse_instant(message.get("created_at"))
        if not actor or at is None or kind in SKIP_TYPES:
            continue
        said = _describe(kind, message.get("content"))
        if not said:
            continue
        verb, title = said
        events.append(
            ActivityEvent(
                id=f"msg:{message.get('id', i)}",
                at=at,
                actor=actor,
                actor_kind=actor_kind(actor, agents),
                verb=verb,
                title=title,
                source="channel",
            )
        )

    for memory in memories:
        actor = str(memory.get("updated_by") or memory.get("created_by") or "").lstrip("@")
        at = parse_instant(memory.get("updated_at"))
        if not actor or at is None:
            continue
        version = memory.get("version") or 1
        events.append(
            ActivityEvent(
                id=f"mem:{memory.get('key')}:{version}",
                at=at,
                actor=actor,
                actor_kind=actor_kind(actor, agents),
                verb="revised" if version > 1 else "wrote",
                title=str(memory.get("key") or ""),
                source=f"memory · v{version}",
            )
        )

    for episode in episodes:
        at = parse_instant(episode.get("updated_at"))
        if at is None:
            continue
        subkind = episode.get("subkind") or episode.get("outcome") or ""
        participants = " ".join(f"@{p}" for p in episode.get("participants") or [])
        topic = str(episode.get("topic", "")).split(":")[-1]
        events.append(
            ActivityEvent(
                id=f"ep:{episode.get('short_id')}",
                at=at,
                actor=str(episode.get("updated_by") or "aligner"),
                actor_kind="engine",
                verb="converged" if subkind in ("converged", "resolved") else "mediated",
                title=f"{topic} · {participants}".strip(),
                source=f"episode {episode.get('short_id')}",
            )
        )

    return sorted(events, key=lambda e: e.at, reverse=True)


def by_day(events: list[ActivityEvent], tz: ZoneInfo) -> dict[date, list[ActivityEvent]]:
    days: dict[date, list[ActivityEvent]] = defaultdict(list)
    for event in events:
        days[day_of(event.at, tz)].append(event)
    return dict(days)


def streaks(days: dict[date, list[ActivityEvent]], end: date) -> tuple[int, int]:
    """Current and longest runs of days with any activity.

    Today not having started yet shouldn't break yesterday's run, so a current
    streak may end on either.
    """
    active = {day for day, events in days.items() if events}

    current = 0
    cursor = end if end in active else end - timedelta(days=1)
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    previous: date | None = None
    for day in sorted(active):
        run = run + 1 if previous and previous + timedelta(days=1) == day else 1
        longest = max(longest, run)
        previous = day

    return current, longest


def summarize_activity(
    days: dict[date, list[ActivityEvent]], frm: date, to: date
) -> ActivitySummary:
    events: list[ActivityEvent] = []
    active = 0
    cursor = frm
    while cursor <= to:
        for_day = days.get(cursor, [])
        if for_day:
            active += 1
        events.extend(for_day)
        cursor += timedelta(days=1)
    return ActivitySummary(
        frm=frm, to=to, events=sorted(events, key=lambda e: e.at, reverse=True), active_days=active
    )


def week_start(day: date) -> date:
    """Monday of the week `day` falls in."""
    return day - timedelta(days=day.weekday())
