# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""L9-over-SLIM round-trip integration test (Step 3 DoD).

Needs a running ``slim`` node. Guarded so the default unit suite stays green
without one (mirrors ``test_slim_roundtrip.py``): point at a node with
``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``); run one via
``mycelium hub host``.

Proves the Step 3 DoD: an L9 ``exchange`` envelope published by one participant
is received and correctly parsed by another over a room channel, and the
envelope (kind/parents/episode) survives the serialize→publish→receive→parse
round trip in causal order.
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
async def test_l9_exchange_round_trip_over_channel():
    """Two causally-linked L9 envelopes arrive, parsed and in causal order."""
    from scripts.l9_slim_roundtrip import _CHILD_ID, _ROOT_ID, run_roundtrip

    received = await run_roundtrip(_ENDPOINT)
    assert len(received) == 2
    root, child = received
    assert root.header.message is not None and child.header.message is not None

    assert [root.header.message.id, child.header.message.id] == [_ROOT_ID, _CHILD_ID]
    # Envelope integrity: kind, episode, and causal parents survive the trip.
    assert root.header.kind.value == "exchange"
    assert child.header.message.parents == [_ROOT_ID]
    assert root.header.message.episode == child.header.message.episode


@pytest.mark.asyncio
async def test_mid_episode_membership_change_aborts_over_slim():
    """A member joining mid-episode aborts it: peers receive commit:rejected."""
    from scripts.l9_slim_roundtrip import run_episode_abort

    abort = await run_episode_abort(_ENDPOINT)

    assert abort.header.kind.value == "commit"
    assert abort.header.subkind == "rejected"
    assert abort.payload.data.get("reason") == "membership_change"


@pytest.mark.asyncio
async def test_durable_inbox_reserves_missed_message_on_reconnect(tmp_path, monkeypatch):
    """Step 4 DoD: an agent offline during a broadcast is re-served it on rejoin.

    agent-a joins, goes offline, misses agent-b's broadcast (SLIM keeps nothing
    for the absent member, §7d), reconnects, and the backend persister re-serves
    exactly the missed message — targeted, in order.
    """
    # Persister writes the transcript to the data dir; isolate it to a temp path.
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    from scripts.l9_slim_roundtrip import _MISSED_ID, run_durable_inbox

    received = await run_durable_inbox(_ENDPOINT)

    ids = [e.header.message.id for e in received if e.header.message is not None]
    assert ids == [_MISSED_ID]
    assert received[0].header.kind.value == "exchange"


@pytest.mark.asyncio
async def test_aligner_observes_and_emits_converged_over_slim(tmp_path, monkeypatch):
    """Step 7 DoD: @-summoning the aligner over a live node makes it observe a
    seeded high-confidence exchange and broadcast commit:converged with metrics."""
    # The engine writes an episode record to the data dir; isolate it.
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    from scripts.l9_slim_roundtrip import run_aligner_observe

    commit = await run_aligner_observe(_ENDPOINT)

    assert commit.header.kind.value == "commit"
    assert commit.header.subkind == "converged"
    metrics = commit.payload.data.get("metrics")
    assert metrics is not None and metrics["mpc"] >= 0.6


@pytest.mark.asyncio
async def test_converged_compiles_plan_and_syncs_memory_over_slim(tmp_path, monkeypatch):
    """Step 8 DoD (same-machine): @-summon the aligner over a seeded exchange →
    it emits commit:converged → the backend compiles plan/tasks.md → a knowledge
    message carries the compiled plan, and applying it to a *second* local store
    writes the markdown and updates that store's JSONL index."""
    from unittest.mock import AsyncMock, patch

    from app.services import memory_sync, plan_compiler, search_index
    from app.services.filesystem import get_room_dir, read_memory_file
    from scripts.l9_slim_roundtrip import _ALIGN_ROOM, run_aligner_converge_and_sync

    store1 = tmp_path / "store1"
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(store1 / ".mycelium"))

    fake_plan = "# Converged Plan\n\n- [ ] ship the thing @agent-a\n- [ ] document it @agent-b"
    with patch.object(plan_compiler, "compile_plan", AsyncMock(return_value=fake_plan)):
        commit, knowledge = await run_aligner_converge_and_sync(_ENDPOINT)

    assert commit.header.subkind == "converged"
    assert memory_sync.is_knowledge(knowledge)

    # First store: the backend compiled plan/tasks.md from the verdict.
    plan1 = read_memory_file(get_room_dir(_ALIGN_ROOM), "plan/tasks")
    assert plan1 is not None and "ship the thing" in plan1[1]

    # Second store: the knowledge push carried the content; apply it there.
    write = memory_sync.knowledge_write_from_envelope(knowledge)
    assert write is not None and write.key == "plan/tasks"
    store2 = tmp_path / "store2"
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(store2 / ".mycelium"))
    result = await memory_sync.apply_knowledge(_ALIGN_ROOM, write)
    assert result.applied

    plan2 = read_memory_file(get_room_dir(_ALIGN_ROOM), "plan/tasks")
    assert plan2 is not None and "ship the thing" in plan2[1]
    assert "plan/tasks" in {r["key"] for r in search_index.load_index(_ALIGN_ROOM)}
