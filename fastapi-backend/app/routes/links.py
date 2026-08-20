# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory link API — the graph over a room's markdown.

GET /rooms/{room}/links?key=…      — one memory's outbound edges + backlinks
GET /rooms/{room}/links/graph      — the room's whole link graph (nodes + edges)
GET /rooms/{room}/links/integrity  — broken links + orphans/roots/leaves
GET /rooms/{room}/links/expand?key=… — a body with its ![[…]] markers expanded

Separate ``/links`` router: ``/memory`` ends in a ``{key:path}`` catch-all,
so suffix routes there would risk ordering bugs.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import links
from app.services.filesystem import room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/links", tags=["links"])


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("")
async def get_links(
    room_name: str,
    key: str = Query(..., description="Memory key to resolve links for"),
):
    """Both directions for one memory: what it points at, and what points at it."""
    _require_room(room_name)
    return {
        "key": key,
        "outbound": [link.to_dict() for link in links.outbound(room_name, key)],
        "backlinks": [link.to_dict() for link in links.backlinks(room_name, key)],
    }


@router.get("/graph")
async def get_graph(room_name: str):
    """The room's link graph — one node per memory, one edge per link."""
    _require_room(room_name)
    return links.graph(room_name)


@router.get("/integrity")
async def get_integrity(room_name: str):
    """Broken links, orphans, roots, and leaves across the room."""
    _require_room(room_name)
    return links.integrity(room_name)


@router.get("/expand")
async def get_expanded(
    room_name: str,
    key: str = Query(..., description="Memory key to render"),
):
    """A memory's body with transclusions expanded.

    Markers that can't be expanded are left verbatim and reported in
    ``expansions``, so a failed embed never reads as an empty definition.
    """
    _require_room(room_name)
    result = links.expand(room_name, key)
    if not result["found"]:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result
