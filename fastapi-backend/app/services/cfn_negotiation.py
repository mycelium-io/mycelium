# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
Async httpx client for the CFN cognitive agents semantic negotiation API.

The cognitive agents service (ioc-cognition-fabric-node-svc, port 9002) exposes:
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/start
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/decide
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# CFN runs LLM + intent discovery + options generation; 60s is too short.
# /decide can also take a while when CFN persists agreements to shared memory.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


class CfnNegotiationError(RuntimeError):
    """CFN semantic-negotiation call failed. The message is user-facing."""


def _mas_url(workspace_id: str, mas_id: str, endpoint: str) -> str:
    return (
        f"{settings.COGNITION_FABRIC_NODE_URL}"
        f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
        f"/semantic-negotiation/{endpoint}"
    )


def _describe_exc(exc: Exception) -> str:
    """Turn an httpx exception into a short, user-legible reason string.

    ``httpx.ReadTimeout(message=None)`` has an empty ``__str__``, which is how
    we previously shipped blank error cards to the UI. Always fall back to the
    exception type name so the user sees *something*.
    """
    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text[:200].replace("\n", " ").strip()
        return (
            f"{name} {exc.response.status_code}: {body}"
            if body
            else f"{name} {exc.response.status_code}"
        )
    if isinstance(exc, httpx.TimeoutException):
        return f"{name}: request exceeded {int(_CFN_HTTP_TIMEOUT.read or 0)}s"
    msg = str(exc).strip()
    return f"{name}: {msg}" if msg else name


async def _cfn_post(url: str, body: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """POST to CFN and raise ``CfnNegotiationError`` with a descriptive reason on any failure."""
    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        reason = _describe_exc(exc)
        logger.warning(
            "CFN %s failed | url=%s status=%d body=%r",
            endpoint,
            url,
            exc.response.status_code,
            exc.response.text[:500],
        )
        raise CfnNegotiationError(reason) from exc
    except Exception as exc:
        reason = _describe_exc(exc)
        logger.exception("CFN %s failed | url=%s reason=%s", endpoint, url, reason)
        raise CfnNegotiationError(reason) from exc


async def start_negotiation(
    *,
    session_id: str,
    content_text: str,
    agents: list[dict[str, str]],
    workspace_id: str,
    mas_id: str,
    n_steps: int = 20,
) -> dict[str, Any]:
    """Call CFN /start. Raises :class:`CfnNegotiationError` on any failure.

    ``agents`` items: ``{"id": handle, "name": handle}``
    """
    url = _mas_url(workspace_id, mas_id, "start")
    body = {
        "session_id": session_id,
        "content_text": content_text,
        "agents": agents,
        "n_steps": n_steps,
    }
    return await _cfn_post(url, body, endpoint="start_negotiation")


async def decide_negotiation(
    *,
    session_id: str,
    agent_replies: list[dict[str, Any]],
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any]:
    """Call CFN /decide. Raises :class:`CfnNegotiationError` on any failure.

    ``agent_replies`` items: ``{"agent_id": handle, "action": "accept"|"reject"|"counter_offer", "offer": {...}|None}``
    """
    url = _mas_url(workspace_id, mas_id, "decide")
    body = {
        "session_id": session_id,
        "agent_replies": agent_replies,
    }
    return await _cfn_post(url, body, endpoint="decide_negotiation")
