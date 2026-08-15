# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Live-node slice: a spoke joins as a member and applies a real broadcast.

This is the cross-machine half of the memory-sync loop over real transport. The
node-free tests in ``test_spoke.py`` prove the decode→apply semantics; this one
proves a spoke actually receives traffic it did not emit. Two independent backends
could never do this: each moderates its own MLS group, so nothing crosses. Here one
client moderates and the *other* joins as a member, which is the supported topology.

Needs a running ``slim`` node; skipped without one. Point at a node with
``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``), e.g. via
``mycelium hub host``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("slim_bindings")

from mycelium.filesystem import read_memory, write_memory
from mycelium.slim.client import SlimClient
from mycelium.slim.naming import (
    DEFAULT_NODE_ENDPOINT,
    DEFAULT_WORKSPACE,
    SlimIdentity,
    node_reachable,
    to_channel_name,
    to_slim_name,
)
from mycelium.spoke import SpokeCounters, receive_and_apply

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)
_ROOM = "spoke-live"
_HUB = "backend"
_SPOKE = "spoke"

pytestmark = pytest.mark.skipif(
    not node_reachable(_ENDPOINT),
    reason=f"no reachable SLIM node at {_ENDPOINT} (set MYCELIUM_SLIM_ENDPOINT or run `mycelium hub host`)",
)

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "slim-l9-wire.json"


def _knowledge_frame(*, version: int, content: str) -> tuple[bytes, str]:
    """The wire bytes of a ``knowledge`` broadcast, and the key it writes."""
    with _CONTRACT_PATH.open() as fh:
        envelope: dict[str, Any] = json.load(fh)["knowledge"]["expected_envelope"]
    envelope["payload"]["data"]["version"] = version
    envelope["payload"]["data"]["content"] = content
    return json.dumps({"content": "", "l9": envelope}).encode(), envelope["payload"]["data"]["key"]


async def _hub_and_spoke(
    room_dir: Path, frames: list[bytes], *, counters: SpokeCounters
) -> SpokeCounters:
    """Moderate a channel, invite a spoke, broadcast ``frames``, let the spoke apply."""
    hub = await SlimClient(SlimIdentity(DEFAULT_WORKSPACE, _ROOM, _HUB)).connect(_ENDPOINT)
    spoke = await SlimClient(SlimIdentity(DEFAULT_WORKSPACE, _ROOM, _SPOKE)).connect(_ENDPOINT)
    try:
        session = await hub.create_group(to_channel_name(DEFAULT_WORKSPACE, _ROOM))

        async def spoke_side() -> SpokeCounters:
            joined = await spoke.listen_for_session()
            return await receive_and_apply(
                joined,
                room_dir,
                counters=counters,
                max_messages=len(frames),
                receive_timeout_s=20.0,
            )

        spoke_task = asyncio.create_task(spoke_side())
        try:
            await hub.invite(session, to_slim_name(DEFAULT_WORKSPACE, _ROOM, _SPOKE))
            for frame in frames:
                await SlimClient.publish(session, frame)
            return await asyncio.wait_for(spoke_task, timeout=60.0)
        finally:
            spoke_task.cancel()
    finally:
        await spoke.close()
        await hub.close()


async def test_spoke_applies_a_hub_broadcast_it_did_not_emit(tmp_path: Path) -> None:
    """A hub `memory set` lands in the spoke's own store, over a real channel."""
    frame, key = _knowledge_frame(version=3, content="decided: canary at 10%\n")
    counters = SpokeCounters()

    await _hub_and_spoke(tmp_path, [frame], counters=counters)

    assert (counters.applied, counters.conflicts) == (1, 0)
    stored = read_memory(tmp_path, key)
    assert stored is not None
    meta, body = stored
    assert body == "decided: canary at 10%"
    assert meta["version"] == 3


async def test_redelivery_over_the_wire_is_idempotent(tmp_path: Path) -> None:
    """The same version twice applies once — a replay is a silent no-op."""
    frame, key = _knowledge_frame(version=3, content="decided: canary at 10%\n")
    counters = SpokeCounters()

    await _hub_and_spoke(tmp_path, [frame, frame], counters=counters)

    assert counters.applied == 1
    assert counters.conflicts == 0
    assert counters.ignored == 1
    stored = read_memory(tmp_path, key)
    assert stored is not None
    assert stored[0]["version"] == 3


async def test_stale_base_over_the_wire_is_a_conflict(tmp_path: Path) -> None:
    """A write behind the local version is recorded, not applied over the top."""
    _frame_for_key, key = _knowledge_frame(version=1, content="unused\n")
    write_memory(tmp_path, key, "newer local\n", created_by="local", updated_by="local", version=7)

    stale, _key = _knowledge_frame(version=2, content="stale from the hub\n")
    counters = SpokeCounters()

    await _hub_and_spoke(tmp_path, [stale], counters=counters)

    assert (counters.applied, counters.conflicts) == (0, 1)
    stored = read_memory(tmp_path, key)
    assert stored is not None
    assert stored[1] == "newer local"
