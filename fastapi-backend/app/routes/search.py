# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
GET /search — one ranked query across memories, episodes, messages, rooms, agents.

A single cross-entity endpoint rather than a client-side merge of five: ranking
heterogeneous results only works where every candidate is in hand, and the
scoping grammar (``#room``, ``@agent``, ``memory:``, ``kind:``) has one
implementation this way instead of one per caller. See
:mod:`app.services.search` for the ranking and :mod:`app.services.search_query`
for the grammar.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.schemas import SearchHitRead, SearchResponse, SearchScopeRead
from app.services import search, search_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_everything(
    q: str = Query("", description="Query text with optional #room / @agent / type: tokens"),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    """Search every entity type in scope and return them on one ranked list.

    An empty query is a valid request with no results — a typeahead calls this
    on the first keystroke and shouldn't have to special-case a 422.
    """
    parsed = search_query.parse(q)
    result = await search.search(parsed, limit=limit)
    return SearchResponse(
        query=q,
        scope=SearchScopeRead(
            text=parsed.text,
            rooms=list(parsed.rooms),
            actors=list(parsed.actors),
            types=list(parsed.types),  # ty: ignore[invalid-argument-type]
            kinds=list(parsed.kinds),
        ),
        results=[SearchHitRead(**hit.__dict__) for hit in result.hits],
        counts=result.counts,
    )
