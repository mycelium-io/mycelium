# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The detector behind the ``upstream`` timeline notice.

A board row that links a pull request already shows where it stands ("CI
failing", "approved"), read from the status cache whenever someone opens the
board. What nothing said was that it *moved*: CI going red while everyone was
in another thread, a review asked for, a merge. The hub is on localhost, so
GitHub cannot call it; this loop looks instead. Once a minute it discovers the
refs every room's rows and threads mention, refreshes the ones that are due
(the cache's own ``ttl`` decides, so a settled pull request is asked about once
a day), and compares each answer with the last one the room saw. A provider
that can say what happened between two answers (``changes``) turns the
difference into words from ``message_format.UPSTREAM_CHANGES``, and each is
raised as an ``upstream`` notice on the row.

Three properties keep it honest.

**It informs and wakes nobody.** A notice is excluded from
``participate._addressed_to``, and every notice consumer acts on its own
subkinds only (``filed``, ``resolved``), so a review requested or a merge never
rings anyone's doorbell. An agent reads it in the digest of a wake something
else caused.

**The first answer is a baseline, not news.** A ref seen for the first time is
recorded silently: a pull request linked today did not change today.

**What the room last saw is kept on disk.** The cache lives in the process and
starts empty after a restart, so comparing with it would either announce
nothing (a merge while the hub was down) or everything. The room's last
answer per ref is kept in ``.upstream-seen.json`` in its folder, and a change
found after a restart is still raised, carrying ``at``: when the source says
it changed, not when we noticed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services import assignments
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_room_names,
    read_memory_file,
    system_meta,
)
from app.services.status import discovery, registry

if TYPE_CHECKING:
    from app.services.status.runtime import StatusRuntime
    from app.services.status.types import CachedStatus, Ref, UpstreamChange

logger = logging.getLogger(__name__)

#: The GitHub provider's answers stay fresh for a minute; looking more often
#: would find nothing new.
SWEEP_INTERVAL_SECONDS = 60

#: Where a room keeps the last answer it saw for each ref it links.
SEEN_FILE = ".upstream-seen.json"

_sweep_task: asyncio.Task[None] | None = None


def _seen_path(room: str):
    return get_room_dir(room) / SEEN_FILE


def load_seen(room: str) -> dict[str, dict[str, Any]]:
    """The room's last answer per ref, keyed by the ref's string form."""
    try:
        raw = json.loads(_seen_path(room).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_seen(room: str, seen: dict[str, dict[str, Any]]) -> None:
    path = _seen_path(room)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _reading(cached: CachedStatus) -> dict[str, Any] | None:
    """What is kept of an answer: enough to tell what changed next time."""
    upstream = cached.upstream
    if upstream is None or cached.freshness not in ("fresh", "stale"):
        return None
    return {"state": upstream.state, "label": upstream.label, "detail": dict(upstream.detail)}


def _row_for(room: str, origins: tuple[str, ...], now: datetime) -> tuple[str, dict, str] | None:
    """The row a change is told on: the first that mentions the ref and is still
    open, else the first that mentions it. One notice per change, however many
    rows link the pull request, so the timeline says it once."""
    room_dir = get_room_dir(room)
    rows: list[tuple[str, dict, str]] = []
    for origin in origins:
        if not origin.startswith("memory:"):
            continue
        key = origin.removeprefix("memory:")
        found = read_memory_file(room_dir, key)
        if found is not None:
            rows.append((key, found[0], found[1]))
    open_rows = [row for row in rows if not assignments.settled(row[1], now)]
    return (open_rows or rows or [None])[0]


async def _raise(
    room: str, row: tuple[str, dict, str], ref: Ref, cached: CachedStatus, change: UpstreamChange
) -> None:
    from app.services.room_channels import manager

    key, meta, content = row
    upstream = cached.upstream
    first = next((ln.strip() for ln in (content or "").splitlines() if ln.strip()), key)
    at = upstream.source_updated_at if upstream else None
    await manager.raise_notice(
        room,
        subkind="upstream",
        key=key,
        title=first.lstrip("# ").strip(),
        episode=system_meta(meta).get(EPISODE_META),
        change=change.change,
        ref=ref.id,
        url=(upstream.url if upstream and upstream.url else ref.url),
        label=upstream.label if upstream else None,
        who=",".join(change.who) or None,
        at=at.isoformat() if at else None,
    )


async def sweep(
    now: datetime | None = None, runtime: StatusRuntime | None = None
) -> list[tuple[str, str, str]]:
    """Raise an ``upstream`` notice for each linked ref that changed since the
    room last looked. Returns ``(room, key, change)`` for each one raised."""
    runtime = runtime or registry.get_runtime()
    clock = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    found: dict[str, list[discovery.DiscoveredRefs]] = {}
    for room in list_room_names():
        try:
            found[room] = await asyncio.to_thread(discovery.discover, room, runtime)
        except Exception:  # one unreadable room must not stop the others
            logger.exception("upstream watch: discovery failed in %s", room)
    refs = list(dict.fromkeys(item.ref for items in found.values() for item in items))
    # One refresh across every room, so a pull request two rooms link is one fetch.
    if refs:
        await runtime.refresh(refs, clock())
    now = clock()

    raised: list[tuple[str, str, str]] = []
    for room, items in found.items():
        seen = load_seen(room)
        before_keys = set(seen)
        dirty = False
        cached = runtime.read([item.ref for item in items], now)
        for item in items:
            name = str(item.ref)
            reading = _reading(cached[item.ref])
            if reading is None or seen.get(name) == reading:
                continue
            before = seen.get(name)
            seen[name] = reading
            dirty = True
            provider = runtime.provider(item.ref.provider)
            telling = getattr(provider, "changes", None)
            if before is None or telling is None:
                continue
            changes = telling(before.get("detail") or {}, reading["detail"])
            row = _row_for(room, item.origins, now) if changes else None
            if row is None:
                continue
            for change in changes:
                try:
                    await _raise(room, row, item.ref, cached[item.ref], change)
                except Exception:  # one notice must not stop the others
                    logger.exception("upstream watch: failed to raise on %s/%s", room, row[0])
                    continue
                raised.append((room, row[0], change.change))
        # A ref no row mentions any more is forgotten, so linking it again
        # later starts from a fresh baseline rather than a stale one.
        linked = {str(item.ref) for item in items}
        for name in before_keys - linked:
            seen.pop(name, None)
            dirty = True
        if dirty and (seen or before_keys):
            await asyncio.to_thread(_save_seen, room, seen)
    if raised:
        logger.info("upstream watch raised %d change(s)", len(raised))
    return raised


async def _sweep_loop() -> None:
    while True:
        try:
            await sweep()
        except Exception:  # keep the loop alive
            logger.exception("upstream watch iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_watch() -> None:
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.get_running_loop().create_task(_sweep_loop())


def stop_watch() -> None:
    global _sweep_task
    if _sweep_task is not None and not _sweep_task.done():
        _sweep_task.cancel()
    _sweep_task = None
