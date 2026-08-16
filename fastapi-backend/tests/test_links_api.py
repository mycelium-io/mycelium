# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The link API, and the memory write path that keeps its index current."""

import pytest

from app.services import links
from app.services.filesystem import get_room_dir, read_memory_file


async def _room(client, name: str = "r") -> None:
    await client.post("/api/rooms", json={"name": name, "created_by": "tester"})


async def _set(client, key: str, value: str, room: str = "r", **extra) -> None:
    item = {"key": key, "value": value, "created_by": "tester", "embed": False, **extra}
    resp = await client.post(f"/api/rooms/{room}/memory", json={"items": [item]})
    assert resp.status_code == 201, resp.text


def _on_disk(key: str, room: str = "r") -> tuple[dict, str]:
    """The memory's frontmatter and body as actually written."""
    stored = read_memory_file(get_room_dir(room), key)
    assert stored is not None, f"{key} not on disk"
    return stored


@pytest.mark.asyncio
async def test_writing_a_memory_indexes_its_links(client):
    await _room(client)
    await _set(client, "context/stack", "The stack.")
    await _set(client, "decisions/db", "Because of [[context/stack]].")

    resp = await client.get("/api/rooms/r/links", params={"key": "decisions/db"})

    assert resp.status_code == 200
    outbound = resp.json()["outbound"]
    assert len(outbound) == 1
    assert outbound[0]["target"] == "context/stack"
    assert outbound[0]["resolved"] is True


@pytest.mark.asyncio
async def test_backlinks_surface_through_the_api(client):
    await _room(client)
    await _set(client, "context/stack", "The stack.")
    await _set(client, "decisions/db", "See [[context/stack]].")

    resp = await client.get("/api/rooms/r/links", params={"key": "context/stack"})

    assert [b["source"] for b in resp.json()["backlinks"]] == ["decisions/db"]


@pytest.mark.asyncio
async def test_deleting_a_memory_drops_its_edges(client):
    await _room(client)
    await _set(client, "context/stack", "The stack.")
    await _set(client, "decisions/db", "See [[context/stack]].")

    await client.delete("/api/rooms/r/memory/decisions/db")
    resp = await client.get("/api/rooms/r/links", params={"key": "context/stack"})

    assert resp.json()["backlinks"] == []


@pytest.mark.asyncio
async def test_meta_writes_frontmatter(client):
    await _room(client)
    await _set(client, "glossary/term", "A definition.", meta={"expandable": True})

    meta, _ = _on_disk("glossary/term")

    assert meta["expandable"] is True


@pytest.mark.asyncio
async def test_frontmatter_survives_a_later_write(client):
    """A content update must not silently drop a page's expandable flag."""
    await _room(client)
    await _set(client, "glossary/term", "A definition.", meta={"expandable": True})
    await _set(client, "glossary/term", "A better definition.")

    meta, body = _on_disk("glossary/term")

    assert meta["expandable"] is True
    assert body == "A better definition."


@pytest.mark.asyncio
async def test_managed_frontmatter_cannot_be_overridden_via_meta(client):
    await _room(client)
    await _set(client, "context/stack", "The stack.", meta={"version": 99, "created_by": "spoof"})

    meta, _ = _on_disk("context/stack")

    assert meta["version"] == 1
    assert meta["created_by"] == "tester"


@pytest.mark.asyncio
async def test_typed_relations_from_meta_become_edges(client):
    await _room(client)
    await _set(client, "decisions/db-v1", "The old call.")
    await _set(client, "decisions/db", "The new call.", meta={"supersedes": "decisions/db-v1"})

    outbound = (await client.get("/api/rooms/r/links", params={"key": "decisions/db"})).json()[
        "outbound"
    ]

    assert outbound[0]["relation"] == "supersedes"
    assert outbound[0]["target"] == "decisions/db-v1"
    assert outbound[0]["resolved"] is True


@pytest.mark.asyncio
async def test_expand_endpoint_renders_transclusions(client):
    await _room(client)
    await _set(client, "glossary/term", "A definition.", meta={"expandable": True})
    await _set(client, "reader", "Recall: ![[glossary/term]]")

    resp = await client.get("/api/rooms/r/links/expand", params={"key": "reader"})

    assert resp.json()["rendered"] == "Recall: A definition."


@pytest.mark.asyncio
async def test_expand_endpoint_404s_on_a_missing_memory(client):
    await _room(client)

    resp = await client.get("/api/rooms/r/links/expand", params={"key": "nope"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_integrity_and_graph_endpoints(client):
    await _room(client)
    await _set(client, "context/stack", "The stack.")
    await _set(client, "decisions/db", "See [[context/stack]] and [[gone]].")

    integrity = (await client.get("/api/rooms/r/links/integrity")).json()
    graph = (await client.get("/api/rooms/r/links/graph")).json()

    assert [b["target"] for b in integrity["broken"]] == ["gone"]
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 2


@pytest.mark.asyncio
async def test_link_endpoints_404_on_an_unknown_room(client):
    resp = await client.get("/api/rooms/nope/links", params={"key": "a"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unlinked_room_reports_a_clean_graph(client):
    await _room(client)
    await _set(client, "context/stack", "Plain prose.")

    assert (await client.get("/api/rooms/r/links/graph")).json()["edges"] == []
    assert links.integrity("r")["broken"] == []
