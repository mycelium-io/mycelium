# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Assignments: taking work, holding it, and letting it drain.

An agent is resident rather than one-shot, but no session gets to announce that
it ended — a container is reclaimed, a cloud session times out, a job is
cancelled.  So an assignment is a lease, not a fact: it has a window, the holder
keeps it alive by saying so, and it returns to the pool when nobody does.

The word is *assignment*, on both sides of the seam and in the frontmatter.
Not *custody* — that names the hub holding a member's MLS keys
(:mod:`app.services.custody`), which shares no concept with this.  The window
below is a lease, but the room's other lease — the presence lease that holds
membership between ``await`` calls — is a different thing again.

**A lease is frontmatter on a ``work/`` memory.**  Nothing new is stored.
``owner`` / ``claimed_at`` / ``ttl_minutes`` go through the same upsert every
memory write goes through, so a claim is versioned, indexed and link-parsed like
any other change to the room, and a hub operator can read one in a text editor.

Plan tasks are deliberately excluded: ``- [ ] text @handle`` has nowhere to put a
stamp, and a compiled plan task is the room's commitment rather than an
in-flight task — a commitment that decays is not one.

**Expiry is derived, never written.**  Recording that a lease ran out would need
a process to be alive at the moment it drained, which is exactly what stopped
being true.  :func:`state_of` reads it off the clock instead, so an abandoned
claim returns to the pool with nobody touching it.

**A renewal is a heartbeat, not news.**  It re-dates the same lease and
broadcasts nothing, and only fires once a lease is past half its window — a
resident loop polling every few seconds must not rewrite the room's files every
few seconds.

The constants below are frozen in ``contracts/board-vocabulary.json`` under
``assignment``; the CLI and the GUI carry their own copies, and a test on each side
asserts against that file so no copy can drift alone.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_memory_files,
    read_memory_file,
    system_meta,
)

FIELD = "assignment"

STATES = ("unclaimed", "held", "released", "expired", "resolved")
STORED_STATES = ("held", "released", "resolved")
DERIVED_STATES = ("unclaimed", "expired")

#: Fraction of a lease that may be spent before a renewal is due.
STALE_AFTER = 0.5
DEFAULT_TTL_MINUTES = 30

RUNTIME_AUTHOR = "runtime"
ASSIGNABLE_NAMESPACES = ("work",)

#: How often a lease watch re-reads the row it is watching.
POLL_INTERVAL_S = 1.0
#: Longest a lease watch holds a request open when the caller names no timeout.
MAX_WAIT_S = 60


class AssignmentError(Exception):
    """A lease operation the room refuses, with the reason a reader needs."""

    def __init__(self, reason: str, *, status: int = 400, **detail: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.detail = detail


def _parse(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def spent(meta: dict, now: datetime) -> float | None:
    """Fraction of the lease already burned, or ``None`` when it has no window."""
    stamp = _parse(meta.get("claimed_at") or meta.get("updated_at"))
    raw_ttl = meta.get("ttl_minutes")
    if not isinstance(raw_ttl, int | float | str):
        return None
    try:
        ttl = float(raw_ttl)
    except (TypeError, ValueError):
        return None
    if stamp is None or ttl <= 0:
        return None
    return max(0.0, (now - stamp).total_seconds() / 60.0 / ttl)


def freshness(meta: dict, now: datetime) -> str | None:
    """fresh / stale / expired, the shape the board's upstream half already reads."""
    fraction = spent(meta, now)
    if fraction is None:
        return None
    if fraction < STALE_AFTER:
        return "fresh"
    return "stale" if fraction < 1.0 else "expired"


def state_of(meta: dict, now: datetime) -> str:
    """A row's assignment state, read off its frontmatter and the clock.

    A ``held`` lease that nobody renewed reads ``expired`` here with nothing on
    disk having changed, and one that cannot be dated at all reads the same way:
    a claim that cannot be shown to be alive is not evidence that it is.
    """
    stored = meta.get(FIELD)
    if stored not in STATES:
        return "unclaimed"
    if stored != "held":
        return str(stored)
    if not meta.get("owner"):
        return "unclaimed"
    return "held" if freshness(meta, now) in ("fresh", "stale") else "expired"


def assignable(key: str) -> bool:
    return key.split("/")[0] in ASSIGNABLE_NAMESPACES


def _load(room: str, key: str) -> tuple[dict, str]:
    if not assignable(key):
        raise AssignmentError(
            f"leases live on {'/, '.join(ASSIGNABLE_NAMESPACES)}/ memories; '{key}' is elsewhere",
            status=422,
            key=key,
        )
    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        raise AssignmentError(f"no memory '{key}' in this room", status=404, key=key)
    return found


def _describe(key: str, meta: dict, now: datetime) -> dict:
    """The row's assignment, as the wire says it."""
    state = state_of(meta, now)
    owner = meta.get("owner")
    body = {
        "key": key,
        "assignment": state,
        "owner": str(owner).lstrip("@") if owner else None,
        "claimed_at": meta.get("claimed_at"),
        "ttl_minutes": meta.get("ttl_minutes"),
        "freshness": freshness(meta, now),
        "version": meta.get("version"),
        "assignment_note": meta.get("assignment_note"),
        "assignment_note_by": meta.get("assignment_note_by"),
    }
    if state == "expired":
        # Nobody wrote this note, because nobody was there to. It is derived from
        # the same silence that expired the lease, and signed as such — which is
        # what tells an abandoned row from a deliberately handed-back one.
        body["assignment_note"] = f"expired — @{body['owner'] or 'its holder'} stopped renewing"
        body["assignment_note_by"] = RUNTIME_AUTHOR
    return body


async def _write(
    room: str, key: str, meta: dict, content: str, patch: dict, handle: str, *, notify: bool = True
) -> dict:
    """Put a assignment change on the row, through the canonical memory upsert.

    The upsert itself is :func:`app.services.fields.upsert_patch`, shared with
    the board's field writes so a lease and a status change cannot drift in how
    they reach the store.
    """
    from app.services.fields import upsert_patch

    fresh_meta = await upsert_patch(room, key, meta, content, patch, handle, notify=notify)
    return _describe(key, fresh_meta, datetime.now(UTC))


async def _raise_notice(room: str, key: str, subkind: str, by: str) -> None:
    """Tell the room the board moved: a task was claimed, handed back or resolved.

    A custody write is news the timeline should carry, so it raises a notice the
    same way a thread write raises a ping — through the manager, waking nobody. Reads
    fresh state so the episode URN is present even when the write just minted it.
    """
    from app.services.room_channels import manager

    meta, content = _load(room, key)
    episode = system_meta(meta).get(EPISODE_META)
    first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
    await manager.raise_notice(
        room,
        subkind=subkind,
        key=key,
        title=first.lstrip("# ").strip(),
        episode=episode,
        by=by.lstrip("@"),
    )


async def claim(room: str, key: str, handle: str, ttl_minutes: int, now: datetime) -> dict:
    """Take assignment of a row, for as long as the lease runs.

    A live claim is not stealable — that is the point of holding one — but an
    expired one is: the row is back in the pool, and refusing the next taker
    because a dead session's handle is still in the file would be the original
    failure with extra steps.
    """
    meta, content = _load(room, key)
    current = state_of(meta, now)
    holder = str(meta.get("owner") or "").lstrip("@")
    if current == "held" and holder and holder != handle.lstrip("@"):
        raise AssignmentError(
            f"'{key}' is held by @{holder}",
            status=409,
            key=key,
            owner=holder,
            claimed_at=meta.get("claimed_at"),
            ttl_minutes=meta.get("ttl_minutes"),
        )
    patch = {
        FIELD: "held",
        "owner": f"@{handle.lstrip('@')}",
        "claimed_at": now.isoformat(),
        "ttl_minutes": ttl_minutes,
        # A new holder inherits the row, not the last holder's parting words.
        "assignment_note": None,
        "assignment_note_by": None,
    }
    described = await _write(room, key, meta, content, patch, handle)
    await _raise_notice(room, key, "claimed", handle)
    return described


async def release(room: str, key: str, handle: str, note: str | None, now: datetime) -> dict:
    """Hand a row back deliberately, and sign the note that says you did.

    Handing off and dying mid-task converge on the same state: an unclaimed row
    with history.  The note's author is what tells them apart, so a release
    always leaves one even when the releaser had nothing to add.
    """
    meta, content = _load(room, key)
    patch = {
        FIELD: "released",
        "owner": None,
        "claimed_at": None,
        "ttl_minutes": None,
        "assignment_note": note or "released",
        "assignment_note_by": handle.lstrip("@"),
    }
    described = await _write(room, key, meta, content, patch, handle)
    await _raise_notice(room, key, "released", handle)
    return described


async def resolve(room: str, key: str, handle: str, now: datetime) -> dict:
    """Mark the work done. A resolved row leaves the board rather than draining."""
    meta, content = _load(room, key)
    patch = {
        FIELD: "resolved",
        "claimed_at": None,
        "ttl_minutes": None,
        "assignment_note": f"resolved by @{handle.lstrip('@')}",
        "assignment_note_by": handle.lstrip("@"),
    }
    described = await _write(room, key, meta, content, patch, handle)
    await _raise_notice(room, key, "resolved", handle)
    return described


async def renew(room: str, handle: str, now: datetime) -> list[dict]:
    """Re-date every lease this handle holds that is due for it.

    This is what a resident loop calls between turns, so it has to be quiet in
    both senses: it writes nothing for a lease still in its first half, and the
    writes it does make don't broadcast — a heartbeat is not news, and a room
    whose transcript filled with "still here" would be worse than one that
    forgot.
    """
    who = handle.lstrip("@")
    renewed: list[dict] = []
    room_dir = get_room_dir(room)
    for namespace in ASSIGNABLE_NAMESPACES:
        for key, meta, content in list_memory_files(room_dir, prefix=f"{namespace}/"):
            if state_of(meta, now) != "held":
                continue
            if str(meta.get("owner") or "").lstrip("@") != who:
                continue
            if (freshness(meta, now) or "fresh") == "fresh":
                continue
            renewed.append(
                await _write(
                    room, key, meta, content, {"claimed_at": now.isoformat()}, handle, notify=False
                )
            )
    return renewed


def read(room: str, key: str, now: datetime) -> dict:
    """The row's assignment right now, without changing anything."""
    meta, _ = _load(room, key)
    return _describe(key, meta, now)


def signature(body: dict) -> str:
    """What a watcher compares to decide whether anything actually moved.

    Deliberately not the memory's version: a lease that drained changed state
    without anyone writing a byte, and a watcher that keyed on the version would
    sleep through the one transition nobody sends.
    """
    return "|".join(
        str(body.get(part) or "") for part in ("assignment", "owner", "claimed_at", "version")
    )


async def watch(room: str, key: str, since: str | None, timeout: int, now_fn=None) -> dict:
    """Long-poll one lease and return when its assignment moves.

    **The lease is the subscription object.**  Waking on channel traffic to watch
    a handoff is the wrong subscription — a dozen unrelated messages wake you for
    nothing.  A lease is already a small state machine whose transitions are
    exactly the events a handoff cares about, so watching it costs no interest
    table on the side and no message can wake it.

    With no ``since`` the current state comes straight back.  An agent does not
    need a push, it needs the row current the next time it exists, so the first
    call is orientation rather than a wait.
    """
    clock = now_fn or (lambda: datetime.now(UTC))
    body = read(room, key, clock())
    current = signature(body)
    if since is None or since != current:
        return {**body, "since": current, "changed": since is not None}

    loop = asyncio.get_event_loop()
    deadline = loop.time() + (timeout if timeout > 0 else MAX_WAIT_S)
    while loop.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        body = read(room, key, clock())
        moved = signature(body)
        if moved != since:
            return {**body, "since": moved, "changed": True}
    return {**body, "since": current, "changed": False}
