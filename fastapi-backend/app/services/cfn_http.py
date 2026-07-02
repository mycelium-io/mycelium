# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Shared httpx client for CFN calls.

A client per request defeats connection pooling and pays TCP+TLS setup on
every negotiation round (PR #391 review). Clients are cached per running
event loop — production has one loop for the app's lifetime, while each
pytest-asyncio test gets a fresh loop, so a cached client never outlives
its loop. ``aclose_all()`` is wired into the app lifespan shutdown.

Callers pass per-request ``timeout=``/``headers=`` overrides on the request
itself rather than configuring the client.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_clients: dict[int, httpx.AsyncClient] = {}


def get_client() -> httpx.AsyncClient:
    """Return the shared client for the current event loop (lazy init)."""
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient()
        _clients[loop_id] = client
    return client


async def aclose_all() -> None:
    """Close all cached clients. Called from the app lifespan shutdown."""
    for client in list(_clients.values()):
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception:  # never let shutdown cleanup raise
            logger.exception("cfn_http client close failed")
    _clients.clear()
