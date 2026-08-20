# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the direct-write → ``knowledge:extraction`` broadcast (#544).

A ``memory set`` (``POST /rooms/{room}/memory``) already writes the file +
index; this is the producer half that mirrors it onto the room channel so
other members' stores converge — the same wire shape ``plan_sync`` uses for
the compiled plan, but tagged ``extraction`` (a raw write) instead of
``distillation`` (converged content). The broadcast is scheduled as a
fire-and-forget background task, so tests drain ``memory_route._broadcast_tasks``
before asserting on what was sent.
"""

import asyncio
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.routes import memory as memory_route
from app.services import memory_sync, room_channels
from tests.fakes import FakeChannel, FakeManaged, FakePersister


async def _drain_broadcasts() -> None:
    """Await in-flight broadcasts and let done-callbacks run."""
    tasks = list(memory_route._broadcast_tasks)
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_memory_write_broadcasts_extraction_knowledge(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "bcast-room"})

    channel = FakeChannel()
    persister = FakePersister()
    managed = FakeManaged(room="bcast-room", channel=channel, persister=persister)

    with (
        patch.object(room_channels.manager, "get", return_value=managed),
        patch.object(room_channels.manager, "members", return_value=["a", "b"]),
    ):
        resp = await client.post(
            "/api/rooms/bcast-room/memory",
            json={
                "items": [
                    {"key": "notes/x", "value": "hello", "created_by": "alice", "embed": False}
                ]
            },
        )
        assert resp.status_code == 201
        await _drain_broadcasts()

    assert len(channel.sent) == 1
    envelope, _extra = channel.sent[0]
    assert envelope.header.kind.value == "knowledge"
    assert envelope.header.subkind == memory_sync.MEMORY_WRITE_SUBKIND
    assert envelope.header.subkind != memory_sync.KNOWLEDGE_SUBKIND

    write = memory_sync.knowledge_write_from_envelope(envelope)
    assert write is not None
    assert write.key == "notes/x"
    assert write.version == 1
    assert write.base_version is None
    assert write.created_by == "alice" and write.updated_by == "alice"

    # ingest_local recorded it too, so the transcript/UI bus see it even if
    # SLIM never loops the broadcast back to the moderator.
    assert len(persister.ingested) == 1


@pytest.mark.asyncio
async def test_memory_write_broadcast_threads_base_version_on_upsert(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "bcast-room2"})

    channel = FakeChannel()
    managed = FakeManaged(room="bcast-room2", channel=channel, persister=None)

    with (
        patch.object(room_channels.manager, "get", return_value=managed),
        patch.object(room_channels.manager, "members", return_value=["a"]),
    ):
        await client.post(
            "/api/rooms/bcast-room2/memory",
            json={"items": [{"key": "k", "value": "v1", "created_by": "alice", "embed": False}]},
        )
        await _drain_broadcasts()
        await client.post(
            "/api/rooms/bcast-room2/memory",
            json={"items": [{"key": "k", "value": "v2", "created_by": "bob", "embed": False}]},
        )
        await _drain_broadcasts()

    assert len(channel.sent) == 2
    second = memory_sync.knowledge_write_from_envelope(channel.sent[1][0])
    assert second is not None
    assert second.version == 2
    assert second.base_version == 1
    assert second.updated_by == "bob"


@pytest.mark.asyncio
async def test_memory_write_skips_broadcast_without_live_channel(client: AsyncClient):
    """No provisioned/live channel (e.g. a not-yet-shared room): silent no-op."""
    await client.post("/api/rooms", json={"name": "local-only-room"})

    with patch.object(room_channels.manager, "get", return_value=None):
        resp = await client.post(
            "/api/rooms/local-only-room/memory",
            json={"items": [{"key": "k", "value": "v", "created_by": "alice", "embed": False}]},
        )
        assert resp.status_code == 201
        await _drain_broadcasts()

    assert memory_route._broadcast_tasks == set()
