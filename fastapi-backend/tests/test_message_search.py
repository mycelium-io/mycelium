# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Deep message search: the faceted grammar, and ``GET /rooms/{room}/messages/search``
over a seeded transcript with a task thread in it.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import facet_query, message_format, message_search, persister, tasks
from app.services.filesystem import get_room_dir
from app.services.message_models import Kind
from app.services.message_slim import serialize_content

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
ROOM = "checkout"

# ── the grammar ───────────────────────────────────────────────────────────────


def test_fields_phrases_negation_and_shorthand_split_out_of_the_text():
    q = message_search.parse('@avery to:builder "apple pay" refund -stripe -stance:reject')
    assert q.terms == ("refund",)
    assert q.phrases == ("apple pay",)
    assert q.excluded == ("stripe",)
    assert [(c.field, c.value, c.negate) for c in q.clauses] == [
        ("from", "avery", False),
        ("to", "builder", False),
        ("stance", "reject", True),
    ]


def test_aliases_land_on_the_canonical_field():
    q = message_search.parse("sender:avery row:work/x episode:abc")
    assert [c.field for c in q.clauses] == ["from", "task", "thread"]


def test_time_bounds_read_ages_dates_and_days():
    q = message_search.parse("after:2h before:2026-09-10", now=NOW)
    assert q.after == NOW - timedelta(hours=2)
    assert q.before == datetime(2026, 9, 10, tzinfo=UTC)

    day = message_search.parse("on:2026-09-03", now=NOW)
    assert day.after == datetime(2026, 9, 3, tzinfo=UTC)
    assert day.before == datetime(2026, 9, 4, tzinfo=UTC)

    yesterday = message_search.parse("on:yesterday", now=NOW)
    assert yesterday.after == datetime(2026, 9, 9, tzinfo=UTC)


def test_unreadable_scope_is_reported_not_dropped():
    q = message_search.parse("after:someday sort:loudest hello", now=NOW)
    assert q.problems == ("after:someday", "sort:loudest")
    assert q.after is None
    assert q.sort == "newest"
    assert q.terms == ("hello",)


def test_a_value_outside_a_closed_field_is_a_problem():
    q = message_search.parse("has:linkz in:thread")
    assert q.problems == ("has:linkz",)


def test_a_field_with_no_value_yet_narrows_nothing():
    q = message_search.parse("apple from: task: -stance:")
    assert q.terms == ("apple",)
    assert q.clauses == ()
    assert q.excluded == ()


def test_an_undeclared_prefix_is_free_text():
    q = message_search.parse("https://example.test/a nope:value")
    assert q.clauses == ()
    assert q.terms == ("https://example.test/a", "nope:value")


def test_facet_counts_ignore_their_own_field():
    """After choosing one sender, the sender facet still lists the others."""
    docs = [("a", "x"), ("a", "y"), ("b", "x")]
    fields = [
        facet_query.Field("from", lambda d: [d[0]]),
        facet_query.Field("tag", lambda d: [d[1]]),
    ]
    out = facet_query.run(
        docs,
        facet_query.parse("from:a", ["from", "tag"]),
        fields,
        text=lambda _d: "",
        when=lambda _d: NOW,
    )
    assert len(out.hits) == 2
    assert {b.value: b.count for b in out.facets["from"]} == {"a": 2, "b": 1}
    assert {b.value: b.count for b in out.facets["tag"]} == {"x": 1, "y": 1}


# ── the route ─────────────────────────────────────────────────────────────────


def _say(
    message_id: str,
    *,
    sender: str,
    text: str,
    at: datetime,
    episode: str | None = None,
    recipients: list[str] | None = None,
    stance: str | None = None,
) -> None:
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode or message_format.live_episode_urn(ROOM),
        sender=sender,
        recipients=recipients or [message_format.SYSTEM_ACTOR_ID],
        topic=f"urn:concept:mycelium:{ROOM}",
        message_id=message_id,
        payload_type="reply",
        payload_data={"action": stance} if stance else None,
    )
    record = persister.record_from(
        env, serialize_content(env, extra={"content": text}), now=at.isoformat()
    )
    persister.append_transcript(ROOM, record)


@pytest.fixture
async def seeded(monkeypatch) -> str:
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    get_room_dir(ROOM)
    row = await tasks.create_task(ROOM, "Add Apple Pay", created_by="julia")
    thread = row.model_dump().get("episode") or tasks.episode_of(ROOM, row.key)
    assert thread
    old = datetime.now(UTC) - timedelta(days=3)
    recent = datetime.now(UTC) - timedelta(minutes=30)
    _say("m1", sender="julia", text="@builder can you add Apple Pay?", at=old)
    _say("m2", sender="builder", text="On it, see https://stripe.test", at=old + timedelta(hours=1))
    _say(
        "m3",
        sender="builder",
        text="Wallet button is in, ready for review @reviewer",
        at=recent,
        episode=thread,
        recipients=["reviewer"],
    )
    _say(
        "m4",
        sender="reviewer",
        text="Apple Pay sheet looks right, cc @~builder",
        at=recent + timedelta(minutes=5),
        episode=thread,
        stance="accept",
    )
    return thread


#: Each seeded message by the first word it says.
_BY_WORD = {"@builder": "m1", "On": "m2", "Wallet": "m3", "Apple": "m4"}


def _ids(body: dict) -> list[str]:
    return [_BY_WORD[h["message"]["content"].split()[0]] for h in body["hits"]]


async def _search(client: AsyncClient, q: str, **params) -> dict:
    resp = await client.get(f"/api/rooms/{ROOM}/messages/search", params={"q": q, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_empty_query_reads_the_whole_room_newest_first(client, seeded):
    body = await _search(client, "")
    assert body["total"] == 4
    assert [h["message"]["content"][:6] for h in body["hits"]] == [
        "Apple ",
        "Wallet",
        "On it,",
        "@build",
    ]
    assert {b["value"] for b in body["facets"]["from"]} == {"julia", "builder", "reviewer"}
    assert "from" in body["fields"]


@pytest.mark.asyncio
async def test_words_and_sender_narrow_together(client, seeded):
    body = await _search(client, "apple from:reviewer")
    assert _ids(body) == ["m4"]
    # The sender facet still offers julia, whose message also says apple.
    assert {b["value"]: b["count"] for b in body["facets"]["from"]} == {"julia": 1, "reviewer": 1}


@pytest.mark.asyncio
async def test_task_field_finds_a_thread_by_its_title_and_names_it(client, seeded):
    body = await _search(client, "task:apple")
    assert set(_ids(body)) == {"m3", "m4"}
    hit = body["hits"][0]
    assert hit["task_title"] == "Add Apple Pay"
    assert hit["thread"] == seeded
    assert body["facets"]["task"][0]["label"] == "Add Apple Pay"


@pytest.mark.asyncio
async def test_in_stance_to_mentions_and_has(client, seeded):
    assert _ids(await _search(client, "in:channel")) == [
        "m2",
        "m1",
    ]
    assert _ids(await _search(client, "stance:accept")) == ["m4"]
    assert _ids(await _search(client, "to:reviewer")) == ["m3"]
    assert _ids(await _search(client, "@builder -in:thread")) == ["m2"]
    # A silent `@~builder` names builder too: it is found, though it woke nobody.
    assert _ids(await _search(client, "mentions:builder")) == ["m4", "m1"]
    assert _ids(await _search(client, "has:link")) == ["m2"]


@pytest.mark.asyncio
async def test_time_bounds_and_sort(client, seeded):
    recent = await _search(client, "after:1h sort:oldest")
    assert _ids(recent) == ["m3", "m4"]
    older = await _search(client, "before:1d")
    assert _ids(older) == ["m2", "m1"]


@pytest.mark.asyncio
async def test_cursor_pages_without_repeating(client, seeded):
    first = await _search(client, "", limit=3)
    assert first["next_cursor"]
    second = await _search(client, "", limit=3, cursor=first["next_cursor"])
    ids = [h["message"]["id"] for h in first["hits"] + second["hits"]]
    assert len(ids) == 4
    assert len(set(ids)) == 4
    assert second["next_cursor"] is None


@pytest.mark.asyncio
async def test_context_brings_the_neighbors_from_the_same_thread(client, seeded):
    body = await _search(client, "sheet looks", context=2)
    hit = body["hits"][0]
    assert [m["content"][:6] for m in hit["context_before"]] == ["Wallet"]
    assert hit["context_after"] == []


@pytest.mark.asyncio
async def test_problems_are_echoed(client, seeded):
    body = await _search(client, "on:never apple")
    assert body["scope"]["problems"] == ["on:never"]


# ── the contract ──────────────────────────────────────────────────────────────

_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "message-search.json").read_text()
)


def test_the_grammar_matches_the_frozen_contract():
    assert list(message_search.FIELDS) == _CONTRACT["fields"]
    assert _CONTRACT["aliases"] == message_search.ALIASES
    assert _CONTRACT["time_keys"] == facet_query._TIME_KEYS
    assert list(facet_query.SORTS) == _CONTRACT["sorts"]
    assert {k: list(v) for k, v in message_search.CLOSED_VALUES.items()} == _CONTRACT[
        "closed_values"
    ]
    assert {f.name for f in message_search.fields({})} == set(_CONTRACT["fields"])


@pytest.mark.asyncio
async def test_every_closed_value_is_one_a_message_can_have(client, seeded):
    """A closed value nothing produces would be documented and never match."""
    produced: dict[str, set[str]] = {}
    for spec in message_search.fields({}):
        if spec.name in message_search.CLOSED_VALUES:
            produced[spec.name] = set()
    body = await _search(client, "")
    for name in produced:
        produced[name] = {b["value"] for b in body["facets"].get(name, [])}
    for name, allowed in message_search.CLOSED_VALUES.items():
        assert produced[name] <= set(allowed), name
