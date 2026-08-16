# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Tests for command-style cross-entity search.

Two halves: the query grammar (``search_query``) as pure parsing, and the
ranked fan-out (``search`` + ``GET /api/search``) over a seeded room.
"""

import pytest
from httpx import AsyncClient

from app.services import search, search_query
from app.services.search_query import ParsedQuery

# ── the grammar ───────────────────────────────────────────────────────────────


def test_parses_scope_tokens_out_of_the_free_text():
    q = search_query.parse("#atlas @avery memory: postgres pooling")
    assert q.rooms == ("atlas",)
    assert q.actors == ("avery",)
    assert q.types == ("memory",)
    assert q.text == "postgres pooling"


def test_type_token_narrows_while_it_is_still_being_typed():
    """`memory:postg` is a half-typed query, not a miss — the tail is free text."""
    q = search_query.parse("memory:postg")
    assert q.types == ("memory",)
    assert q.text == "postg"


def test_plural_and_short_type_spellings_are_the_same_filter():
    for token in ("memory:", "memories:", "mem:"):
        assert search_query.parse(token).types == ("memory",)
    assert search_query.parse("msg:").types == ("message",)


def test_kind_token_is_a_value_filter_not_a_type():
    q = search_query.parse("kind:converged")
    assert q.kinds == ("converged",)
    assert q.types == ()
    assert q.text == ""


def test_unknown_prefix_stays_free_text():
    """A memory key or a URL has a colon in it and must survive the parse."""
    q = search_query.parse("log/episodes/a1b2 https://example.test")
    assert q.types == ()
    assert q.text == "log/episodes/a1b2 https://example.test"


def test_repeated_token_is_deduped_not_weighted():
    assert search_query.parse("#atlas #atlas #ops").rooms == ("atlas", "ops")


def test_empty_query_is_empty():
    assert search_query.parse("   ").is_empty
    assert not search_query.parse("#atlas").is_empty


# ── scoring ───────────────────────────────────────────────────────────────────


def test_an_exact_label_outscores_a_partial_one_which_outscores_a_body_mention():
    exact = search.lexical_score(["planner"], "planner", "")
    partial = search.lexical_score(["planner"], "planner-two", "")
    body = search.lexical_score(["planner"], "avery", "ask the planner")
    assert exact > partial > body > 0


def test_every_term_must_land_for_a_full_score():
    """A two-word query is not satisfied by a document carrying one of the words."""
    both = search.lexical_score(["postgres", "pooling"], "postgres-pooling", "")
    one = search.lexical_score(["postgres", "pooling"], "postgres-only", "")
    assert one == pytest.approx(both / 2)


def test_a_semantic_only_hit_never_outranks_an_exact_name():
    assert search.semantic_score(1.0) < search.lexical_score(["x"], "x", "")


def test_cosine_noise_scores_nothing():
    assert search.semantic_score(search.SEMANTIC_FLOOR) == 0.0
    assert search.semantic_score(0.1) == 0.0


# ── the fan-out ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Deterministic stub embeddings so search runs without the ONNX model."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


async def _seed_room(client: AsyncClient, name: str) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201), resp.text


async def _seed_memory(client: AsyncClient, room: str, key: str, text: str) -> None:
    resp = await client.post(
        f"/api/rooms/{room}/memory",
        json={"items": [{"key": key, "value": {"text": text}, "created_by": "avery"}]},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_finds_a_memory_by_its_key_across_every_room(client):
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "decisions/postgres-pooling", "pgbouncer in front")

    resp = await client.get("/api/search", params={"q": "pooling"})
    assert resp.status_code == 200
    hits = resp.json()["results"]
    memory = next(h for h in hits if h["type"] == "memory")
    assert memory["id"] == "decisions/postgres-pooling"
    assert memory["room"] == "atlas"


@pytest.mark.asyncio
async def test_room_scope_excludes_every_other_room(client):
    await _seed_room(client, "atlas")
    await _seed_room(client, "ops")
    await _seed_memory(client, "atlas", "decisions/pooling", "pgbouncer")
    await _seed_memory(client, "ops", "decisions/pooling", "pgbouncer")

    resp = await client.get("/api/search", params={"q": "#ops pooling"})
    rooms = {h["room"] for h in resp.json()["results"]}
    assert rooms == {"ops"}


@pytest.mark.asyncio
async def test_type_token_keeps_only_that_type(client):
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "decisions/atlas-plan", "the atlas plan")

    resp = await client.get("/api/search", params={"q": "memory: atlas"})
    types = {h["type"] for h in resp.json()["results"]}
    assert types == {"memory"}


@pytest.mark.asyncio
async def test_a_room_is_findable_by_name(client):
    await _seed_room(client, "atlas-migration")

    resp = await client.get("/api/search", params={"q": "atlas"})
    hit = next(h for h in resp.json()["results"] if h["type"] == "room")
    assert hit["id"] == "atlas-migration"


@pytest.mark.asyncio
async def test_an_agent_is_findable_by_handle(client):
    await _seed_room(client, "atlas")
    resp = await client.post(
        "/api/rooms/atlas/engines",
        json={"handle": "aligner", "kind": "aligner", "created_by": "avery"},
    )
    assert resp.status_code in (200, 201), resp.text

    resp = await client.get("/api/search", params={"q": "aligner"})
    hit = next(h for h in resp.json()["results"] if h["type"] == "agent")
    assert hit["id"] == "aligner"
    assert hit["room"] == "atlas"


@pytest.mark.asyncio
async def test_a_message_is_findable_by_its_text(client):
    await _seed_room(client, "atlas")
    resp = await client.post(
        "/api/rooms/atlas/messages",
        json={
            "sender_handle": "avery",
            "message_type": "broadcast",
            "content": "I think pgbouncer is the answer",
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get("/api/search", params={"q": "pgbouncer"})
    hit = next(h for h in resp.json()["results"] if h["type"] == "message")
    assert "pgbouncer" in hit["snippet"]
    assert hit["subtitle"].endswith("@avery")


@pytest.mark.asyncio
async def test_actor_scope_keeps_only_that_actor(client):
    await _seed_room(client, "atlas")
    for sender in ("avery", "jordan"):
        resp = await client.post(
            "/api/rooms/atlas/messages",
            json={
                "sender_handle": sender,
                "message_type": "broadcast",
                "content": "pgbouncer please",
            },
        )
        assert resp.status_code == 201, resp.text

    resp = await client.get("/api/search", params={"q": "@jordan message: pgbouncer"})
    senders = {h["subtitle"] for h in resp.json()["results"]}
    assert senders == {"atlas · @jordan"}


@pytest.mark.asyncio
async def test_a_pure_scope_query_browses_newest_first(client):
    """`#atlas memory:` has nothing to rank by, so it lists the room's recent memories."""
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "context/first", "one")
    await _seed_memory(client, "atlas", "context/second", "two")

    resp = await client.get("/api/search", params={"q": "#atlas memory:"})
    keys = [h["id"] for h in resp.json()["results"]]
    assert keys[0] == "context/second"
    assert set(keys) == {"context/first", "context/second"}


@pytest.mark.asyncio
async def test_the_scope_is_echoed_back(client):
    resp = await client.get("/api/search", params={"q": "#atlas @avery kind:converged plan"})
    scope = resp.json()["scope"]
    assert scope == {
        "text": "plan",
        "rooms": ["atlas"],
        "actors": ["avery"],
        "types": [],
        "kinds": ["converged"],
    }


@pytest.mark.asyncio
async def test_an_empty_query_returns_nothing_rather_than_erroring(client):
    resp = await client.get("/api/search", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_counts_report_matches_beyond_the_trimmed_list(client):
    await _seed_room(client, "atlas")
    for i in range(4):
        await _seed_memory(client, "atlas", f"context/note-{i}", "shared body text")

    resp = await client.get("/api/search", params={"q": "memory: context", "limit": 2})
    body = resp.json()
    assert len(body["results"]) == 2
    assert body["counts"]["memory"] == 4


@pytest.mark.asyncio
async def test_a_room_named_by_scope_that_does_not_exist_searches_nothing(client):
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "decisions/pooling", "pgbouncer")

    resp = await client.get("/api/search", params={"q": "#nowhere pooling"})
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_the_index_cache_sees_a_later_write(client):
    """The read cache is stamped by the index file, so a write is not missed."""
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "context/before", "first")
    await client.get("/api/search", params={"q": "context"})

    await _seed_memory(client, "atlas", "context/after", "second")
    resp = await client.get("/api/search", params={"q": "memory: context"})
    assert {h["id"] for h in resp.json()["results"]} == {"context/before", "context/after"}


def test_type_priors_only_break_ties():
    """No prior is large enough to lift a weak match over a decisively better one."""
    assert (
        max(search.TYPE_PRIOR.values()) < search.lexical_score(["x"], "x", "") - search.BROWSE_SCORE
    )


@pytest.mark.asyncio
async def test_search_is_scoped_to_the_requested_types_only(client):
    """A type filter must not merely reorder: the other fan-outs never run."""
    await _seed_room(client, "atlas")
    parsed = ParsedQuery(text="atlas", types=("room",))
    result = await search.search(parsed)
    assert set(result.counts) == {"room"}


@pytest.mark.asyncio
async def test_a_kind_filter_reads_a_memory_namespace_and_drops_the_kindless(client):
    """`kind:` fails closed — a room has no kind, so it is not "every kind"."""
    await _seed_room(client, "atlas")
    await _seed_memory(client, "atlas", "decisions/pooling", "pgbouncer")
    await _seed_memory(client, "atlas", "context/pooling", "background")

    resp = await client.get("/api/search", params={"q": "kind:decisions atlas pooling"})
    results = resp.json()["results"]
    assert [h["id"] for h in results] == ["decisions/pooling"]
