# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Async httpx client for the CFN Python service semantic negotiation API.

Endpoints:
  POST .../workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/start
  POST .../workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/decide
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_API_PREFIX = "/api"

# CFN may run LLM + persist agreement to shared memory; 60s is often too short.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


async def start_negotiation(
    *,
    session_id: str,
    content_text: str,
    agents: list[dict[str, str]],
    workspace_id: str,
    mas_id: str,
    n_steps: int = 20,
) -> dict[str, Any]:
    """Call CFN start endpoint.  Returns the raw response dict.

    ``agents`` items: ``{"id": handle, "name": handle}``

    On network/HTTP error, logs a warning and returns ``{}``.
    """
    url = (
        f"{settings.COGNITION_FABRIC_NODE_URL}{_API_PREFIX}"
        f"/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
        f"/semantic-negotiation/start"
    )
    body = {
        "session_id": session_id,
        "content_text": content_text,
        "agents": agents,
        "n_steps": n_steps,
    }
    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("CFN start_negotiation failed: %s", exc)
        return {}


async def decide_negotiation(
    *,
    session_id: str,
    agent_replies: list[dict[str, Any]],
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any]:
    """Call CFN decide endpoint.  Returns the raw response dict.

    ``agent_replies`` items: ``{"agent_id": handle, "action": "accept"|"reject"|"counter_offer", "offer": {...}|None}``

    On network/HTTP error, logs a warning and returns ``{}``.
    """
    url = (
        f"{settings.COGNITION_FABRIC_NODE_URL}{_API_PREFIX}"
        f"/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
        f"/semantic-negotiation/decide"
    )
    body = {
        "session_id": session_id,
        "agent_replies": agent_replies,
    }
    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("CFN decide_negotiation failed: %r", exc)
        return {}
