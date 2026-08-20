# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9 episode read API — backs the protocol inspector.

The projection from a ``log/episodes/{short_id}.md`` record to structured fields
lives in :mod:`app.services.episode_records`; these endpoints only serve it.

GET /rooms/{room}/episodes            — summaries, newest first
GET /rooms/{room}/episodes/{short_id} — one episode + its envelope chain
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import EpisodeDetailRead, EpisodeListResponse
from app.services import pagination
from app.services.episode_records import (
    EPISODES_PREFIX,
    episode_summary,
    parse_envelopes,
    room_episodes,
)
from app.services.filesystem import get_room_dir, read_memory_file, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/episodes", tags=["episodes"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _episode_sort_key(episode: dict[str, Any]) -> tuple[str, str, str]:
    """An episode's keyset sort key: pinned-live first, then newest, then id.

    The leading rank is how "an in-progress episode sorts first" survives
    pagination — it is part of the order rather than a post-sort insert, so a
    cursor into page two still agrees with page one about where the live one sits.
    """
    live = "1" if episode.get("outcome") == "open" else "0"
    return (live, str(episode.get("updated_at") or ""), str(episode.get("short_id") or ""))


@router.get("", response_model=EpisodeListResponse)
async def list_episodes(
    room_name: str,
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(
        None, description="Opaque cursor from a previous page's next_cursor"
    ),
):
    """List episode summaries for a room, newest first (an in-progress one first)."""
    _require_room(room_name)
    try:
        page = pagination.paginate(
            room_episodes(room_name, limit=None),
            key=_episode_sort_key,
            limit=limit,
            cursor=cursor,
        )
    except pagination.InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "episodes": page.items,
        "total": page.total,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@router.get("/{short_id}", response_model=EpisodeDetailRead)
async def get_episode(room_name: str, short_id: str):
    """Return one episode: its summary plus the full L9 envelope chain."""
    _require_room(room_name)
    result = read_memory_file(get_room_dir(room_name), f"{EPISODES_PREFIX}{short_id}")
    if result is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    meta, content = result
    summary = episode_summary(f"{EPISODES_PREFIX}{short_id}", meta, content)
    summary["messages"] = parse_envelopes(content)
    return summary
