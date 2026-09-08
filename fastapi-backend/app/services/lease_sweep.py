# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The detector behind the ``expired`` timeline notice.

A lease drains by the clock: :func:`assignments.state_of` reads ``expired`` off
``claimed_at`` and ``ttl_minutes`` with nothing on disk having changed, which is
the property that lets an abandoned claim return to the pool with nobody alive
to say so. It also means there is no write to hang a notice off. ``claimed``,
``released`` and ``resolved`` each raise theirs from the seam that wrote them;
expiry has no seam, so this loop watches for the crossing instead.

Two properties keep it honest.

**Raise once per lease.** A lease is identified by ``(room, key, claimed_at)``:
the same row re-claimed is a new lease and may expire again, a row released or
resolved leaves the set, and a lease already announced is never announced twice
however many sweeps see it still expired.

**Announce crossings, not history.** The set lives in the process, so on the
first sweep after a start every lease already expired is recorded silently and
not raised: the timeline dates a notice at the moment it was raised, and a
lease that drained while the hub was down cannot honestly be dated now. The
board still reads that row as ``expired`` (that is derived, and needs no
notice); what is lost is only the timeline line for a crossing nobody observed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.services import assignments
from app.services.filesystem import get_room_dir, list_memory_files, list_room_names

logger = logging.getLogger(__name__)

#: A lease's shortest useful TTL is minutes; a minute between looks dates an
#: ``expired`` line closely enough without rereading every board every second.
SWEEP_INTERVAL_SECONDS = 60

_sweep_task: asyncio.Task[None] | None = None

#: Leases whose expiry has been seen, as ``(room, key, claimed_at)``.
_announced: set[tuple[str, str, str]] = set()
_primed = False


def reset() -> None:
    """Forget every observed lease; the next sweep primes again. For tests."""
    global _primed
    _announced.clear()
    _primed = False


def _expired_leases(now: datetime) -> list[tuple[str, str, dict]]:
    """Every held lease the clock says has drained, with its frontmatter."""
    found: list[tuple[str, str, dict]] = []
    for room in list_room_names():
        room_dir = get_room_dir(room)
        for namespace in assignments.ASSIGNABLE_NAMESPACES:
            for key, meta, _content in list_memory_files(room_dir, prefix=f"{namespace}/"):
                if meta.get(assignments.FIELD) != "held":
                    continue
                if assignments.state_of(meta, now) == "expired":
                    found.append((room, key, meta))
    return found


def _ident(room: str, key: str, meta: dict) -> tuple[str, str, str]:
    return (room, key, str(meta.get("claimed_at") or ""))


async def sweep_expired_leases(now: datetime | None = None) -> list[tuple[str, str]]:
    """Raise ``expired`` for each lease that drained since the last look.

    Returns the ``(room, key)`` pairs raised. The first call after a start
    records what is already expired and raises nothing (see the module note).
    """
    global _primed
    now = now or datetime.now(UTC)
    expired = _expired_leases(now)
    current = {_ident(room, key, meta) for room, key, meta in expired}
    # A lease that is no longer held-and-expired — re-claimed, released,
    # resolved, or its row gone — is forgotten, so the set tracks the board.
    _announced.intersection_update(current)

    if not _primed:
        _announced.update(current)
        _primed = True
        return []

    raised: list[tuple[str, str]] = []
    for room, key, meta in expired:
        ident = _ident(room, key, meta)
        if ident in _announced:
            continue
        holder = str(meta.get("owner") or "").lstrip("@")
        try:
            await assignments.raise_notice(
                room, key, "expired", holder or assignments.RUNTIME_AUTHOR
            )
        except Exception:  # one row's notice must not stop the others
            logger.exception("lease sweep: failed to raise expired for %s/%s", room, key)
            continue
        _announced.add(ident)
        raised.append((room, key))
    if raised:
        logger.info("lease sweep raised expired for %d lease(s)", len(raised))
    return raised


async def _sweep_loop() -> None:
    while True:
        try:
            await sweep_expired_leases()
        except Exception:  # keep the loop alive
            logger.exception("lease sweep iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_lease_sweep() -> None:
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.get_running_loop().create_task(_sweep_loop())


def stop_lease_sweep() -> None:
    global _sweep_task
    if _sweep_task is not None and not _sweep_task.done():
        _sweep_task.cancel()
    _sweep_task = None
