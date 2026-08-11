# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the backend persister / durable inbox (app/services/persister.py).

Node-free: they exercise the delivery cursor, transcript persistence, and the
trigger detection as pure logic over built envelopes. The live durable-inbox
round trip over a real SLIM node is in ``test_l9_over_slim_roundtrip.py``
(guarded on a running node).
"""

import pytest

from app.services import l9, persister
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


# ── delivery-cursor persistence (D5) ─────────────────────────────────────────


def test_cursors_round_trip_and_missing_file_is_empty():
    room = "cursor-rt-room"
    get_room_dir(room)
    persister.write_cursors(room, {"agent-a": 2, "agent-b": 0})
    assert persister.load_cursors(room) == {"agent-a": 2, "agent-b": 0}
    # A room that never persisted cursors reads back empty, not an error.
    assert persister.load_cursors("no-such-cursor-room") == {}


def test_cursors_survive_a_restart_so_an_offline_tail_is_still_reserved():
    """The D5 fix: an agent offline at shutdown must still be recognised as a
    reconnect and re-served exactly its missed tail after a backend restart.

    Before cursors were persisted, only the transcript reloaded; the restarted
    log knew no cursors, so undelivered() defaulted to the transcript end and the
    reconnecting agent silently got nothing.
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


def test_loaded_cursors_are_clamped_to_the_transcript_length():
    """A cursor file that drifted from the transcript (one write landed across a
    crash, the other didn't) must never index out of bounds."""
    log = persister.DeliveryLog([_record("m1")], cursors={"ahead": 5, "behind": -2})
    assert log.undelivered("ahead") == []  # clamped to end → re-serves nothing
    assert [r.message_id for r in log.undelivered("behind")] == ["m1"]  # clamped to 0


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
    assert read_memory_file(base, persister.TRANSCRIPT_KEY) is not None
    assert (base / "log" / "transcript.md").exists()
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
        on_summon=lambda handle, env, co: summoned.append(handle),
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
    from app.services import local_state

    room = "h2-invariant-room"
    p = _persister_for(room, summoned=[], converged=[])

    # 1) The human's message: written by the POST route (its own producer), and
    #    ingested locally by the persister (local=True → must NOT also list-write).
    human_env, human_content = _msg_content(
        "h-1", sender="julia", text="@smoke-agent hello", payload_type="message"
    )
    local_state.add_message(
        room,
        local_state.StoredMessage(
            room_name=room, sender_handle="julia", message_type="broadcast", content="hello"
        ),
    )
    p._ingest(human_env, human_content, local=True)
    # Its SLIM loopback arrives on the receive path — de-duped by id, no re-write.
    p._ingest(human_env, human_content, local=False)

    # 2) The agent's reply: arrives only over SLIM (receive path) → the persister
    #    is its sole producer.
    agent_env, agent_content = _msg_content(
        "a-1", sender="smoke-agent", text="hi back", payload_type="reply"
    )
    p._ingest(agent_env, agent_content, local=False)

    stored = local_state.list_messages(room)
    assert [(m.sender_handle, m.content) for m in stored] == [
        ("julia", "hello"),
        ("smoke-agent", "hi back"),
    ]


def test_list_store_message_carries_its_episode():
    """Rung 2: a message lands in the list store tagged with the L9 episode it rode,
    so the UI can group/fold a negotiation's turns by episode (and the messages
    route can filter by it)."""
    from app.services import local_state

    room = "episode-tag-room"
    p = _persister_for(room, summoned=[], converged=[])

    env, content = _msg_content("a-1", sender="growth", text="my position", payload_type="reply")
    p._ingest(env, content, local=False)

    stored = local_state.list_messages(room)
    assert len(stored) == 1
    assert stored[0].episode == "urn:ioc:mycelium:episode:r:s"


def test_addressed_absent_recipient_holds_the_triggering_message():
    """§E: a message @-addressed to an absent, untracked agent is held in its
    undelivered tail, so its first wake replays the mention that invited it —
    instead of tracking at the transcript end and skipping it.
    """
    log = persister.DeliveryLog()
    # An @-mention broadcast while agent-x is absent (not present, not tracked).
    log.record(_record("m1", sender="julia"), delivered_to=set(), recipients=["agent-x"])
    assert [r.message_id for r in log.undelivered("agent-x")] == ["m1"]

    # A later unrelated message it also misses stays in the tail, in order.
    log.record(_record("m2", sender="julia"), delivered_to=set(), recipients=[])
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
    from app.services import local_state

    room = "h2-presence-room"
    p = _persister_for(room, summoned=[], converged=[])

    pres_env, pres_content = _msg_content(
        "p-1", sender="smoke-agent", text="joined the room", payload_type="presence"
    )
    p._ingest(pres_env, pres_content, local=False)

    assert local_state.list_messages(room) == []
