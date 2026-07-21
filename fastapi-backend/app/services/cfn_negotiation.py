# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Async client for the CFN semantic-alignment API (ioc-cfn-svc, the Go CFN).

TRANSITIONAL (per CFN team, 2026-07-07): this REST contract is a bridge, not a
permanent surface. The Semantic Alignment CE (formerly "sem neg") is being
reworked to process L9 natively (specifically the SAB subprotocol) and once
that lands the CFN's ``semantic-alignment/start|decide`` endpoints are removed.
At that point mycelium's negotiation path migrates onto the L9 envelope layer
(``app/services/l9.py`` / ``l9_episode.py``), which is why we already emit L9
envelopes today. Don't over-invest in this typed client; it exists to make the
current endpoints safe during the transition.

Endpoints:
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-alignment/start
  POST /api/workspaces/{ws}/multi-agentic-systems/{mas}/semantic-alignment/decide

Calls go through the generated ``ioc_cfn_svc_api_client`` (regenerated from the
Go CFN's swagger via ``scripts/gen-cfn-client.sh``). Three layers of contract
enforcement:

1. **Typed request construction**: ``StartRequest``/``DecideRequest``/
   ``AgentReply`` are built as typed models; ``ty`` catches a field we got
   wrong at the call site.
2. **Schema-validated response parsing**: the client parses the HTTP body
   into ``StartResponse``/``DecideResponse``, so a structural mismatch shows
   up here, not three layers deep in coordination.
3. **Presence assertions**: swaggo marks every field optional, so a CFN-side
   *rename* would silently become ``UNSET`` rather than raise. We assert the
   fields we depend on and raise :class:`CfnNegotiationError` on drift.

Two response fields are deliberately NOT trusted from the typed model:
``messages`` (Go ``[]json.RawMessage``, swaggo mis-renders as ``[]int``, but
the runtime shape is a list of JSON envelope objects) and ``final_result``
(Go ``map[string]interface{}``: opaque by the CFN's own contract). We return
the validated model's ``to_dict()`` to coordination so those two are handed
over as their real dict form, never as a mis-typed field. The returned dict is
in the Go CFN's JSON shape (top-level ``status``/``meta``/``final_result``/
``shared_memory``).
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
from ioc_cfn_svc_api_client.api.semantic_alignment import (
    post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_decide as decide_api,
)
from ioc_cfn_svc_api_client.api.semantic_alignment import (
    post_api_workspaces_workspace_id_multi_agentic_systems_mas_id_semantic_alignment_start as start_api,
)
from ioc_cfn_svc_api_client.errors import UnexpectedStatus
from ioc_cfn_svc_api_client.models import (
    SemanticalignmentAgent,
    SemanticalignmentAgentReply,
    SemanticalignmentAgentReplyOffer,
    SemanticalignmentDecideRequest,
    SemanticalignmentDecideResponse,
    SemanticalignmentStartRequest,
    SemanticalignmentStartResponse,
)
from ioc_cfn_svc_api_client.types import UNSET, Unset

logger = logging.getLogger(__name__)

# CFN runs LLM + intent discovery + options generation; 60s is too short.
# /decide can also take a while when CFN persists agreements to shared memory.
# Configurable via CFN_DECIDE_TIMEOUT_SECONDS.
_CFN_HTTP_TIMEOUT = httpx.Timeout(float(settings.CFN_DECIDE_TIMEOUT_SECONDS))


class CfnNegotiationError(RuntimeError):
    """CFN semantic-alignment call failed. The message is user-facing."""


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


def _extract_cfn_loop_lag_headers(headers: Any) -> None:
    """Pull CFN's per-request loop-lag stats from response headers into the timing snapshot."""
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


def _record_meta_usage(meta: Any, operation: str, *, room: str, mas_id: str) -> None:
    """Record token usage from a response's typed ``meta`` (CommonTokenUsageMeta).

    The Go CFN reports usage in ``meta.tokens`` (prompt/completion/total) with
    ``meta.cost_usd`` / ``meta.latency_ms``. (The python CFN used a top-level
    ``_usage`` key; reading that against the Go CFN silently recorded nothing;
    the typed client surfaced the drift.)
    """
    record_room_identity(mas_id=mas_id, room_name=room)
    if isinstance(meta, Unset) or meta is None:
        return
    tokens = getattr(meta, "tokens", None)

    def _num(v: Any) -> float:
        return float(v) if isinstance(v, int | float) else 0.0

    prompt = _num(getattr(tokens, "prompt", 0))
    completion = _num(getattr(tokens, "completion", 0))
    total = _num(getattr(tokens, "total", 0))
    if not (prompt or completion or total):
        return
    record_cfn_llm_usage(
        operation=operation,
        room=room,
        prompt_tokens=int(prompt),
        completion_tokens=int(completion),
        cached_tokens=0,
        total_tokens=int(total),
        llm_calls=1,
        latency_ms=_num(getattr(meta, "latency_ms", 0.0)),
        by_operation={
            operation: {
                "calls": 1,
                "prompt_tokens": int(prompt),
                "completion_tokens": int(completion),
            }
        },
    )


def _require(value: Any, field: str, endpoint: str) -> Any:
    """Assert a depended-on response field is present. Raises on drift."""
    if isinstance(value, Unset) or value is None:
        raise CfnNegotiationError(
            f"CFN {endpoint} response missing required field {field!r}: "
            f"the semantic-alignment contract may have changed "
            f"(regenerate the client with scripts/gen-cfn-client.sh)"
        )
    return value


async def _post_typed(
    endpoint_module: Any,
    *,
    op_name: str,
    workspace_id: str,
    mas_id: str,
    body: Any,
    expected: type,
) -> Any:
    """Run a typed endpoint call with the shared timing/metrics instrumentation.

    Returns the validated response model (an instance of ``expected``). Raises
    :class:`CfnNegotiationError` on transport failure, error-status response,
    or a parsed body that isn't the expected model.
    """
    cfn_timing_stamp("endpoint", op_name)
    sent_ns = time.time_ns()
    cfn_timing_stamp("sent_wall_ns", sent_ns)
    t0 = time.monotonic()
    try:
        with cfn_timing_stage("client_setup_ms"):
            client_cm = _client(**{"X-Client-Sent-Wall-Ns": str(sent_ns)})
            client = await client_cm.__aenter__()
        try:
            with cfn_timing_stage("http_ms"):
                resp = await endpoint_module.asyncio_detailed(
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
            "CFN %s failed | status=%d body=%r", op_name, exc.status_code, exc.content[:500]
        )
        record_cfn_call(
            service="node",
            operation=op_name,
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=exc.status_code,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc
    except Exception as exc:
        reason = _describe_exc(exc)
        logger.exception("CFN %s failed | reason=%s", op_name, reason)
        record_cfn_call(
            service="node",
            operation=op_name,
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        raise CfnNegotiationError(reason) from exc

    record_cfn_call(
        service="node",
        operation=op_name,
        duration_ms=(time.monotonic() - t0) * 1000,
        status_code=resp.status_code,
    )
    parsed = resp.parsed
    if not isinstance(parsed, expected):
        # Error-status body (typed error model) or an unparseable payload.
        body_snip = resp.content[:200].decode("utf-8", errors="replace").strip()
        raise CfnNegotiationError(
            f"CFN {op_name} returned {resp.status_code} with unexpected payload: {body_snip}"
        )
    return parsed


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

    ``agents`` items: ``{"id": handle, "name": handle}``. Returns the validated
    response as a dict in the Go CFN's JSON shape.
    """
    body = SemanticalignmentStartRequest(
        session_id=session_id,
        content_text=content_text,
        agents=[SemanticalignmentAgent(id=a["id"], name=a["name"]) for a in agents],
        n_steps=n_steps if n_steps and n_steps > 0 else UNSET,
    )
    model: SemanticalignmentStartResponse = await _post_typed(
        start_api,
        op_name="start_negotiation",
        workspace_id=workspace_id,
        mas_id=mas_id,
        body=body,
        expected=SemanticalignmentStartResponse,
    )
    _require(model.status, "status", "start_negotiation")
    _record_meta_usage(model.meta, "start_negotiation", room=room, mas_id=mas_id)
    return model.to_dict()


def _build_agent_reply(item: dict[str, Any]) -> SemanticalignmentAgentReply:
    """Build a typed AgentReply from coordination's reply dict.

    The alignment API keys replies on ``participant_id``; the offer (counter
    only) is a free-form issue→option map.
    """
    raw_offer = item.get("offer")
    offer: SemanticalignmentAgentReplyOffer | Unset = UNSET
    if isinstance(raw_offer, dict):
        offer = SemanticalignmentAgentReplyOffer.from_dict(raw_offer)
    return SemanticalignmentAgentReply(
        participant_id=item["agent_id"],
        action=item["action"],
        offer=offer,
    )


async def decide_negotiation(
    *,
    session_id: str,
    agent_replies: list[dict[str, Any]],
    workspace_id: str,
    mas_id: str,
    room: str = "",
) -> dict[str, Any]:
    """Call CFN semantic-alignment /decide. Raises :class:`CfnNegotiationError`.

    ``agent_replies`` items: ``{"agent_id", "action", "offer"?}``. Epistemic
    extras that coordination tracks on the reply dicts (confidence/evidence/
    deferred_to/reasoning) are NOT forwarded to CFN; they never leave
    Mycelium. Returns the validated response as a dict in the Go CFN's shape.
    """
    body = SemanticalignmentDecideRequest(
        session_id=session_id,
        agent_replies=[_build_agent_reply(r) for r in agent_replies],
    )
    model: SemanticalignmentDecideResponse = await _post_typed(
        decide_api,
        op_name="decide_negotiation",
        workspace_id=workspace_id,
        mas_id=mas_id,
        body=body,
        expected=SemanticalignmentDecideResponse,
    )
    _require(model.status, "status", "decide_negotiation")
    _record_meta_usage(model.meta, "decide_negotiation", room=room, mas_id=mas_id)
    return model.to_dict()
