# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ends a hold with no timer, and what says a held row has gone quiet (#1136).

A row given to someone, or claimed without a lease, is held until something
real ends it. A 30-minute lease that only ``await --loop`` renewed expired rows
every day while their agents were still on them, so the clock is no longer
what ends a hold. These are, each checked once a minute and each said on the
room's timeline:

- **The holder's herdr pane closed.** A connected runner's machine report
  (``RunnerHello.machine``) lists every herdr agent on its machine; one whose
  every pane reads ``gone`` has stopped, and its rows are released.
- **The holder left the room.** No ``agents/<handle>`` and no person by that
  name: released.
- **No sign of the holder at all, for a long time.** A holder the hub has no
  signal for (no pane on any runner, no herdr presence, no ``await``) keeps
  the row for :data:`FALLBACK_HOURS` of no activity on it, then it expires
  with a notice. A holder the hub can see is never expired for being slow.

A row whose holder is around but which has had no activity (nothing in its
thread, no edit, no notice, such as a pull request changing) for
:data:`FLAG_HOURS` is **flagged**, never released: one line in its thread,
naming whoever filed it, once per hold.
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

#: Hours of no activity on a row before its holder's hold is flagged.
FLAG_HOURS = 3
#: Hours of no activity, with no sign of the holder anywhere, before it expires.
FALLBACK_HOURS = 8
#: The frontmatter that remembers a hold was flagged, so it's flagged once.
FLAGGED_FIELD = "hold_flagged_at"


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
    """What the hub can see of ``handle``: ``person``, ``engine``, ``gone``
    (not in the room any more), ``closed`` (every herdr pane it had is closed),
    ``present`` or ``unseen``."""
    from app.services.principals import classify_sender
    from app.services.room_channels import manager

    kind = classify_sender(room, handle)
    if kind == "user":
        return "person"
    if kind == "engine":
        return "engine"
    if kind == "unknown":
        return "gone"
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
        if payload.get("type") == message_format.NOTICE_PAYLOAD_TYPE and (
            (payload.get("data") or {}).get("key") == key
        ):
            stamps.append(parse_recorded_at(record.recorded_at))
            break
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


async def _flag(room: str, key: str, meta: dict, content: str, who: str, hours: int) -> None:
    """One line in the row's thread, naming whoever filed it, once per hold."""
    from app.services.fields import upsert_patch
    from app.services.room_channels import manager

    episode = system_meta(meta).get(EPISODE_META)
    managed = manager.get(room)
    filer = str(meta.get("created_by") or "").lstrip("@")
    ask = f"@{filer} " if filer and filer not in (who, assignments.RUNTIME_AUTHOR) else ""
    text = (
        f"{ask}@~{who} has held this for {hours}h with no activity: nothing in this thread, "
        "no edits and no pull request changes. Is it still going?"
    )
    if managed is not None and episode:
        from app.services.message_models import Kind

        envelope = message_format.build_envelope(
            kind=Kind.exchange,
            episode=episode,
            sender=message_format.SYSTEM_ACTOR_ID,
            sender_role=message_format.SYSTEM_ACTOR_ROLE,
            topic=message_format.topic_urn(room),
            payload_type="message",
        )
        await managed.post(envelope, text, list_write=True)
        manager.enqueue_herdr_wakes_for_mentions(
            room, text, sender=message_format.SYSTEM_ACTOR_ID, episode=episode
        )
    await upsert_patch(
        room,
        key,
        meta,
        content,
        {FLAGGED_FIELD: datetime.now(UTC).isoformat()},
        assignments.RUNTIME_AUTHOR,
        notify=False,
    )


async def _end(room: str, key: str, why: str, subkind: str, by: str, now: datetime) -> None:
    """End a hold: the row goes back to the pool with a runtime note saying why."""
    await assignments.end_hold(room, key, why, subkind=subkind, by=by, now=now)


async def sweep(now: datetime | None = None) -> list[tuple[str, str, str]]:
    """End or flag every hold the evidence says to. Returns ``(room, key, what)``."""
    now = now or datetime.now(UTC)
    done: list[tuple[str, str, str]] = []
    for room in list_room_names():
        room_dir = get_room_dir(room)
        for namespace in assignments.ASSIGNABLE_NAMESPACES:
            for key, meta, content in list_memory_files(room_dir, prefix=f"{namespace}/"):
                if assignments.state_of(meta, now) != "held" or not assignments.open_ended(meta):
                    continue
                who = assignments.holder(meta, now)
                if not who:
                    continue
                try:
                    what = await _one(room, key, meta, content, who, now)
                except Exception:  # one row must not stop the others
                    logger.exception("hold sweep failed on %s/%s", room, key)
                    continue
                if what:
                    done.append((room, key, what))
    return done


async def _one(
    room: str, key: str, meta: dict, content: str, who: str, now: datetime
) -> str | None:
    seen = signal_of(room, who)
    runtime = assignments.RUNTIME_AUTHOR
    if seen == "gone":
        await _end(room, key, f"@{who} isn't in the room any more", "released", runtime, now)
        return "released"
    if seen == "closed":
        await _end(room, key, f"@{who}'s herdr pane closed", "released", runtime, now)
        return "released"
    last = last_activity(room, key, meta) or now
    quiet = now - last
    if seen == "unseen" and quiet >= timedelta(hours=FALLBACK_HOURS):
        why = f"expired: no sign of @{who} and nothing on this row for {FALLBACK_HOURS}h"
        await _end(room, key, why, "expired", who, now)
        return "expired"
    flagged = _stamp(meta.get(FLAGGED_FIELD))
    since = _stamp(meta.get("claimed_at")) or _stamp(meta.get("created_at"))
    already = flagged is not None and (since is None or flagged >= since)
    if quiet >= timedelta(hours=FLAG_HOURS) and not already and seen != "person":
        await _flag(room, key, meta, content, who, int(quiet.total_seconds() // 3600))
        return "flagged"
    return None
