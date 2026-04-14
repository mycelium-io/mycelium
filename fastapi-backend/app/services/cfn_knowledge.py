# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Async httpx client for CFN's shared-memories knowledge API.

The ioc-cognition-fabric-node-svc (CFN) exposes shared-memories endpoints under
``/api/workspaces/{ws}/multi-agentic-systems/{mas}/``:

  POST  shared-memories              create/update knowledge (this module)
  POST  shared-memories/query        semantic query            (C5)
  GET   graph/neighbors/{id}         graph neighbors           (C5)
  POST  graph/concepts/by_ids        concepts by id            (C5)
  POST  graph/paths                  graph paths               (C5)

CFN runs the heavy work (two-stage LLM extraction via ioc-cfn-cognitive-engines'
ingestion agent, embeddings, KG writes) inside the handler, so timeouts are
generous. Errors are raised as :class:`CfnKnowledgeError`; the route handler is
responsible for appending attempt records to the ingest log buffer and
translating failures to client-facing HTTP statuses.
"""

import json
import logging
import uuid
from typing import Any

import httpx
import tiktoken

from app.config import settings

logger = logging.getLogger(__name__)

# Cached once at module load. tiktoken ships with litellm so no new dep.
_CL100K = tiktoken.get_encoding("cl100k_base")


def estimate_cfn_knowledge_input_tokens(records: list[dict[str, Any]]) -> int:
    """Input-side proxy for the LLM cost CFN will pay on these records.

    Encodes the JSON-serialized ``records`` with ``cl100k_base``. CFN's actual
    LLM consumption (system prompts, two-pass concept+relation extraction,
    embeddings) is typically higher; this is a cost-awareness signal, not a
    billing figure.
    """
    return len(_CL100K.encode(json.dumps(records)))

# CFN shared-memories runs concept + relationship LLM extraction plus
# embeddings. Match cfn_negotiation.py's 300s ceiling.
_CFN_HTTP_TIMEOUT = httpx.Timeout(300.0)


class CfnKnowledgeError(RuntimeError):
    """Raised when a CFN shared-memories request fails.

    ``status_code`` is set when the failure came from a non-2xx HTTP response;
    it is ``None`` for transport-level failures (timeout, connection refused).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _mas_base(workspace_id: str, mas_id: str) -> str:
    return (
        f"{settings.COGNITION_FABRIC_NODE_URL}"
        f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}"
    )


async def create_or_update_shared_memories(
    *,
    workspace_id: str,
    mas_id: str,
    records: list[dict[str, Any]],
    agent_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """POST openclaw turns to CFN's ``shared-memories`` create/update endpoint.

    Builds a ``CreateOrUpdateRequest`` body with ``metadata.format="openclaw"``
    and the provided ``records`` as ``payload.data``. Returns CFN's response as
    a dict, typically ``{"response_id": str, "message": str | None}``.

    Raises :class:`CfnKnowledgeError` on any HTTP or transport failure.
    """
    url = f"{_mas_base(workspace_id, mas_id)}/shared-memories"
    rid = request_id or str(uuid.uuid4())
    body: dict[str, Any] = {
        "request_id": rid,
        "payload": {
            "metadata": {"format": "openclaw"},
            "data": records,
        },
    }
    if agent_id:
        body["header"] = {"agent_id": agent_id}

    try:
        async with httpx.AsyncClient(timeout=_CFN_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        snippet = exc.response.text[:300]
        logger.warning(
            "CFN shared-memories create/update failed "
            "| status=%d workspace=%s mas=%s request_id=%s body=%r",
            status,
            workspace_id,
            mas_id,
            rid,
            snippet,
        )
        raise CfnKnowledgeError(
            f"CFN returned {status}: {snippet[:200]}",
            status_code=status,
        ) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.exception(
            "CFN shared-memories create/update unreachable "
            "| workspace=%s mas=%s request_id=%s",
            workspace_id,
            mas_id,
            rid,
        )
        raise CfnKnowledgeError(f"CFN unreachable: {exc}") from exc
