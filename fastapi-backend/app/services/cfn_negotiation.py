# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

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
    # Per-call HTTP timing breakdown.  Break the call into:
    #   client_setup_ms   : AsyncClient context-manager entry (TLS, pool init)
    #   http_ms           : actual await client.post(...) (the on-the-wire time)
    #   raise_for_status_ms : status check (cheap, but timed for completeness)
    #   json_parse_ms     : resp.json() — can be non-trivial for fat payloads
    # The contextvar bucket is owned by the caller (coordination._cfn_decide_round)
    # and read after _cfn_post returns; if no caller installed one, all the
    # timing_stage() calls become no-ops.
    from app.services._cfn_call_timing import cfn_timing_stage, cfn_timing_stamp

    cfn_timing_stamp("endpoint", endpoint)
    try:
        client_cm = httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT)
        with cfn_timing_stage("client_setup_ms"):
            client = await client_cm.__aenter__()
        entered = True
        try:
            # Stamp wall-clock send time so CFN can compute
            # wire_to_middleware_ms = cfn_received_at - X-Client-Sent-Wall-Ns.
            # Both containers share the host clock (sub-ms skew on the same kernel).
            import time as _time

            sent_ns = _time.time_ns()
            cfn_timing_stamp("sent_wall_ns", sent_ns)
            headers = {"X-Client-Sent-Wall-Ns": str(sent_ns)}
            with cfn_timing_stage("http_ms"):
                resp = await client.post(url, json=body, headers=headers)
            with cfn_timing_stage("raise_for_status_ms"):
                resp.raise_for_status()
            with cfn_timing_stage("json_parse_ms"):
                data = resp.json()
            cfn_timing_stamp("response_bytes", len(resp.content))
            # Pull CFN's per-request loop-lag stats out of the response
            # headers and into the timing snapshot.  These tell
            # us whether CFN's event loop was blocked *during* the request
            # — a non-zero value here for a slow request means the wedge
            # was inside the handler/deps, not just before middleware fired.
            for hdr_key in (
                "x-cfn-loop-lag-samples-n",
                "x-cfn-loop-lag-mean-ms",
                "x-cfn-loop-lag-p95-ms",
                "x-cfn-loop-lag-max-ms",
            ):
                v = resp.headers.get(hdr_key)
                if v is not None:
                    try:
                        # All these are numeric; n is int, the rest float.
                        cfn_timing_stamp(
                            hdr_key.replace("x-", "").replace("-", "_"),
                            int(v) if "samples-n" in hdr_key else float(v),
                        )
                    except (ValueError, TypeError):
                        pass
            return data
        finally:
            if entered:
                with cfn_timing_stage("client_close_ms"):
                    await client_cm.__aexit__(None, None, None)
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
