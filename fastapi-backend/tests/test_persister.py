# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the backend persister / durable inbox (app/services/persister.py).

Node-free: they exercise the delivery cursor, transcript persistence, and the
trigger detection as pure logic over built envelopes. The live durable-inbox
round trip over a real SLIM node is in ``test_l9_over_slim_roundtrip.py``
(guarded on a running node).
"""

import pytest

from app.services import l9, memory_sync, persister
from app.services.filesystem import get_room_dir, read_memory_file
from app.services.l9_models import Kind


def _exchange(message_id: str, *, sender: str = "agent-a", text: str | None = None):
    """A minimal exchange envelope (optionally naming a human-facing text)."""
    return l9.build_envelope(
        kind=Kind.exchange,
        episode="urn:ioc:mycelium:episode:r:s",
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic="urn:concept:mycelium:r",
        message_id=message_id,
        payload_type="reply",
        payload_data={"action": "offer", **({"text": text} if text is not None else {})},
    )


def _record(
    message_id: str, *, sender: str = "agent-a", text: str = ""
) -> persister.TranscriptRecord:
    env = _exchange(message_id, sender=sender, text=text or None)
    from app.services.l9_slim import serialize_content

    return persister.record_from(
        env, serialize_content(env, extra={"text": text} if text else None)
    )


# ── delivery cursor ──────────────────────────────────────────────────────────


def test_cursor_advances_for_present_members_and_stays_empty_when_caught_up():
    log = persister.DeliveryLog()
    log.track("agent-a", caught_up=True)

    log.record(_record("m1"), delivered_to={"agent-a"})
    assert log.undelivered("agent-a") == []  # got it live → caught up


def test_cursor_yields_exactly_the_missed_tail_for_an_offline_agent():
    log = persister.DeliveryLog()
    log.track("agent-a", caught_up=True)

    # agent-a present for m1, then offline for m2 and m3.
    log.record(_record("m1"), delivered_to={"agent-a"})
    log.record(_record("m2"), delivered_to={"agent-b"})
    log.record(_record("m3"), delivered_to={"agent-b"})

    tail = log.undelivered("agent-a")
    assert [r.message_id for r in tail] == ["m2", "m3"]

    # After re-serve it is caught up again.
    log.mark_caught_up("agent-a")
    assert log.undelivered("agent-a") == []


def test_fresh_join_is_caught_up_and_misses_nothing_prior():
    log = persister.DeliveryLog()
    log.record(_record("m1"), delivered_to=set())  # happened before agent-a joined
    assert not log.knows("agent-a")

    log.track("agent-a", caught_up=True)  # a first join
    assert log.undelivered("agent-a") == []  # missed nothing that preceded it

    log.record(_record("m2"), delivered_to={"agent-b"})  # now offline
    assert [r.message_id for r in log.undelivered("agent-a")] == ["m2"]


# ── transcript persistence ───────────────────────────────────────────────────


def test_transcript_persists_in_order_and_survives_reload():
    room = "persist-room"
    get_room_dir(room)  # ensure the room dir exists
    records = [_record("m1", text="first"), _record("m2", text="second")]
    persister.write_transcript(room, records)

    reloaded = persister.load_transcript(room)
    assert [r.message_id for r in reloaded] == ["m1", "m2"]
    assert reloaded[0].content["text"] == "first"
    assert reloaded[1].sender == "agent-a"


def test_append_transcript_is_o1_and_accumulates():
    """Appending records one at a time yields the same ordered history a
    full rewrite would, without re-rendering the whole file."""
    room = "append-room"
    base = get_room_dir(room)
    for mid in ("m1", "m2", "m3"):
        persister.append_transcript(room, _record(mid))

    reloaded = persister.load_transcript(room)
    assert [r.message_id for r in reloaded] == ["m1", "m2", "m3"]
    # Plain JSONL on disk: one JSON object per line, no markdown fence.
    body = (base / persister.TRANSCRIPT_FILENAME).read_text(encoding="utf-8")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 3
    assert "```" not in body


# ── delivery-cursor persistence (D5) ─────────────────────────────────────────


def test_cursors_round_trip_and_missing_file_is_empty():
    room = "cursor-rt-room"
    get_room_dir(room)
    persister.write_cursors(room, {"agent-a": 2, "agent-b": 0})
    assert persister.load_cursors(room) == {"agent-a": 2, "agent-b": 0}
    # A room that never persisted cursors reads back empty, not an error.
    assert persister.load_cursors("no-such-cursor-room") == {}


def test_cursors_survive_a_restart_so_an_offline_tail_is_still_reserved():
    """The D5 fix: an agent offline at shutdown must still be recognized as a
    reconnect and re-served exactly its missed tail after a backend restart.

    Cursors persist alongside the transcript, so a reconnecting agent re-serves
    its missed tail after a backend restart.
    """
    room = "cursor-restart-room"
    get_room_dir(room)

    log = persister.DeliveryLog()
    log.track("agent-a", caught_up=True)
    log.record(_record("m1"), delivered_to={"agent-a"})  # present
    log.record(_record("m2"), delivered_to={"agent-b"})  # agent-a offline
    log.record(_record("m3"), delivered_to={"agent-b"})
    # What the persister writes on each record: transcript + cursors together.
    persister.write_transcript(room, log.records)
    persister.write_cursors(room, log.cursors)

    # Rebuild purely from disk — the restart.
    resumed = persister.DeliveryLog(
        persister.load_transcript(room), cursors=persister.load_cursors(room)
    )
    assert resumed.knows("agent-a")  # a reconnect, not a fresh join
    assert [r.message_id for r in resumed.undelivered("agent-a")] == ["m2", "m3"]


def test_classify_receive_error_separates_churn_from_genuine_faults():
    """Membership churn (a member leaving, a session re-keyed on a join) must be
    classified apart from a real transport fault, so it doesn't spend the fatal
    give-up budget and zombie the room under rapid invite/remove churn."""
    classify = persister._classify_receive_error
    assert (
        classify(Exception("participant disconnected: acme/room/agent-a/inst"))
        == "participant_left"
    )
    assert classify(Exception("SessionError: session closed")) == "transient"
    assert classify(Exception("Session not found for 42")) == "transient"
    assert classify(Exception("no active session")) == "transient"
    # A genuine fault must remain fatal so a truly dead channel still gives up fast.
    assert classify(Exception("connection reset by peer")) == "fatal"
    assert classify(Exception("some unrecognized transport error")) == "fatal"


def test_loaded_cursors_are_clamped_to_the_transcript_length():
    """A cursor file that drifted from the transcript (one write landed across a
    crash, the other didn't) must never index out of bounds."""
    log = persister.DeliveryLog([_record("m1")], cursors={"ahead": 5, "behind": -2})
    assert log.undelivered("ahead") == []  # clamped to end → re-serves nothing
    assert [r.message_id for r in log.undelivered("behind")] == ["m1"]  # clamped to 0


def test_position_of_an_untracked_handle_is_the_transcript_end():
    """A handle no one has addressed sits at "now": nothing prior is its business."""
    log = persister.DeliveryLog([_record("m1"), _record("m2")])
    assert log.position("stranger") == 2


def test_position_of_an_addressed_untracked_handle_is_its_anchor():
    """The mention that summoned an absent handle anchors its cursor at itself, so
    ``position`` reports the mention — not the end — for its first await."""
    log = persister.DeliveryLog()
    log.record(_record("m0", sender="avery"), delivered_to=set(), recipients=[])
    log.record(_record("m1", sender="avery"), delivered_to=set(), recipients=["agent-x"])
    assert log.position("agent-x") == 1  # anchored at the mention, not the end (2)


def test_advance_moves_the_cursor_forward_and_registers_a_new_handle():
    log = persister.DeliveryLog([_record("m1"), _record("m2"), _record("m3")])
    log.advance("agent-x", 2)
    assert log.knows("agent-x")
    assert [r.message_id for r in log.undelivered("agent-x")] == ["m3"]


def test_advance_never_rewinds_a_cursor():
    """A drain can't un-deliver a tail an earlier live send already advanced past."""
    log = persister.DeliveryLog([_record("m1"), _record("m2"), _record("m3")])
    log.advance("agent-x", 3)
    log.advance("agent-x", 1)  # a stale/lower position is ignored
    assert log.position("agent-x") == 3


def test_advance_clamps_beyond_the_transcript_end():
    log = persister.DeliveryLog([_record("m1")])
    log.advance("agent-x", 99)
    assert log.position("agent-x") == 1


def test_an_await_advanced_cursor_survives_a_restart(tmp_path, monkeypatch):
    """The consume side of the durable inbox persists: a message drained by an
    ``await`` on one process is not re-served after a restart (#649)."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    room = "await-restart"
    records = [_record("m1"), _record("m2")]
    for r in records:
        persister.append_transcript(room, r)

    log = persister.DeliveryLog(records, cursors=persister.load_cursors(room))
    log.advance("agent-x", 2)  # await drained both
    persister.write_cursors(room, log.cursors)

    resumed = persister.DeliveryLog(
        persister.load_transcript(room), cursors=persister.load_cursors(room)
    )
    assert resumed.undelivered("agent-x") == []  # not re-served after the "restart"
    assert resumed.position("agent-x") == 2


def test_transcript_does_not_clobber_episode_records():
    """The transcript is a distinct file from log/episodes/*."""
    room = "coexist-room"
    base = get_room_dir(room)
    # Seed an episode record where l9_episode would write one.
    from app.services.filesystem import write_memory_file

    write_memory_file(base, "log/episodes/abcd1234", "# Episode\n", created_by="x")

    persister.write_transcript(room, [_record("m1")])

    # Both survive independently.
    assert read_memory_file(base, "log/episodes/abcd1234") is not None
    assert (base / persister.TRANSCRIPT_FILENAME).exists()
    assert (base / "log" / "episodes" / "abcd1234.md").exists()


# ── trigger-watcher ──────────────────────────────────────────────────────────


def test_summon_token_is_recognized_in_content():
    content = {"text": "hey @aligner can you check this?", "l9": {"ignored": "@notme"}}
    assert persister.find_summons(content) == ["aligner"]


def test_plain_message_has_no_summons():
    assert persister.find_summons({"text": "just chatting, no mentions"}) == []
    # An @ inside the l9 envelope key is never treated as a summon.
    assert persister.find_summons({"l9": {"note": "@ghost"}}) == []


def test_multiple_summons_deduped_in_order():
    content = {"text": "@a and @b and @a again", "extra": ["also @c"]}
    assert persister.find_summons(content) == ["a", "b", "c"]


# ── plan-compile hook ────────────────────────────────────────────────────────


def test_is_converged_true_only_for_commit_converged():
    converged = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode="urn:ioc:mycelium:episode:r:s",
        payload_type="consensus",
        payload_data={},
    )
    rejected = l9.build_envelope(
        kind=Kind.commit,
        subkind="rejected",
        episode="urn:ioc:mycelium:episode:r:s",
        payload_type="consensus",
        payload_data={},
    )
    assert persister.is_converged(converged) is True
    assert persister.is_converged(rejected) is False
    assert persister.is_converged(_exchange("m1")) is False


# ── ingest wiring: triggers fire off recorded messages ───────────────────────


def _persister_for(room: str, *, summoned: list, converged: list) -> persister.RoomPersister:
    """A persister with no live channel, hooks capturing into the given lists."""
    return persister.RoomPersister(
        room,
        channel=None,  # ty: ignore[invalid-argument-type]  # not exercised: we call _ingest directly
        members_provider=lambda: set(),
        on_summon=lambda handle, env, co, msg="": summoned.append(handle),
        on_converged=lambda env: converged.append(env),
        feed_bus=False,
    )


def test_ingest_fires_summon_hook_but_not_on_plain_message():
    summoned: list[str] = []
    converged: list = []
    p = _persister_for("ingest-room", summoned=summoned, converged=converged)

    from app.services.l9_slim import serialize_content

    env = _exchange("m1", text="ping @aligner")
    p._ingest(env, serialize_content(env, extra={"text": "ping @aligner"}))
    assert summoned == ["aligner"]
    assert converged == []

    plain = _exchange("m2", text="no mention here")
    p._ingest(plain, serialize_content(plain, extra={"text": "no mention here"}))
    assert summoned == ["aligner"]  # unchanged


def test_ingest_skips_keepalive_from_the_transcript():
    """A connector's idle keepalive ping exists only to reset SLIM liveness — it
    must never be recorded to the durable transcript (else the log fills with a
    ping every ~20s per member). A real reply still records."""
    p = _persister_for("keepalive-room", summoned=[], converged=[])

    ping_env, ping_content = _msg_content("k-1", sender="growth", text="", payload_type="keepalive")
    p._ingest(ping_env, ping_content)
    assert p.log.records == []  # keepalive dropped, nothing recorded

    reply_env, reply_content = _msg_content("r-1", sender="growth", text="hi", payload_type="reply")
    p._ingest(reply_env, reply_content)
    assert len(p.log.records) == 1  # a real message still records


def test_ingest_fires_converged_hook_for_commit_converged_only():
    summoned: list[str] = []
    converged: list = []
    p = _persister_for("ingest-room-2", summoned=summoned, converged=converged)

    from app.services.l9_slim import serialize_content

    conv = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode="urn:ioc:mycelium:episode:r:s",
        message_id="c1",
        payload_type="consensus",
        payload_data={},
    )
    p._ingest(conv, serialize_content(conv))
    assert len(converged) == 1

    other = _exchange("m3", text="just talking")
    p._ingest(other, serialize_content(other))
    assert len(converged) == 1  # unchanged


@pytest.mark.asyncio
async def test_reserve_without_context_is_a_noop():
    """No cached reply context (agent never spoke) → nothing to route to."""
    p = _persister_for("reserve-room", summoned=[], converged=[])
    p.log.track("agent-a", caught_up=True)
    from app.services.l9_slim import serialize_content

    env = _exchange("m1")
    p.log.record(persister.record_from(env, serialize_content(env)), delivered_to=set())
    # agent-a missed m1 but we have no context for it → 0 re-served, no raise.
    assert await p.reserve("agent-a") == 0
    # The skipped first-wake re-serve is now visible on the health surface.
    assert p.reserve_skipped == 1
    assert p.reserves == 0


@pytest.mark.asyncio
async def test_reserve_failure_is_counted_for_the_health_surface():
    """A re-serve that has a route but fails to send is a lost delivery — counted
    as reserve_failures, not silently swallowed."""

    class _DeadChannel:
        async def send_content_to(self, _context, _content):
            raise RuntimeError("point-to-point send failed")

    p = persister.RoomPersister(
        "reserve-fail-room",
        _DeadChannel(),  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        feed_bus=False,
    )
    from app.services.l9_slim import serialize_content

    p.log.track("agent-a", caught_up=True)
    env = _exchange("m1")
    p.log.record(persister.record_from(env, serialize_content(env)), delivered_to=set())
    # a route exists, but the send will fail (a stand-in context, not a real one)
    p._contexts["agent-a"] = object()  # ty: ignore[invalid-assignment]
    assert await p.reserve("agent-a") == 0
    assert p.reserve_failures == 1
    assert p.reserves == 0


@pytest.mark.asyncio
async def test_transient_churn_is_counted_apart_from_fatal_faults():
    """Recoverable session churn increments transient_errors (retried, not lost)
    and never spends the fatal receive_errors budget."""

    class _ChurningChannel:
        def __init__(self):
            self.calls = 0

        async def receive_with_context(self):
            self.calls += 1
            if self.calls > 3:
                raise __import__("asyncio").CancelledError
            raise RuntimeError("SessionError: session closed")

    p = persister.RoomPersister(
        "churn-room",
        _ChurningChannel(),  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        feed_bus=False,
    )
    with pytest.raises(__import__("asyncio").CancelledError):
        await p.run()
    assert p.transient_errors == 3
    assert p.receive_errors == 0  # churn never counts as a fatal fault


# ── H2 list-store invariant: one store, source-partitioned producers ──────────


def _msg_content(message_id: str, *, sender: str, text: str, payload_type: str):
    """An envelope + serialized content with a top-level human-facing ``content``."""
    from app.services.l9_slim import serialize_content

    env = l9.build_envelope(
        kind=Kind.exchange,
        episode="urn:ioc:mycelium:episode:r:s",
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic="urn:concept:mycelium:r",
        message_id=message_id,
        payload_type=payload_type,
    )
    return env, serialize_content(env, extra={"content": text})


def test_list_store_human_and_agent_each_appear_once_in_order():
    """The H2 invariant: a human message and an agent reply each land in the list
    store exactly once, in order — the source partition (POST writes the human's,
    the persister writes SLIM arrivals) + id-dedup hold, so nothing double-writes.
    """
    from app.services import in_memory_store

    room = "h2-invariant-room"
    p = _persister_for(room, summoned=[], converged=[])

    # 1) The human's message: written by the POST route (its own producer, stamped
    #    with the envelope id), and ingested by the persister with list_write=False
    #    so it is NOT double-written to the list store.
    human_env, human_content = _msg_content(
        "h-1", sender="avery", text="@smoke-agent hello", payload_type="message"
    )
    in_memory_store.add_message(
        room,
        in_memory_store.StoredMessage(
            room_name=room,
            sender_handle="avery",
            message_type="broadcast",
            content="hello",
            message_id="h-1",
        ),
    )
    p._ingest(human_env, human_content, list_write=False)
    # Its SLIM loopback arrives on the receive path — de-duped by id, no re-write.
    p._ingest(human_env, human_content)

    # 2) The agent's reply: arrives only over SLIM (receive path) → the persister
    #    is its sole producer.
    agent_env, agent_content = _msg_content(
        "a-1", sender="smoke-agent", text="hi back", payload_type="reply"
    )
    p._ingest(agent_env, agent_content)

    stored = in_memory_store.list_messages(room)
    assert [(m.sender_handle, m.content) for m in stored] == [
        ("avery", "hello"),
        ("smoke-agent", "hi back"),
    ]


def test_list_store_message_carries_its_episode():
    """Rung 2: a message lands in the list store tagged with the L9 episode it rode,
    so the UI can group/fold a negotiation's turns by episode (and the messages
    route can filter by it)."""
    from app.services import in_memory_store

    room = "episode-tag-room"
    p = _persister_for(room, summoned=[], converged=[])

    env, content = _msg_content("a-1", sender="growth", text="my position", payload_type="reply")
    p._ingest(env, content)

    stored = in_memory_store.list_messages(room)
    assert len(stored) == 1
    assert stored[0].episode == "urn:ioc:mycelium:episode:r:s"


def test_conversational_messages_project_from_the_durable_transcript():
    """The read path's source of truth: chat records project out of the transcript
    with their envelope id (correlation key) and episode; presence/control records
    are skipped."""
    room = "conv-projection-room"
    get_room_dir(room)

    for mid, sender, ptype in [
        ("h-1", "avery", "message"),
        ("a-1", "growth", "reply"),
        ("p-1", "growth", "presence"),
    ]:
        env, content = _msg_content(
            mid, sender=sender, text=f"{sender} says hi", payload_type=ptype
        )
        persister.append_transcript(room, persister.record_from(env, content))

    projected = persister.conversational_messages(room)
    assert [(m.sender_handle, m.message_id) for m in projected] == [
        ("avery", "h-1"),
        ("growth", "a-1"),
    ]
    assert projected[1].episode == "urn:ioc:mycelium:episode:r:s"


def test_conversational_messages_survive_a_wiped_in_memory_store():
    """The restart bug (issue #497 §3): the in-memory list store is empty after a
    restart, but the durable transcript still projects the full history — so the
    read path serves it regardless."""
    from app.services import in_memory_store

    room = "conv-restart-room"
    get_room_dir(room)
    env, content = _msg_content("a-1", sender="growth", text="my position", payload_type="reply")
    persister.append_transcript(room, persister.record_from(env, content))

    in_memory_store.clear_all()  # the restart: memory is gone, disk is not
    projected = persister.conversational_messages(room)
    assert [m.content for m in projected] == ["my position"]


def test_conversational_projection_is_stable_and_dedups_against_the_list_store():
    """The same message projected from disk carries the same synthetic id on every
    read (so a UI keyed by id is stable), and shares its ``message_id`` with the
    list-store row the persister wrote — the key the read path dedups on."""
    from app.services import in_memory_store

    room = "conv-dedup-room"
    p = _persister_for(room, summoned=[], converged=[])
    env, content = _msg_content("a-1", sender="growth", text="hello", payload_type="reply")
    p._ingest(env, content)  # writes both the transcript and the list store

    disk = persister.conversational_messages(room)
    assert persister.conversational_messages(room)[0].id == disk[0].id  # stable across reads
    mem = in_memory_store.list_messages(room)
    assert len(disk) == 1 and len(mem) == 1
    assert disk[0].message_id == mem[0].message_id == "a-1"  # one correlation key, dedupable


def test_raise_up_l9_frames_project_into_the_conversational_view():
    """A ``knowledge`` push and a ``commit`` consensus are promoted into the chat
    feed on the cold read, carrying the whole envelope as their ``l9_<kind>`` frame
    — the exact shape the live SSE bus pushes. Without this the frontend promotes
    them live but a refresh drops them (the "temporary" raise-up rows bug).
    """
    import json

    from app.services.l9_slim import serialize_content

    room = "raise-up-room"
    get_room_dir(room)

    know_env = l9.build_envelope(
        kind=Kind.knowledge,
        subkind="extraction",
        episode="urn:ioc:mycelium:episode:raise-up-room:knowledge",
        topic="urn:concept:mycelium:raise-up-room",
        message_id="k-1",
        payload_type="extraction",
        payload_data={"key": "agents/x", "version": 1},
    )
    know_content = serialize_content(know_env, extra={"content": "memory updated → agents/x"})
    persister.append_transcript(room, persister.record_from(know_env, know_content))

    commit_env = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode="urn:ioc:mycelium:episode:raise-up-room:neg",
        topic="urn:concept:mycelium:raise-up-room",
        message_id="c-1",
        payload_type="data",
        payload_data={"assignments": {"alice": "build"}},
    )
    commit_content = serialize_content(commit_env, extra={"content": "CONSENSUS"})
    persister.append_transcript(room, persister.record_from(commit_env, commit_content))

    # A control frame (presence) still stays out — only the raise-up kinds promote.
    pres_env, pres_content = _msg_content(
        "p-1", sender="alice", text="here", payload_type="presence"
    )
    persister.append_transcript(room, persister.record_from(pres_env, pres_content))

    projected = persister.conversational_messages(room)
    assert [(m.message_type, m.message_id) for m in projected] == [
        ("l9_knowledge", "k-1"),
        ("l9_commit", "c-1"),
    ]
    # The content is the full envelope JSON, so the frontend decodes a refresh
    # identically to the live frame it pushes over SSE.
    assert json.loads(projected[0].content)["l9"]["header"]["kind"] == "knowledge"
    assert projected[0].episode == "urn:ioc:mycelium:episode:raise-up-room:knowledge"


def test_addressed_absent_recipient_holds_the_triggering_message():
    """§E: a message @-addressed to an absent, untracked agent is held in its
    undelivered tail, so its first wake replays the mention that invited it —
    instead of tracking at the transcript end and skipping it.
    """
    log = persister.DeliveryLog()
    # An @-mention broadcast while agent-x is absent (not present, not tracked).
    log.record(_record("m1", sender="avery"), delivered_to=set(), recipients=["agent-x"])
    assert [r.message_id for r in log.undelivered("agent-x")] == ["m1"]

    # A later unrelated message it also misses stays in the tail, in order.
    log.record(_record("m2", sender="avery"), delivered_to=set(), recipients=[])
    assert [r.message_id for r in log.undelivered("agent-x")] == ["m1", "m2"]

    # A genuinely fresh join (not addressed) starts caught-up: nothing to replay.
    log.track("bystander", caught_up=True)
    assert log.undelivered("bystander") == []


def test_handle_from_disconnect_parses_the_leaving_handle():
    m = "message='participant disconnected: mycelium/smoke3/smoke-agent/ffffffffffffffff'"
    assert persister._handle_from_disconnect(m) == "smoke-agent"
    assert persister._handle_from_disconnect("participant disconnected: ws/room/bob") == "bob"
    assert persister._handle_from_disconnect("some other error") is None


@pytest.mark.asyncio
async def test_participant_disconnect_is_membership_not_fatal():
    """A member dropping is presence: on_member_left fires and the loop keeps
    serving (it must NOT spend the failure budget and zombie the room).
    """

    class _FlappyChannel:
        def __init__(self):
            self.calls = 0

        async def receive_with_context(self):
            self.calls += 1
            if self.calls > 5:  # let several disconnects go by, then stop the loop
                raise __import__("asyncio").CancelledError
            raise RuntimeError("participant disconnected: mycelium/r/agent-x/abcd")

    left: list[str] = []
    p = persister.RoomPersister(
        "flappy-room",
        _FlappyChannel(),  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        on_member_left=left.append,
        feed_bus=False,
    )
    with pytest.raises(__import__("asyncio").CancelledError):
        await p.run()
    # Five disconnects, all treated as membership events (not the 3-strike give-up).
    assert left == ["agent-x"] * 5
    assert p.receive_errors == 0


def test_list_store_skips_presence_and_non_conversational():
    """Presence/control payloads stay out of the chat list (transcript/bus only)."""
    from app.services import in_memory_store

    room = "h2-presence-room"
    p = _persister_for(room, summoned=[], converged=[])

    pres_env, pres_content = _msg_content(
        "p-1", sender="smoke-agent", text="joined the room", payload_type="presence"
    )
    p._ingest(pres_env, pres_content)

    assert in_memory_store.list_messages(room) == []


# ── knowledge apply: inbound memory-sync writes converge the local store ─────


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Applying a knowledge write reindexes through the embedder; stub it so
    these tests never load the fastembed ONNX model (matches
    ``test_memory_sync.py``'s fixture)."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


def _knowledge_envelope(
    *,
    room: str,
    key: str = "plan/tasks.md",
    content: str = "# Plan\n\n- [ ] first task\n",
    version: int = 1,
    base_version: int | None = None,
    subkind: str = memory_sync.KNOWLEDGE_SUBKIND,
):
    """A `knowledge` envelope; `build_knowledge_envelope` mints a fresh random
    message id per call, so distinct calls are never deduped against each other."""
    from app.services.l9_slim import serialize_content

    write = memory_sync.KnowledgeWrite(
        key=key,
        content=content,
        version=version,
        created_by="system",
        updated_by="system",
        updated_at="2026-08-04T00:00:00+00:00",
        base_version=base_version,
    )
    env = memory_sync.build_knowledge_envelope(
        room=room, write=write, recipients=["bob"], subkind=subkind
    )
    return env, serialize_content(env)


@pytest.mark.asyncio
async def test_ingest_applies_inbound_knowledge_write_to_local_store():
    """A `knowledge` envelope arriving on the channel writes the carried markdown
    into this backend's local store — the receive half of cross-store memory
    convergence (#549)."""
    room = "knowledge-room-1"
    p = _persister_for(room, summoned=[], converged=[])

    env, content = _knowledge_envelope(room=room, version=1)
    p._ingest(env, content)
    for task in list(p._knowledge_tasks):
        await task

    got = read_memory_file(get_room_dir(room), "plan/tasks.md")
    assert got is not None
    assert got[1] == "# Plan\n\n- [ ] first task"
    assert p.knowledge_applied == 1
    assert p.knowledge_conflicts == 0


@pytest.mark.asyncio
async def test_ingest_applies_extraction_subkind_the_same_way():
    """`extraction` (a raw ``memory set``) applies identically to `distillation`
    — the applier is subkind-agnostic."""
    room = "knowledge-room-2"
    p = _persister_for(room, summoned=[], converged=[])

    env, content = _knowledge_envelope(
        room=room,
        key="notes/idea.md",
        content="an idea\n",
        version=1,
        subkind=memory_sync.MEMORY_WRITE_SUBKIND,
    )
    p._ingest(env, content)
    for task in list(p._knowledge_tasks):
        await task

    got = read_memory_file(get_room_dir(room), "notes/idea.md")
    assert got is not None
    assert got[1] == "an idea"
    assert p.knowledge_applied == 1


@pytest.mark.asyncio
async def test_ingest_knowledge_loopback_is_idempotent_not_a_double_write():
    """The sender's own broadcast loops back through ``ingest_local`` /
    ``_ingest`` too. Applying it again must be a silent no-op (same version) —
    never a re-broadcast or a double-write — so two hosts can't ping-pong."""
    room = "knowledge-room-3"
    p = _persister_for(room, summoned=[], converged=[])

    env, content = _knowledge_envelope(room=room, version=1)
    p._ingest(env, content)
    for task in list(p._knowledge_tasks):
        await task
    assert p.knowledge_applied == 1

    # Same write, same version, arriving again (e.g. a second connector's own
    # loopback of the same broadcast, or a redelivery).
    env2, content2 = _knowledge_envelope(room=room, version=1)
    p._ingest(env2, content2)
    for task in list(p._knowledge_tasks):
        await task

    assert p.knowledge_applied == 1  # unchanged: idempotent, not a second write
    assert p.knowledge_conflicts == 0


@pytest.mark.asyncio
async def test_ingest_knowledge_stale_base_is_a_conflict_not_a_merge():
    """An incoming write behind the local version is rejected (last-write-wins);
    the newer local content survives untouched."""
    room = "knowledge-room-4"
    p = _persister_for(room, summoned=[], converged=[])

    newer, newer_content = _knowledge_envelope(room=room, content="v2 content\n", version=2)
    p._ingest(newer, newer_content)
    for task in list(p._knowledge_tasks):
        await task
    assert p.knowledge_applied == 1

    stale, stale_content = _knowledge_envelope(room=room, content="v1 content\n", version=1)
    p._ingest(stale, stale_content)
    for task in list(p._knowledge_tasks):
        await task

    got = read_memory_file(get_room_dir(room), "plan/tasks.md")
    assert got is not None
    assert got[1] == "v2 content"  # the newer local content was not overwritten
    assert p.knowledge_applied == 1  # the stale write did not count as applied
    assert p.knowledge_conflicts == 1
