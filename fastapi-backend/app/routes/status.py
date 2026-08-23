# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Status API — what the tools a room points at say about the work.

GET /rooms/{room}/status — every external reference the room's own text mentions,
resolved to a state, with the row ids that mention it.

**Reading never fetches.** This is the whole point of the cache underneath: a
board opening does not become a burst of calls to GitHub. A read answers from
what is already cached, says how fresh each answer is, and kicks a refresh in the
background for whatever is due. The next read sees it. ``?refresh=true`` is the
blocking path for a caller with nowhere to come back to, a one-shot CLI or an
agent mid-turn.

**Freshness travels with the value.** Every answer carries ``freshness`` and its
age, because an agent reasoning on a three-hour-old "CI green" is the failure
this surface exists to prevent. ``?max_age=`` is the strict version: anything
older is reported ``missing`` rather than handed over, so a caller can demand
recency instead of hoping for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.filesystem import room_exists
from app.services.status import discovery, registry
from app.services.status.types import ROW_FIELD, CachedStatus, Ref

if TYPE_CHECKING:
    from app.services.status.runtime import StatusRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/status", tags=["status"])

#: Background refreshes in flight. asyncio holds only a weak reference to a task,
#: so one that nothing keeps can be garbage collected mid-flight; this is the
#: strong reference that keeps a kicked refresh alive to completion.
_refreshes: set[asyncio.Task] = set()


class UpstreamRead(BaseModel):
    """One external reference and the last thing its provider said about it."""

    ref: str = Field(description="Stable ref key, 'provider:kind:id'")
    provider: str
    kind: str
    id: str
    url: str | None = None

    freshness: str = Field(description="fresh | stale | missing | error")
    state: str | None = Field(
        default=None, description="ok | pending | blocked | failed | done | unknown"
    )
    label: str | None = Field(default=None, description="The provider's own wording, shown as-is")
    source_updated_at: datetime | None = Field(
        default=None, description="When the source last changed, not when we fetched it"
    )
    fetched_at: datetime | None = None
    age_seconds: float | None = None
    error: str | None = None

    origins: list[str] = Field(
        default_factory=list,
        description="Board row ids whose text mentions this ref (plan:<id>, memory:<key>)",
    )


class RoomStatusResponse(BaseModel):
    room: str
    field: str = Field(
        description=(
            "The board-row field an answer belongs under. Served rather than "
            "assumed so a surface does not carry its own copy of the name."
        )
    )
    providers: list[str] = Field(description="Providers registered on this hub")
    refs: list[UpstreamRead]
    rows: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Row id to the ref keys it mentions. A row may mention several.",
    )
    refreshing: bool = Field(
        default=False, description="A background refresh was kicked for stale or unknown refs"
    )


def _read(ref: Ref, cached: CachedStatus, origins: tuple[str, ...], now: datetime) -> UpstreamRead:
    age = cached.age(now)
    upstream = cached.upstream
    return UpstreamRead(
        ref=str(ref),
        provider=ref.provider,
        kind=ref.kind,
        id=ref.id,
        # The provider's own link wins: it resolved the thing and we only parsed
        # a mention of it.
        url=(upstream.url if upstream and upstream.url else ref.url),
        freshness=cached.freshness,
        state=upstream.state if upstream else None,
        label=upstream.label if upstream else None,
        source_updated_at=upstream.source_updated_at if upstream else None,
        fetched_at=cached.fetched_at,
        age_seconds=age.total_seconds() if age is not None else None,
        error=cached.error,
        origins=list(origins),
    )


def _schedule_background_refresh(runtime: StatusRuntime, refs: list[Ref], now: datetime) -> bool:
    """Refresh whatever is due, in the background. Returns whether anything was."""
    due = runtime.due(refs, now)
    if not due:
        return False

    async def run() -> None:
        # A refresh nobody is waiting on must not surface as an unhandled task
        # exception: the next read reports the failure through the cache, which
        # is where a caller is looking anyway.
        with contextlib.suppress(Exception):
            await runtime.refresh(due, datetime.now(UTC))

    task = asyncio.create_task(run())
    _refreshes.add(task)
    task.add_done_callback(_refreshes.discard)
    return True


@router.get("", response_model=RoomStatusResponse)
async def get_room_status(
    room_name: str,
    refresh: bool = Query(
        default=False,
        description="Fetch before answering. The blocking path, for a one-shot caller.",
    ),
    max_age: int | None = Query(
        default=None,
        ge=0,
        description="Seconds. An answer older than this is reported missing, not handed over.",
    ),
) -> RoomStatusResponse:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    runtime = registry.get_runtime()
    # Discovery reads the room's plan and up to a few hundred memory files. That
    # is real disk work, so it goes off the event loop rather than stalling every
    # other request while one board opens.
    found = await asyncio.to_thread(discovery.discover, room_name, runtime)
    refs = [d.ref for d in found]
    origins = {d.ref: d.origins for d in found}
    now = datetime.now(UTC)
    window = timedelta(seconds=max_age) if max_age is not None else None

    refreshing = False
    if refresh and refs:
        await runtime.refresh(refs, now)
        now = datetime.now(UTC)
    elif refs:
        refreshing = _schedule_background_refresh(runtime, refs, now)

    cached = runtime.read(refs, now, max_age=window)
    return RoomStatusResponse(
        room=room_name,
        field=ROW_FIELD,
        providers=sorted(registry.registered()),
        refs=[_read(ref, cached[ref], origins[ref], now) for ref in refs],
        rows=_rows(found),
        refreshing=refreshing,
    )


def _rows(found: list[discovery.DiscoveredRefs]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for item in found:
        for origin in item.origins:
            rows.setdefault(origin, []).append(str(item.ref))
    return rows
