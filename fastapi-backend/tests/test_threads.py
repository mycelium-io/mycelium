# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Threads: a conversation scope inside a room, derived from the L9 causal DAG (#631).

Node-free — the transcript is seeded directly, since threading is a projection of
records the wire already carries, not a transport feature.
"""

from __future__ import annotations

import pytest

from app.services import l9, local_state, persister, threads
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content


def _record(
    message_id: str,
    *,
    sender: str = "avery",
    text: str = "hello",
    parents: list[str] | None = None,
    episode: str = "urn:ioc:mycelium:episode:r:live",
    payload_type: str = "message",
    payload_data: dict | None = None,
    recipients: list[str] | None = None,
    at: str = "",
):
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        recipients=recipients or [],
        topic=l9.topic_urn("r"),
        message_id=message_id,
        parents=parents,
        payload_type=payload_type,
        payload_data=payload_data,
    )
    content = serialize_content(env, extra={"content": text})
    return persister.record_from(env, content, now=at or f"2026-08-17T00:00:{message_id[-2:]:0>2}")


# ── derivation ───────────────────────────────────────────────────────────────


def test_a_reply_opens_a_thread_rooted_at_what_it_answers():
    """The DAG is the thread: replying to a room-level message creates the thread
    and folds the answered message in as its root."""
    root = _record("m01", text="what should the cache TTL be?")
    reply = _record("m02", sender="rowan", text="60s", parents=["m01"])

    assigned = threads.thread_map([root, reply])
    assert assigned == {"m01": "m01", "m02": "m01"}


def test_a_thread_carries_through_a_chain_of_replies():
    records = [
        _record("m01"),
        _record("m02", parents=["m01"]),
        _record("m03", parents=["m02"]),
    ]
    assigned = threads.thread_map(records)
    assert set(assigned.values()) == {"m01"}


def test_a_room_level_message_has_no_thread():
    assert threads.thread_map([_record("m01")]) == {}


def test_parallel_exchanges_stay_apart():
    """The tangle this is for: two conversations interleaved in one transcript."""
    records = [
        _record("m01", text="cache TTL?"),
        _record("m02", text="deploy window?"),
        _record("m03", parents=["m01"], text="60s"),
        _record("m04", parents=["m02"], text="thursday"),
    ]
    assigned = threads.thread_map(records)
    assert assigned["m03"] == "m01"
    assert assigned["m04"] == "m02"


def test_an_episode_is_a_typed_thread():
    """A negotiation's turns thread on their episode, not on their causal chain —
    threads generalize episodes rather than sitting beside them."""
    episode = l9.episode_urn("r", "ab12cd34")
    records = [
        _record("m01", episode=episode, payload_type="tick"),
        _record("m02", episode=episode, payload_type="reply", parents=["m01"]),
    ]
    assigned = threads.thread_map(records)
    assert assigned == {"m01": "ab12cd34", "m02": "ab12cd34"}


def test_the_rooms_live_episode_scopes_nothing():
    """``…:live`` is the catch-all every un-negotiated message rides; it is not a
    thread, or the whole room would be one."""
    assert not threads.is_scoped_episode(l9.episode_urn("r", "live"))
    assert threads.thread_map([_record("m01"), _record("m02")]) == {}


def test_an_opener_threads_itself_before_anyone_replies():
    """``thread new`` has no parent to hang off and no reply yet to root it, so the
    root message declares itself one."""
    opener = _record("m01", text="Rollout plan", payload_data={threads.THREAD_ROOT_KEY: True})
    assert threads.thread_map([opener]) == {"m01": "m01"}


def test_naming_an_absent_root_still_threads():
    """A reply may name a thread whose root isn't in this transcript slice; the
    reply still lands in that thread rather than silently going room-level."""
    assert threads.thread_map([_record("m02", parents=["from-elsewhere"])])["m02"] == (
        "from-elsewhere"
    )


def test_presence_traffic_never_opens_a_thread():
    presence = _record("m01", payload_type="presence", text="")
    assert threads.thread_map([presence, _record("m02", parents=["m01"])]) == {
        "m01": "m01",
        "m02": "m01",
    }
    assert threads.thread_map([presence]) == {}


def test_the_index_assigns_incrementally():
    """A long-poll keeps one index warm across iterations instead of re-deriving
    the room every tick."""
    index = threads.ThreadIndex()
    root, reply = _record("m01"), _record("m02", parents=["m01"])
    index.extend([root])
    assert index.thread_of_record(root) is None
    index.extend([root, reply])  # only the tail is processed
    assert index.consumed == 2
    assert index.thread_of_record(reply) == "m01"
    assert index.thread_of("m01") == "m01"  # the root was folded in retroactively


# ── summaries + resolution ───────────────────────────────────────────────────


def _seed(room: str, records: list) -> None:
    get_room_dir(room)
    persister.write_transcript(room, records)


def test_summaries_read_as_conversations():
    room = "threads-summary"
    _seed(
        room,
        [
            _record("m01", sender="avery", text="what should the cache TTL be?\nsecond line"),
            _record("m02", sender="rowan", text="60s", parents=["m01"]),
            _record("m03", sender="avery", text="agreed", parents=["m02"]),
        ],
    )
    (summary,) = threads.room_threads(room)
    assert summary.id == "m01"
    assert summary.kind == "chat"
    assert summary.title == "what should the cache TTL be?"
    assert summary.participants == ["avery", "rowan"]
    assert summary.message_count == 3
    assert summary.root_message_id == "m01"
    assert summary.last_message_id == "m03"


def test_threads_are_listed_most_recently_active_first():
    room = "threads-order"
    _seed(
        room,
        [
            _record("m01", text="older", at="2026-08-17T00:00:01"),
            _record("m02", parents=["m01"], at="2026-08-17T00:00:02"),
            _record("m03", text="newer", at="2026-08-17T00:00:03"),
            _record("m04", parents=["m03"], at="2026-08-17T00:00:04"),
        ],
    )
    assert [t.id for t in threads.room_threads(room)] == ["m03", "m01"]


def test_a_thread_resolves_by_prefix_and_by_episode_urn():
    room = "threads-resolve"
    episode = l9.episode_urn(room, "ab12cd34")
    _seed(
        room,
        [
            _record("aaaa-1111-2222", text="chat root"),
            _record("bbbb", parents=["aaaa-1111-2222"]),
            _record("m03", episode=episode, payload_type="tick"),
        ],
    )

    def _id(ref: str) -> str | None:
        found = threads.resolve(room, ref)
        return found.id if found else None

    assert _id("aaaa") == "aaaa-1111-2222"
    assert _id("aaaa-1111-2222") == "aaaa-1111-2222"
    assert _id(episode) == "ab12cd34"
    assert threads.resolve(room, "nope") is None


def test_an_ambiguous_prefix_is_reported_not_guessed():
    room = "threads-ambiguous"
    _seed(
        room,
        [
            _record("ab-one"),
            _record("x01", parents=["ab-one"]),
            _record("ab-two"),
            _record("x02", parents=["ab-two"]),
        ],
    )
    with pytest.raises(threads.AmbiguousThread) as exc:
        threads.resolve(room, "ab")
    assert sorted(exc.value.matches) == ["ab-one", "ab-two"]


# ── read path ────────────────────────────────────────────────────────────────


def test_the_read_path_stamps_each_message_with_its_thread():
    room = "threads-read"
    _seed(room, [_record("m01"), _record("m02", parents=["m01"]), _record("m03", text="elsewhere")])
    by_id = {m.message_id: m.thread for m in persister.room_conversation(room)}
    assert by_id == {"m01": "m01", "m02": "m01", "m03": None}


def test_a_live_row_keeps_the_thread_the_transcript_gives_it():
    """A message is written to the live store before anything can reply to it, so
    its thread only exists on the transcript — the merge must not lose it."""
    room = "threads-live-merge"
    root = _record("m01")
    _seed(room, [root, _record("m02", parents=["m01"])])
    live_row = persister.stored_message_from_record(room, root)
    assert live_row is not None
    local_state.add_message(room, live_row)

    served = {m.message_id: m.thread for m in persister.room_conversation(room)}
    assert served["m01"] == "m01"


@pytest.mark.asyncio
async def test_listing_filters_by_thread(client):
    room = "threads-filter"
    await client.post("/api/rooms", json={"name": room})
    _seed(
        room,
        [
            _record("m01", text="cache TTL?"),
            _record("m02", parents=["m01"], text="60s"),
            _record("m03", text="unrelated"),
        ],
    )
    scoped = await client.get(f"/api/rooms/{room}/messages", params={"thread": "m01"})
    assert sorted(m["content"] for m in scoped.json()["messages"]) == ["60s", "cache TTL?"]

    whole_room = await client.get(f"/api/rooms/{room}/messages")
    assert whole_room.json()["total"] == 3
    assert {m["content"]: m["thread"] for m in whole_room.json()["messages"]} == {
        "cache TTL?": "m01",
        "60s": "m01",
        "unrelated": None,
    }


@pytest.mark.asyncio
async def test_the_threads_api_lists_and_opens_one_thread(client):
    room = "threads-api"
    await client.post("/api/rooms", json={"name": room})
    _seed(
        room,
        [
            _record("m01", sender="avery", text="cache TTL?"),
            _record("m02", sender="rowan", text="60s", parents=["m01"]),
            _record("m03", text="unrelated"),
        ],
    )
    listing = await client.get(f"/api/rooms/{room}/threads")
    assert [t["id"] for t in listing.json()["threads"]] == ["m01"]

    detail = await client.get(f"/api/rooms/{room}/threads/m0")  # by prefix
    assert detail.status_code == 200
    assert [m["content"] for m in detail.json()["messages"]] == ["cache TTL?", "60s"]
    assert detail.json()["participants"] == ["avery", "rowan"]


@pytest.mark.asyncio
async def test_an_unknown_thread_is_a_404_not_an_empty_room(client):
    room = "threads-404"
    await client.post("/api/rooms", json={"name": room})
    _seed(room, [_record("m01")])
    assert (await client.get(f"/api/rooms/{room}/threads/nope")).status_code == 404
    filtered = await client.get(f"/api/rooms/{room}/messages", params={"thread": "nope"})
    assert filtered.status_code == 404


@pytest.mark.asyncio
async def test_an_ambiguous_prefix_is_a_409_over_http(client):
    room = "threads-409"
    await client.post("/api/rooms", json={"name": room})
    _seed(
        room,
        [
            _record("ab-one"),
            _record("x01", parents=["ab-one"]),
            _record("ab-two"),
            _record("x02", parents=["ab-two"]),
        ],
    )
    resp = await client.get(f"/api/rooms/{room}/threads/ab")
    assert resp.status_code == 409
    assert "ambiguous" in resp.json()["detail"]
