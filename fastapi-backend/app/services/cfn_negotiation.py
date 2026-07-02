# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Async client for the CFN semantic-alignment API (ioc-cfn-svc, the Go CFN).

Endpoints used:
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-alignment/start
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-alignment/decide

Request shapes:
  start:  {session_id, content_text, agents: [{id, name}], n_steps?}
  decide: {session_id, agent_replies: [{participant_id, action, offer?}]}

Terminal agreements arrive as a ``final_result`` SSTP envelope (normalized in
``coordination.py:_normalize_cfn_decide_response``) and responses carry
``trace``/``meta``/``shared_memory`` extras. The CFN auto-persists agreements
to shared memory (surfaced as ``cfn_persisted`` on the consensus payload).

Plain httpx, no generated client — two endpoints with open-ended JSON
responses. (The python CFN's semantic-negotiation API and its generated
``ioc_cfn_svc_api_client`` were removed in 2.0.0.)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.services._cfn_call_timing import cfn_timing_stage, cfn_timing_stamp
from app.services.metrics import record_cfn_call, record_cfn_llm_usage, record_room_identity

logger = logging.getLogger(__name__)

# CFN runs LLM + intent discovery + options generation; 60s is too short.
# /decide can also take a while when CFN persists agreements to shared memory.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


class CfnNegotiationError(RuntimeError):
    """CFN semantic-alignment call failed. The message is user-facing."""


def _describe_exc(exc: Exception) -> str:
    """Turn an httpx exception into a short, user-legible reason string."""
    name = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        read_timeout = _CFN_HTTP_TIMEOUT.read
        timeout_s = float(read_timeout) if isinstance(read_timeout, int | float) else 0.0
        return f"{name}: request exceeded {int(timeout_s)}s"
    msg = str(exc).strip()
    return f"{name}: {msg}" if msg else name


def _extract_cfn_usage(
    result: dict[str, Any], operation: str, *, room: str = "", mas_id: str = ""
) -> None:
    """Extract ``_usage`` from a CFN response and record it as metrics.

    ``mas_id`` is captured alongside ``room`` into the snapshot's
    ``room_identities`` map so the CLI can keep displaying the
    room ↔ mas_id link even after the room is hard-deleted.
    """
    record_room_identity(mas_id=mas_id, room_name=room)
    usage = result.pop("_usage", None)
    if not isinstance(usage, dict):
        return
    record_cfn_llm_usage(
        operation=operation,
        room=room,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cached_tokens=usage.get("cached_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        llm_calls=usage.get("llm_calls", 0),
        latency_ms=usage.get("total_latency_ms", 0.0),
        by_operation=usage.get("by_operation"),
    )
    logger.debug(
        "CFN %s usage: %d calls, %d prompt, %d completion tokens",
        operation,
        usage.get("llm_calls", 0),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def _extract_cfn_loop_lag_headers(headers: Any) -> None:
    """Pull CFN's per-request loop-lag stats from response headers into the timing snapshot.

    These tell us whether CFN's event loop was blocked *during* the request
    — a non-zero value for a slow request means the wedge was inside the
    handler/deps, not before middleware fired.
    """
    for hdr_key in (
        "x-cfn-loop-lag-samples-n",
        "x-cfn-loop-lag-mean-ms",
        "x-cfn-loop-lag-p95-ms",
        "x-cfn-loop-lag-max-ms",
    ):
        v = headers.get(hdr_key)
        if v is not None:
            try:
                cfn_timing_stamp(
                    hdr_key.replace("x-", "").replace("-", "_"),
                    int(v) if "samples-n" in hdr_key else float(v),
                )
            except (ValueError, TypeError):
                pass


async def _post_alignment(
    *,
    op: str,
    workspace_id: str,
    mas_id: str,
    payload: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    """POST to the CFN's semantic-alignment API with the standard
    timing/metrics instrumentation. Raises :class:`CfnNegotiationError`."""
    sent_ns = time.time_ns()
    cfn_timing_stamp("sent_wall_ns", sent_ns)
    url = (
        f"{settings.COGNITION_FABRIC_NODE_URL}/api/workspaces/{workspace_id}"
        f"/multi-agentic-systems/{mas_id}/semantic-alignment/{op}"
    )
    t0 = time.monotonic()
    try:
        with cfn_timing_stage("client_setup_ms"):
            client = httpx.AsyncClient(
                timeout=_CFN_HTTP_TIMEOUT,
                headers={"X-Client-Sent-Wall-Ns": str(sent_ns)},
            )
        try:
            with cfn_timing_stage("http_ms"):
                resp = await client.post(url, json=payload)
            cfn_timing_stamp("response_bytes", len(resp.content))
            _extract_cfn_loop_lag_headers(resp.headers)
        finally:
            with cfn_timing_stage("client_close_ms"):
                await client.aclose()
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.content[:200].decode("utf-8", errors="replace").strip()
        reason = f"CFN {op} returned {exc.response.status_code}: {body}"
        logger.warning("CFN %s failed | %s", operation, reason)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=exc.response.status_code,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    except Exception as exc:
        reason = _describe_exc(exc)
        logger.exception("CFN %s failed | reason=%s", operation, reason)
        record_cfn_call(
            service="node",
            operation=operation,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    record_cfn_call(
        service="node",
        operation=operation,
        duration_ms=(time.monotonic() - t0) * 1000,
        status_code=resp.status_code,
    )
    if not isinstance(result, dict):
        raise CfnNegotiationError(
            f"CFN {op} returned unexpected payload type: {type(result).__name__}"
        )
    return result


async def start_negotiation(
    *,
    session_id: str,
    content_text: str,
    agents: list[dict[str, str]],
    workspace_id: str,
    mas_id: str,
    n_steps: int = 20,
    room: str = "",
) -> dict[str, Any]:
    """Call CFN semantic-alignment /start. Raises :class:`CfnNegotiationError`.

    ``agents`` items: ``{"id": handle, "name": handle}``
    """
    cfn_timing_stamp("endpoint", "start_negotiation")
    payload: dict[str, Any] = {
        "session_id": session_id,
        "content_text": content_text,
        "agents": [{"id": a["id"], "name": a["name"]} for a in agents],
    }
    if n_steps and n_steps > 0:
        payload["n_steps"] = n_steps
    result = await _post_alignment(
        op="start",
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload=payload,
        operation="start_negotiation",
    )
    _extract_cfn_usage(result, "start_negotiation", room=room, mas_id=mas_id)
    return result


async def decide_negotiation(
    *,
    session_id: str,
    agent_replies: list[dict[str, Any]],
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any]:
    """Call CFN semantic-alignment /decide. Raises :class:`CfnNegotiationError`.

    ``agent_replies`` items: ``{"agent_id": handle, "action": "accept"|"reject"|"counter_offer", "offer": {...}|None}``

    The alignment API keys replies on ``participant_id``; epistemic extras
    (confidence/evidence/deferred_to/reasoning) that mycelium tracks on the
    reply dicts are deliberately NOT forwarded to CFN.
    """
    cfn_timing_stamp("endpoint", "decide_negotiation")
    replies = []
    for r in agent_replies:
        reply: dict[str, Any] = {
            "participant_id": r["agent_id"],
            "action": r["action"],
        }
        if isinstance(r.get("offer"), dict):
            reply["offer"] = r["offer"]
        replies.append(reply)
    return await _post_alignment(
        op="decide",
        workspace_id=workspace_id,
        mas_id=mas_id,
        payload={"session_id": session_id, "agent_replies": replies},
        operation="decide_negotiation",
    )
