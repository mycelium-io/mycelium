# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A direct memory write records a ``knowledge:extraction`` line in the room.

A ``memory set`` (``POST /rooms/{room}/memory``) writes the file and the index,
then records one message in the room's transcript saying the memory changed:
the line the room's timeline shows for it. It carries the write's key, version,
base version and author in its payload.
"""

import pytest
from httpx import AsyncClient

from app.services import persister


def _memory_lines(room: str) -> list[persister.TranscriptRecord]:
    return [r for r in persister.load_transcript(room) if r.kind == "knowledge"]


def _payload(record: persister.TranscriptRecord) -> dict:
    return record.content["envelope"]["payload"]["data"]


async def _write(client: AsyncClient, room: str, key: str, value: str, who: str):
    resp = await client.post(
        f"/api/rooms/{room}/memory",
        json={"items": [{"key": key, "value": value, "created_by": who, "embed": False}]},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_a_memory_write_records_an_extraction_line(client: AsyncClient):
    room = "timeline-room"
    await client.post("/api/rooms", json={"name": room})

    await _write(client, room, "notes/x", "hello", "alice")

    (line,) = _memory_lines(room)
    assert line.subkind == "extraction"
    assert line.content["content"] == "memory updated → notes/x"
    data = _payload(line)
    assert data["key"] == "notes/x"
    assert data["version"] == 1
    assert data["base_version"] is None
    assert data["created_by"] == "alice" and data["updated_by"] == "alice"


@pytest.mark.asyncio
async def test_an_overwrite_names_the_version_it_replaced(client: AsyncClient):
    room = "timeline-room2"
    await client.post("/api/rooms", json={"name": room})

    await _write(client, room, "k", "v1", "alice")
    await _write(client, room, "k", "v2", "bob")

    first, second = _memory_lines(room)
    assert _payload(first)["version"] == 1
    assert _payload(second)["version"] == 2
    assert _payload(second)["base_version"] == 1
    assert _payload(second)["updated_by"] == "bob"
