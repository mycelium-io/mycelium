# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Coordination observability endpoints.

Read-only endpoints that expose in-memory coordination state for diagnostics
and the Phase 2 test matrix described in issue #162.

GET    /api/internal/coordination/round-traces
DELETE /api/internal/coordination/round-traces

These endpoints return data from the in-memory ring buffer in
``app.services.coordination``; the buffer is reset on backend restart.
They are deliberately namespaced under ``/api/internal/`` to signal that
they are operator/diagnostic endpoints, not public agent-facing API.
"""

import logging

from fastapi import APIRouter, Query

from app.services import coordination as coordination_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/coordination", tags=["coordination"])


@router.get("/round-traces")
async def list_round_traces(
    limit: int | None = Query(
        None,
        ge=0,
        le=coordination_service._ROUND_TRACE_BUFFER_SIZE,
        description=(
            "Return at most the most-recent N traces.  Omit to return all "
            "traces currently in the buffer (capped at "
            f"{coordination_service._ROUND_TRACE_BUFFER_SIZE})."
        ),
    ),
) -> dict:
    """Return completed CFN round traces, oldest first.

    Each trace is one round of a CFN negotiation: who replied, when, whether
    any replies were synthesised because the watchdog fired, and how the
    round closed.  Used by the Phase 2 test matrix in issue #162 to produce
    real distributions of agent latency and synthesis rates.
    """
    traces = coordination_service.get_round_traces(limit=limit)
    return {
        "count": len(traces),
        "buffer_capacity": coordination_service._ROUND_TRACE_BUFFER_SIZE,
        "traces": traces,
    }


@router.delete("/round-traces", status_code=204)
async def clear_round_traces() -> None:
    """Empty the round trace ring buffer.

    Used by the Phase 2 test matrix to reset between cells so each cell's
    output is independent.  No-op if the buffer is already empty.
    """
    coordination_service.clear_round_traces()
