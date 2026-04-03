# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Async httpx client for the CFN cognitive agents semantic negotiation API.

The cognitive agents service (ioc-cognition-fabric-node-svc) exposes:
  POST /api/v1/negotiate/initiate  — start a new negotiation session
  POST /api/v1/negotiate/decide    — advance by one round with agent replies

Both endpoints use the SSTP message envelope format.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _sstp_envelope(
    *,
    session_id: str,
    workspace_id: str,
    mas_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a minimal valid SSTPNegotiateMessage envelope."""
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    return {
        "version": "0",
        "kind": "negotiate",
        "message_id": str(uuid4()),
        "dt_created": datetime.now(UTC).isoformat(),
        "origin": {
            "actor_id": mas_id,
            "tenant_id": workspace_id,
        },
        "semantic_context": {
            "schema_id": "urn:ioc:schema:negotiate:negmas-sao:v1",
            "schema_version": "1.0",
            "encoding": "json",
            "session_id": session_id,
        },
        "payload_hash": payload_hash,
        "policy_labels": {
            "sensitivity": "internal",
            "propagation": "local",
            "retention_policy": "default",
        },
        "provenance": {"sources": [], "transforms": []},
        "payload": payload,
    }


async def start_negotiation(
    *,
    session_id: str,
    content_text: str,
    agents: list[dict[str, str]],
    workspace_id: str,
    mas_id: str,
    n_steps: int = 20,
) -> dict[str, Any]:
    """Call CFN /initiate endpoint.  Returns the raw response dict.

    ``agents`` items: ``{"id": handle, "name": handle}``

    On network/HTTP error, logs a warning and returns ``{}``.
    """
    url = f"{settings.COGNITION_FABRIC_NODE_URL}/api/v1/negotiate/initiate"
    body = _sstp_envelope(
        session_id=session_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload={
            "content_text": content_text,
            "agents": agents,
            "n_steps": n_steps,
        },
    )
    try:
        async with httpx.AsyncClient(timeout=120) as client:
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
    """Call CFN /decide endpoint.  Returns the raw response dict.

    ``agent_replies`` items: ``{"agent_id": handle, "action": "accept"|"reject"|"counter_offer", "offer": {...}|None}``

    On network/HTTP error, logs a warning and returns ``{}``.
    """
    url = f"{settings.COGNITION_FABRIC_NODE_URL}/api/v1/negotiate/decide"
    body = _sstp_envelope(
        session_id=session_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload={
            "session_id": session_id,
            "agent_replies": agent_replies,
        },
    )
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("CFN decide_negotiation failed: %s", exc)
        return {}
