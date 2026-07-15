# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Client for the Go CFN's native L9 endpoint (``POST /api/l9/messages``).

The CFN routes each envelope to a Cognition Engine registered for the MAS by
matching kind/subkind (content-based routing; workspace/MAS are read from
``participants.groups``). Everything here is gated on
``settings.L9_CFN_ENABLED``: it requires a knowledge CE
(ghcr.io/outshift-open/ioc-cfn-cognition-engines) registered with the CFN,
and stays off until the deployment runs one.

Both operations are deliberately fail-soft: a knowledge query miss just means
no team prior in the ticks, and a knowledge write failure is logged and
dropped: consensus must never block on the knowledge fabric.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services import cfn_http, l9
from app.services.l9_models import Kind

logger = logging.getLogger(__name__)

_L9_HTTP_TIMEOUT = httpx.Timeout(60.0)


def enabled() -> bool:
    return bool(settings.L9_CFN_ENABLED and settings.CFN_SVC_URL)


async def post_l9(envelope_dict: dict[str, Any]) -> dict[str, Any] | None:
    """POST an envelope to the CFN; return the CE's L9 response dict or None."""
    url = f"{settings.CFN_SVC_URL}/api/l9/messages"
    try:
        client = cfn_http.get_client()
        resp = await client.post(url, json=envelope_dict, timeout=_L9_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("CFN /api/l9/messages call failed: %s", exc)
        return None


async def knowledge_query_team_prior(
    *,
    parent_room: str,
    short_id: str,
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any] | None:
    """Ask the knowledge fabric for the team's prior on this room's topic.

    Returns a tick-ready ``team_prior`` dict
    (``{"confidence", "provenance_weight", "episode_count", "source"?}``)
    or None when disabled, unreachable, or the CE has nothing usable.
    """
    if not enabled() or not workspace_id or not mas_id:
        return None
    env = l9.build_envelope(
        kind=Kind.knowledge,
        subkind="query",
        episode=l9.episode_urn(parent_room, short_id),
        topic=l9.topic_urn(parent_room),
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload_type="query",
        payload_data={
            "intent": (
                f"Prior negotiation agreements and team confidence on {l9.topic_urn(parent_room)}"
            ),
        },
    )
    response = await post_l9(l9.envelope_to_dict(env))
    if not response:
        return None
    data = (response.get("payload") or {}).get("data") or {}
    prior = data.get("team_prior", data)
    conf = prior.get("confidence") if isinstance(prior, dict) else None
    if not isinstance(conf, int | float) or not 0.0 <= conf <= 1.0:
        return None
    out: dict[str, Any] = {"confidence": float(conf)}
    for key in ("provenance_weight", "episode_count", "source"):
        if prior.get(key) is not None:
            out[key] = prior[key]
    return out


async def knowledge_write_consensus(
    *,
    parent_room: str,
    short_id: str,
    workspace_id: str,
    mas_id: str,
    assignments: dict[str, Any],
    metrics: dict[str, Any] | None,
    plan_file: str | None,
    consensus_l9_id: str | None,
) -> None:
    """Record a converged agreement in the knowledge fabric (fire-and-forget)."""
    if not enabled() or not workspace_id or not mas_id:
        return
    payload: dict[str, Any] = {
        "room": parent_room,
        "assignments": assignments,
        "revision_cause": "converged_episode",
    }
    if metrics:
        payload["metrics"] = metrics
    if plan_file:
        payload["plan_file"] = plan_file
    env = l9.build_envelope(
        kind=Kind.knowledge,
        subkind="feedback",
        episode=l9.episode_urn(parent_room, short_id),
        parents=[consensus_l9_id] if consensus_l9_id else [],
        topic=l9.topic_urn(parent_room),
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload_type="knowledge",
        payload_data=payload,
    )
    await post_l9(l9.envelope_to_dict(env))
