# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ends a hold with no timer, and what says a held row has gone quiet.

A row given to someone, or claimed with no time limit, is held until one of
these ends it. Each is said on the room's timeline:

- **The holder's herdr pane closed.** A connected runner's machine report
  (``RunnerHello.machine``) lists every herdr agent on its machine. When every
  pane reported for the holder reads ``gone`` on two sweeps in a row, its rows
  are released.
- **The holder was removed from the room.** Deleting an agent's
  ``agents/<handle>`` manifest releases its rows at once
  (:func:`holder_removed`, called by the memory delete route).
- **No sign of the holder at all, for a long time.** A holder the hub has no
  signal for (no pane on any runner, no herdr presence, no ``await``) keeps
  the row for :data:`FALLBACK_HOURS` of no activity on it, then it expires
  with a notice. A holder the hub can see is never expired for being slow.

A row that has had no activity (nothing in its thread, no edit, no notice such
as a pull request changing) for :data:`QUIET_HOURS` gets a ``quiet`` notice on
the room's timeline, once per hold. It is never released for that, and the
notice wakes nobody: no process of the hub's own posts a message or rings an
agent. A row waiting on someone else, because its pull request is open and
awaiting review or a merge, or because it names a blocker, is not quiet and
doesn't expire.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services import assignments, message_format
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_memory_files,
    list_room_names,
    system_meta,
)

logger = logging.getLogger(__name__)

#: Hours of no activity on a row before the timeline says it has gone quiet.
QUIET_HOURS = 3
#: Hours of no activity, with no sign of the holder anywhere, before it expires.
FALLBACK_HOURS = 8
#: The frontmatter that remembers a hold was said to be quiet, so it's said once.
QUIET_FIELD = "hold_flagged_at"
#: The notice that says so. Like every notice it wakes nobody.
QUIET_NOTICE = "quiet"
#: A linked pull request in one of these states waits on someone other than
#: the holder: a review, a merge, or CI that is still running.
WAITING_PR_STATES = ("ok", "pending")
#: Sweeps in a row a holder's pane must read closed before its rows are released.
CLOSED_SWEEPS = 2

#: How many sweeps in a row each ``(room, handle)`` has read closed.
_closed_sweeps: dict[tuple[str, str], int] = {}


def _stamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def pane_states(room: str, handle: str) -> list[str]:
    """What every connected runner's machine says about ``handle``'s herdr panes."""
    from app.services.runners import registry

    found: list[str] = []
    for runner in registry.all():
        if not runner.connected or runner.machine is None:
            continue
        for workspace in runner.machine.workspaces:
            found += [a.state for a in workspace.agents if a.room == room and a.handle == handle]
    return found


def signal_of(room: str, handle: str) -> str:
    """What the hub can see of ``handle``: ``person``, ``engine``, ``closed``
    (every herdr pane it had is closed), ``present`` or ``unseen``.

    A handle with no manifest and no user record is ``unseen``, not gone: a
    person who never set up a user record looks the same. Leaving the room ends
    a hold only when an agent is removed (:func:`holder_removed`)."""
    from app.services.principals import classify_sender
    from app.services.room_channels import manager

    kind = classify_sender(room, handle)
    if kind == "user":
        return "person"
    if kind == "engine":
        return "engine"
    panes = pane_states(room, handle)
    if panes and all(state == "gone" for state in panes):
        return "closed"
    if any(state != "gone" for state in panes):
        return "present"
    if manager.herdr_status(room, handle) is not None or handle in manager.members(room):
        return "present"
    return "unseen"


def last_activity(room: str, key: str, meta: dict) -> datetime | None:
    """The newest thing that happened on a row: an edit, a message in its
    thread, or a notice about it (a pull request changing, say)."""
    from app.services.persister import parse_recorded_at, record_episode
    from app.services.room_channels import manager

    # The sweep's own writes and lines are not activity, or flagging a quiet row
    # would make it look busy.
    edited = (
        None if meta.get("updated_by") == assignments.RUNTIME_AUTHOR else meta.get("updated_at")
    )
    stamps = [_stamp(edited), _stamp(meta.get("claimed_at")), _stamp(meta.get("created_at"))]
    episode = system_meta(meta).get(EPISODE_META)
    managed = manager.get(room)
    records = managed.persister.log.records if managed and managed.persister else []
    for record in reversed(records):
        if record.sender == message_format.SYSTEM_ACTOR_ID and record_episode(record) == episode:
            continue
        if episode and record_episode(record) == episode:
            stamps.append(parse_recorded_at(record.recorded_at))
            break
        payload = (record.content.get("l9") or {}).get("payload") or {}
        data = payload.get("data") or {}
        if (
            payload.get("type") == message_format.NOTICE_PAYLOAD_TYPE
            and data.get("key") == key
            and data.get("subkind") != QUIET_NOTICE
        ):
            stamps.append(parse_recorded_at(record.recorded_at))
            break
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


def open_pull_requests(room: str) -> dict[str, list[dict[str, Any]]]:
    """The last reading of each pull request the room links, by the row that
    links it (``.upstream-seen.json``, kept by the status watcher)."""
    from app.services.status import discovery, registry
    from app.services.status.watch import load_seen

    runtime = registry.get_runtime()
    seen = load_seen(room)
    by_row: dict[str, list[dict[str, Any]]] = {}
    for item in discovery.discover(room, runtime):
        reading = seen.get(str(item.ref))
        if reading is None:
            continue
        for origin in item.origins:
            if origin.startswith("memory:"):
                by_row.setdefault(origin.removeprefix("memory:"), []).append(reading)
    return by_row


def waiting_on_someone(meta: dict, readings: list[dict[str, Any]]) -> bool:
    """Whether the row's next step is someone else's: a blocker it names, or a
    linked pull request that is open and waiting on a review, a merge or CI.
    A draft, a failing check or requested changes are the holder's to act on."""
    if meta.get("blocked_by"):
        return True
    for reading in readings:
        detail = reading.get("detail") or {}
        if detail.get("pr") != "OPEN" or reading.get("label") == "draft":
            continue
        if reading.get("state") in WAITING_PR_STATES:
            return True
    return False


async def _note_quiet(room: str, key: str, meta: dict, content: str, who: str, hours: int) -> None:
    """Say on the timeline that a held row has gone quiet, once per hold. A
    notice: it posts nothing in the thread and wakes nobody."""
    from app.services.fields import upsert_patch

    await assignments.raise_notice(
        room,
        key,
        QUIET_NOTICE,
        assignments.RUNTIME_AUTHOR,
        why=f"nothing on it for {hours}h; @{who} holds it",
    )
    await upsert_patch(
        room,
        key,
        meta,
        content,
        {QUIET_FIELD: datetime.now(UTC).isoformat()},
        assignments.RUNTIME_AUTHOR,
        notify=False,
    )


async def _end(room: str, key: str, why: str, subkind: str, by: str, now: datetime) -> None:
    """End a hold: the row goes back to the pool with a runtime note saying why."""
    await assignments.end_hold(room, key, why, subkind=subkind, by=by, now=now)


async def holder_removed(room: str, handle: str, now: datetime | None = None) -> list[str]:
    """Release every row ``handle`` holds in ``room``, because the agent was
    removed from it. Returns the keys released."""
    now = now or datetime.now(UTC)
    handle = handle.lstrip("@")
    released: list[str] = []
    room_dir = get_room_dir(room)
    for namespace in assignments.ASSIGNABLE_NAMESPACES:
        for key, meta, _content in list_memory_files(room_dir, prefix=f"{namespace}/"):
            if assignments.holder(meta, now) != handle:
                continue
            why = f"@{handle} was removed from the room"
            await _end(room, key, why, "released", assignments.RUNTIME_AUTHOR, now)
            released.append(key)
    return released


async def sweep(now: datetime | None = None) -> list[tuple[str, str, str]]:
    """End or flag every hold the evidence says to. Returns ``(room, key, what)``."""
    now = now or datetime.now(UTC)
    done: list[tuple[str, str, str]] = []
    # Each holder is read once per sweep, however many rows it holds, so the
    # closed-pane count goes up once per sweep.
    signals: dict[tuple[str, str], str] = {}
    for room in list_room_names():
        room_dir = get_room_dir(room)
        prs = _PullRequests(room)
        for namespace in assignments.ASSIGNABLE_NAMESPACES:
            for key, meta, content in list_memory_files(room_dir, prefix=f"{namespace}/"):
                if assignments.state_of(meta, now) != "held" or not assignments.open_ended(meta):
                    continue
                who = assignments.holder(meta, now)
                if not who:
                    continue
                try:
                    if (room, who) not in signals:
                        signals[room, who] = _read(room, who)
                    what = await _one(room, key, meta, content, who, signals[room, who], now, prs)
                except Exception:  # one row must not stop the others
                    logger.exception("hold sweep failed on %s/%s", room, key)
                    continue
                if what:
                    done.append((room, key, what))
    return done


class _PullRequests:
    """A room's linked pull requests, read the first time a row needs them."""

    def __init__(self, room: str) -> None:
        self.room = room
        self._by_row: dict[str, list[dict[str, Any]]] | None = None

    def of(self, key: str) -> list[dict[str, Any]]:
        if self._by_row is None:
            try:
                self._by_row = open_pull_requests(self.room)
            except Exception:  # no status runtime: no pull request to wait on
                logger.debug("hold sweep: no pull requests read for %s", self.room)
                self._by_row = {}
        return self._by_row.get(key, [])


def _read(room: str, who: str) -> str:
    """``who``'s signal for this sweep, counting the sweeps in a row its pane
    has read closed."""
    seen = signal_of(room, who)
    if seen == "closed":
        _closed_sweeps[room, who] = _closed_sweeps.get((room, who), 0) + 1
    else:
        _closed_sweeps.pop((room, who), None)
    return seen


async def _one(
    room: str,
    key: str,
    meta: dict,
    content: str,
    who: str,
    seen: str,
    now: datetime,
    prs: _PullRequests | None = None,
) -> str | None:
    runtime = assignments.RUNTIME_AUTHOR
    # While an agent restarts, a runner can report only its old, closed pane
    # until the new one is mapped, so a pane must read closed on two sweeps in
    # a row before the row is released.
    if seen == "closed":
        if _closed_sweeps.get((room, who), 0) >= CLOSED_SWEEPS:
            await _end(room, key, f"@{who}'s herdr pane closed", "released", runtime, now)
            return "released"
        return None
    last = last_activity(room, key, meta) or now
    quiet = now - last
    if quiet < timedelta(hours=QUIET_HOURS) or seen == "person":
        return None
    # Waiting on a review, a merge or a blocker is not going quiet.
    if waiting_on_someone(meta, (prs or _PullRequests(room)).of(key)):
        return None
    if seen == "unseen" and quiet >= timedelta(hours=FALLBACK_HOURS):
        why = f"expired: no sign of @{who} and nothing on this row for {FALLBACK_HOURS}h"
        await _end(room, key, why, "expired", who, now)
        return "expired"
    noted = _stamp(meta.get(QUIET_FIELD))
    since = _stamp(meta.get("claimed_at")) or _stamp(meta.get("created_at"))
    if noted is not None and (since is None or noted >= since):
        return None
    await _note_quiet(room, key, meta, content, who, int(quiet.total_seconds() // 3600))
    return "quiet"
