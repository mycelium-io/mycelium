# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SLIM group round-trip integration test.

Needs a running ``slim`` node. Guarded so the default unit suite stays green
without one: if the node endpoint is unreachable, the test is skipped. Point at
a node with ``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``); run
one via ``mycelium hub host``.
"""

import os
import socket
from urllib.parse import urlparse

import pytest

pytest.importorskip("slim_bindings")

from app.services.slim_client import DEFAULT_NODE_ENDPOINT

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)


def _node_reachable(endpoint: str, *, timeout: float = 1.0) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 46357
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _node_reachable(_ENDPOINT),
    reason=f"no reachable SLIM node at {_ENDPOINT} (set MYCELIUM_SLIM_ENDPOINT or run `mycelium hub host`)",
)


@pytest.mark.asyncio
async def test_group_broadcast_round_trip():
    """Moderator creates + invites; participant publishes; moderator receives it."""
    from scripts.slim_roundtrip import _MESSAGE, run_roundtrip

    payload = await run_roundtrip(_ENDPOINT)
    assert payload == _MESSAGE
