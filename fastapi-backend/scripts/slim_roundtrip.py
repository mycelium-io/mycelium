# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Throwaway Step 2 harness: prove a two-client group broadcast over a SLIM node.

Runs a moderator and a participant in one process against a running ``slim``
node. The moderator creates a group channel and invites the participant; the
participant publishes one message; the moderator receives the bytes. Prints
``OK`` and exits 0 on success.

Usage (with a node on :46357, e.g. via ``mycelium hub host``)::

    cd fastapi-backend
    uv run python scripts/slim_roundtrip.py
    # or point at another node:
    uv run python scripts/slim_roundtrip.py http://127.0.0.1:46357

This is a manual DoD aid; the guarded pytest equivalent lives in
``tests/test_slim_roundtrip.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python scripts/slim_roundtrip.py` from the backend root: the script's
# own dir is on sys.path by default, not the package root, so add it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.slim_client import (
    DEFAULT_NODE_ENDPOINT,
    SlimClient,
    SlimIdentity,
    to_channel_name,
    to_slim_name,
)

_WORKSPACE = "acme"
_ROOM = "hello-room"
_MESSAGE = b"hello over a slim group"


async def run_roundtrip(endpoint: str = DEFAULT_NODE_ENDPOINT) -> bytes:
    """Exchange one broadcast moderator<-participant; return what the moderator got."""
    moderator = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "moderator")).connect(endpoint)
    participant = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "participant")).connect(endpoint)

    channel = to_channel_name(_WORKSPACE, _ROOM)
    session = await moderator.create_group(channel)

    participant_name = to_slim_name(_WORKSPACE, _ROOM, "participant")

    async def participant_side() -> None:
        # Blocks until the moderator's invite lands, then broadcasts once.
        joined = await participant.listen_for_session()
        await SlimClient.publish(joined, _MESSAGE)

    participant_task = asyncio.create_task(participant_side())
    try:
        await moderator.invite(session, participant_name)
        payload = await SlimClient.receive(session, timeout_s=15.0)
    finally:
        await participant_task

    return payload


async def _main(endpoint: str) -> int:
    payload = await run_roundtrip(endpoint)
    if payload == _MESSAGE:
        print(f"OK — moderator received: {payload!r}")
        return 0
    print(f"MISMATCH — got {payload!r}, expected {_MESSAGE!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    node = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NODE_ENDPOINT
    raise SystemExit(asyncio.run(_main(node)))
