# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Async client for the CFN cognitive agents semantic negotiation API.

Calls go through the generated ``ioc_cfn_svc_api_client`` (regenerated from
``http://localhost:9002/openapi.json`` via ``scripts/gen-cfn-client.sh``).
The typed client is the contract — ty catches breaking CFN field changes
at the call sites below when the client is regenerated.

Endpoints used:
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/start
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-negotiation/decide
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.services._cfn_call_timing import cfn_timing_stage, cfn_timing_stamp
from app.services.metrics import record_cfn_call, record_cfn_llm_usage, record_room_identity
from ioc_cfn_svc_api_client import Client
from ioc_cfn_svc_api_client.api.semantic_negotiation import (
    decide_negotiation_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_negotiation_decide_post as decide_api,
)
from ioc_cfn_svc_api_client.api.semantic_negotiation import (
    start_negotiation_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_negotiation_start_post as start_api,
)
from ioc_cfn_svc_api_client.errors import UnexpectedStatus
from ioc_cfn_svc_api_client.models import (
    Agent,
    AgentReply,
    AgentReplyAction,
    AgentReplyOfferType0,
    DecideRequest,
    HTTPValidationError,
    InitiateNegotiationRequest,
)
from ioc_cfn_svc_api_client.types import UNSET

logger = logging.getLogger(__name__)

# CFN runs LLM + intent discovery + options generation; 60s is too short.
# /decide can also take a while when CFN persists agreements to shared memory.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


class CfnNegotiationError(RuntimeError):
    """CFN semantic-negotiation call failed. The message is user-facing."""


def _client(**extra_headers: str) -> Client:
    return Client(
        base_url=settings.CFN_SVC_URL or "",
        timeout=_CFN_HTTP_TIMEOUT,
        raise_on_unexpected_status=True,
        headers=dict(extra_headers) if extra_headers else {},
    )


def _describe_exc(exc: Exception) -> str:
    """Turn a client/httpx exception into a short, user-legible reason string."""
    name = type(exc).__name__
    if isinstance(exc, UnexpectedStatus):
        body = exc.content[:200].decode("utf-8", errors="replace").replace("\n", " ").strip()
        return f"{name} {exc.status_code}: {body}" if body else f"{name} {exc.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        read_timeout = _CFN_HTTP_TIMEOUT.read
        timeout_s = float(read_timeout) if isinstance(read_timeout, int | float) else 0.0
        return f"{name}: request exceeded {int(timeout_s)}s"
    msg = str(exc).strip()
    return f"{name}: {msg}" if msg else name


def _raise_if_validation_error(
    result: Any | HTTPValidationError | None, endpoint: str
) -> dict[str, Any]:
    """Coerce the typed-client return into a dict, or raise with a clear reason.

    The /start and /decide endpoints are typed as ``Any | HTTPValidationError | None``
    because CFN returns an open-ended JSON document — we accept whatever and return
    it as ``dict[str, Any]``. If CFN sends a 422 instead, surface it as an error.
    """
    if isinstance(result, HTTPValidationError):
        details = result.detail if not isinstance(result.detail, type(UNSET)) else "no detail"
        raise CfnNegotiationError(f"CFN {endpoint} validation error: {details}")
    if not isinstance(result, dict):
        raise CfnNegotiationError(
            f"CFN {endpoint} returned unexpected payload type: {type(result).__name__}"
        )
    return result


def _extract_cfn_usage(
    result: dict[str, Any], operation: str, *, room: str = "", mas_id: str = ""
) -> None:
    """Extract token usage from a CFN response and record it as metrics.

    Handles two shapes:
    - Legacy Python CE: ``_usage`` top-level key with flat fields
    - Go CE: ``meta`` key with nested ``tokens.prompt/completion/total`` structure
    """
    record_room_identity(mas_id=mas_id, room_name=room)

    # Legacy Python CE shape
    usage = result.pop("_usage", None)
    if isinstance(usage, dict):
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
        return

    # Go CE shape: meta.tokens.{prompt,completion,total}
    meta = result.get("meta")
    if not isinstance(meta, dict):
        return
    tokens = meta.get("tokens", {})
    prompt = tokens.get("prompt", 0)
    completion = tokens.get("completion", 0)
    total = tokens.get("total", 0)
    latency = meta.get("latency_ms", 0.0)
    record_cfn_llm_usage(
        operation=operation,
        room=room,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=0,
        total_tokens=total,
        llm_calls=1,
        latency_ms=latency,
        by_operation=None,
    )
    logger.debug(
        "CFN %s usage: %d prompt, %d completion tokens, %.1f ms",
        operation,
        prompt,
        completion,
        latency,
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
    """Call CFN /start. Raises :class:`CfnNegotiationError` on any failure.

    ``agents`` items: ``{"id": handle, "name": handle}``
    """
    cfn_timing_stamp("endpoint", "start_negotiation")
    sent_ns = time.time_ns()
    cfn_timing_stamp("sent_wall_ns", sent_ns)

    body = InitiateNegotiationRequest(
        session_id=session_id,
        content_text=content_text,
        agents=[Agent(id=a["id"], name=a["name"]) for a in agents],
        n_steps=n_steps if n_steps and n_steps > 0 else UNSET,
    )
    t0 = time.monotonic()
    try:
        with cfn_timing_stage("client_setup_ms"):
            client_cm = _client(**{"X-Client-Sent-Wall-Ns": str(sent_ns)})
            client = await client_cm.__aenter__()
        try:
            with cfn_timing_stage("http_ms"):
                resp = await start_api.asyncio_detailed(
                    workspace_id=workspace_id,
                    mas_id=mas_id,
                    client=client,
                    body=body,
                )
            cfn_timing_stamp("response_bytes", len(resp.content))
            _extract_cfn_loop_lag_headers(resp.headers)
        finally:
            with cfn_timing_stage("client_close_ms"):
                await client_cm.__aexit__(None, None, None)
    except UnexpectedStatus as exc:
        reason = _describe_exc(exc)
        logger.warning(
            "CFN start_negotiation failed | status=%d body=%r",
            exc.status_code,
            exc.content[:500],
        )
        record_cfn_call(
            service="node",
            operation="start_negotiation",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=exc.status_code,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    except Exception as exc:
        reason = _describe_exc(exc)
        logger.exception("CFN start_negotiation failed | reason=%s", reason)
        record_cfn_call(
            service="node",
            operation="start_negotiation",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    record_cfn_call(
        service="node",
        operation="start_negotiation",
        duration_ms=(time.monotonic() - t0) * 1000,
        status_code=resp.status_code,
    )
    result = _raise_if_validation_error(resp.parsed, "start_negotiation")
    _extract_cfn_usage(result, "start_negotiation", room=room, mas_id=mas_id)
    return result


def _build_agent_reply(item: dict[str, Any]) -> AgentReply:
    # Support both legacy "agent_id" and current "participant_id" key
    pid = item.get("participant_id") or item.get("agent_id", "")
    raw_offer = item.get("offer", UNSET)
    if raw_offer is None:
        return AgentReply(
            participant_id=pid,
            action=AgentReplyAction(item["action"]),
            offer=None,
        )
    if isinstance(raw_offer, dict):
        return AgentReply(
            participant_id=pid,
            action=AgentReplyAction(item["action"]),
            offer=AgentReplyOfferType0.from_dict(raw_offer),
        )
    return AgentReply(
        participant_id=pid,
        action=AgentReplyAction(item["action"]),
    )


async def decide_negotiation(
    *,
    session_id: str,
    agent_replies: list[dict[str, Any]],
    workspace_id: str,
    mas_id: str,
) -> dict[str, Any]:
    """Call CFN /decide. Raises :class:`CfnNegotiationError` on any failure.

    ``agent_replies`` items: ``{"participant_id": handle, "action": "accept"|"reject"|"counter_offer", "offer": {...}|None}``
    """
    cfn_timing_stamp("endpoint", "decide_negotiation")
    sent_ns = time.time_ns()
    cfn_timing_stamp("sent_wall_ns", sent_ns)

    body = DecideRequest(
        session_id=session_id,
        agent_replies=[_build_agent_reply(r) for r in agent_replies],
    )
    t0 = time.monotonic()
    try:
        with cfn_timing_stage("client_setup_ms"):
            client_cm = _client(**{"X-Client-Sent-Wall-Ns": str(sent_ns)})
            client = await client_cm.__aenter__()
        try:
            with cfn_timing_stage("http_ms"):
                resp = await decide_api.asyncio_detailed(
                    workspace_id=workspace_id,
                    mas_id=mas_id,
                    client=client,
                    body=body,
                )
            cfn_timing_stamp("response_bytes", len(resp.content))
            _extract_cfn_loop_lag_headers(resp.headers)
        finally:
            with cfn_timing_stage("client_close_ms"):
                await client_cm.__aexit__(None, None, None)
    except UnexpectedStatus as exc:
        reason = _describe_exc(exc)
        logger.warning(
            "CFN decide_negotiation failed | status=%d body=%r",
            exc.status_code,
            exc.content[:500],
        )
        record_cfn_call(
            service="node",
            operation="decide_negotiation",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=exc.status_code,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    except Exception as exc:
        reason = _describe_exc(exc)
        logger.exception("CFN decide_negotiation failed | reason=%s", reason)
        record_cfn_call(
            service="node",
            operation="decide_negotiation",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    record_cfn_call(
        service="node",
        operation="decide_negotiation",
        duration_ms=(time.monotonic() - t0) * 1000,
        status_code=resp.status_code,
    )
    result = _raise_if_validation_error(resp.parsed, "decide_negotiation")
    return result
