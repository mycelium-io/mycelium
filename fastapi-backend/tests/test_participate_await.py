# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` delivers off the durable per-handle cursor (#649).

Node-free: the SLIM channel is faked so the test exercises only the delivery
logic — that a first ``await`` replays a message already sitting in the
transcript addressed to the handle (the reported bug), consumes it, and that the
cursor is the durable inbox's, not a process-local one.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.routes import participate
from app.services import message_format, persister
from app.services.asks import asks
from app.services.message_models import Kind
from app.services.message_slim import serialize_content

# A bare ASGI request — ``authorize_handle`` is stubbed out, so the route never
# reads it; it exists only to satisfy the ``Request`` parameter type.
_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


def _addressed_record(message_id: str, *, to: str, sender: str = "avery"):
    """A human exchange @-addressed to ``to`` (a message recipient, as the send path
    builds it), recorded as a transcript record."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("r", "live"),
        sender=sender,
        sender_role="human",
        recipients=[to],
        topic=message_format.topic_urn("r"),
        message_id=message_id,
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": f"@{to} hello"})
    return persister.record_from(env, content)


class _FakePersister:
    """Just enough of RoomPersister for the await loop: a durable log + the
    consume-side cursor advance, room-wide and per-thread (no disk write needed
    in the unit test)."""

    def __init__(self, log: persister.DeliveryLog) -> None:
        self.log = log
        self.episode_cursors = persister.EpisodeCursors()

    def advance_cursor(self, handle: str, pos: int) -> None:
        self.log.advance(handle, pos)

    def episode_position(self, handle: str, episode: str) -> int:
        return self.episode_cursors.position(handle, episode, default=self.log.position(handle))

    def advance_episode_cursor(self, handle: str, episode: str, pos: int) -> None:
        self.episode_cursors.advance(handle, episode, pos, limit=len(self.log.records))


class _Managed:
    def __init__(self, persister_: _FakePersister) -> None:
        self.persister = persister_


@pytest.fixture
def wired(monkeypatch):
    """Wire the await route to a fake room whose transcript we control."""

    def _wire(log: persister.DeliveryLog) -> None:
        managed = _Managed(_FakePersister(log))

        async def _provision(_room):
            return managed

        monkeypatch.setattr(participate, "room_exists", lambda _r: True)
        monkeypatch.setattr(participate.actor, "authorize_handle", lambda *a, **k: None)
        monkeypatch.setattr(participate.room_channels.manager, "provision", _provision)
        monkeypatch.setattr(
            participate.room_channels.manager, "refresh_lease", lambda *a, **k: None
        )
        # Keep the empty-poll cases from spinning the full long-poll window.
        monkeypatch.setattr(participate, "_POLL_INTERVAL_S", 0.01)

    return _wire


@pytest.mark.asyncio
async def test_first_await_replays_a_mention_sent_before_it(wired):
    """The repro: a message addressed to a fresh handle *before* its first await
    is delivered, not skipped at "now"."""
    # A mention broadcast anchors an untracked recipient's cursor at itself.
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )

    wired(log)
    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert result["message_id"] == "m1"
    assert result["prompt"] == "@claude-code-agent hello"


@pytest.mark.asyncio
async def test_await_consumes_the_message_it_serves(wired):
    """A served turn is not served again: the durable cursor advanced past it."""
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )

    wired(log)
    first = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert first["message_id"] == "m1"

    second = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert second["message"] is None  # consumed, nothing left


@pytest.mark.asyncio
async def test_await_hands_over_every_unread_ask_led_by_the_newest(wired):
    """The wake shows every ask and leads with the newest, so one ``await``
    hands over the same: all of them, oldest first, with the newest as the turn.
    Serving the oldest first gave the agent a message the wake had moved past."""
    log = persister.DeliveryLog()
    for mid in ("m1", "m2", "m3"):
        log.record(
            _addressed_record(mid, to="claude-code-agent"),
            delivered_to=set(),
            recipients=["claude-code-agent"],
        )

    wired(log)
    turn = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert turn["message_id"] == "m3"
    assert [a["message_id"] for a in turn["asks"]] == ["m1", "m2", "m3"]
    assert turn["asks"][-1]["prompt"] == turn["prompt"]
    assert turn["asks"][0]["id"] == str(persister.read_id(log.records[0]))

    again = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert again["message"] is None  # all three were handed over


@pytest.mark.asyncio
async def test_await_ignores_turns_addressed_to_others(wired):
    """A handle only wakes on turns addressed to it — an observer broadcast to a
    peer is consumed silently, never returned."""
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="someone-else"),
        delivered_to=set(),
        recipients=["someone-else"],
    )

    wired(log)
    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert result["message"] is None


def test_a_silent_mention_is_not_a_turn():
    """``@~handle`` names a member without asking it anything: the send path
    makes it no recipient, and the text alone does not address it either."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("r", "live"),
        sender="avery",
        sender_role="human",
        recipients=persister.parse_mentions("@reviewer look, cc @~claude-code-agent"),
        topic=message_format.topic_urn("r"),
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": "@reviewer look, cc @~claude-code-agent"})
    assert asks(content, "reviewer")
    assert not asks(content, "claude-code-agent")


@pytest.mark.asyncio
async def test_await_does_not_serve_a_handle_quoted_in_code(wired):
    """A handle inside code is quoted, not mentioned: the send path makes it no
    recipient, and ``await`` reads the text by the same rule, so a message whose
    only mention of the handle is in code is never served to it."""
    text = "quoting `ask @claude-code-agent to look` for @reviewer"
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("r", "live"),
        sender="avery",
        sender_role="human",
        recipients=persister.parse_mentions(text),
        topic=message_format.topic_urn("r"),
        message_id="m1",
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": text})
    assert asks(content, "reviewer")
    assert not asks(content, "claude-code-agent")

    log = persister.DeliveryLog()
    log.record(persister.record_from(env, content), delivered_to=set(), recipients=["reviewer"])
    wired(log)
    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert result["message"] is None


def test_an_interrupting_mention_addresses_by_text():
    """``@!handle`` in the text addresses the handle like ``@handle`` does."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("r", "live"),
        sender="avery",
        sender_role="human",
        recipients=[],
        topic=message_format.topic_urn("r"),
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": "@!Coder stop, wrong checkout"})
    assert asks(content, "coder")


@pytest.mark.asyncio
async def test_a_served_turn_says_the_handle_is_responding(wired):
    """From the moment ``await`` hands a turn over until the reply lands, the
    room is waiting on that handle; the stream says so (#513). Bus-only: the
    transcript gains nothing."""
    from app.bus import bus, room_channel
    from app.services import activity

    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )
    wired(log)
    queue = bus.subscribe(room_channel("r"))
    try:
        result = await participate.await_message(
            "r", _REQUEST, handle="claude-code-agent", timeout=0
        )
        assert result["message_id"] == "m1"
        frame = queue.get_nowait()
    finally:
        bus.unsubscribe(room_channel("r"), queue)

    assert frame["type"] == activity.ACTIVITY_TYPE
    assert frame["handle"] == "claude-code-agent"
    assert frame["state"] == "responding"
    assert frame["episode"] == message_format.episode_urn("r", "live")
    assert len(log.records) == 1  # nothing was written to the transcript


@pytest.mark.asyncio
async def test_await_keeps_the_thread_a_wake_already_named(wired):
    """A wake said where the agent is replying; await serves the oldest message
    first and must not move the room's "responding in" line to an older place."""
    from app.bus import bus, room_channel
    from app.services import activity

    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )
    wired(log)
    activity.signal("r", "claude-code-agent", "responding", episode="urn:the-newest-thread")
    queue = bus.subscribe(room_channel("r"))
    try:
        result = await participate.await_message(
            "r", _REQUEST, handle="claude-code-agent", timeout=0
        )
        assert result["message_id"] == "m1"
        assert queue.empty()  # nothing re-raised over the wake's thread
    finally:
        bus.unsubscribe(room_channel("r"), queue)


def _said(
    message_id: str,
    text: str,
    *,
    sender: str = "julia",
    to: list[str] | None = None,
    thread: str = "live",
    payload_type: str = "message",
):
    """A message said in the room (or ``thread``), addressed to ``to`` if given."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.episode_urn("r", thread),
        sender=sender,
        sender_role="human",
        recipients=to or [],
        topic=message_format.topic_urn("r"),
        message_id=message_id,
        payload_type=payload_type,
    )
    return persister.record_from(env, serialize_content(env, extra={"content": text}))


def _add(log: persister.DeliveryLog, record) -> None:
    """Record as the send path does: a mention names its handle as a recipient,
    which is what anchors a fresh handle's cursor at it."""
    text = record.content.get("content") or ""
    mentioned = ["agent"] if "@agent" in text else []
    log.record(record, delivered_to=set(), recipients=mentioned)


def _log(*records) -> persister.DeliveryLog:
    log = persister.DeliveryLog()
    for record in records:
        _add(log, record)
    return log


@pytest.mark.asyncio
async def test_a_turn_comes_with_what_was_said_before_the_mention(wired):
    """The report: an agent woken by "@agent foo bar" also sees the three
    messages that led up to it, oldest first, though none of them woke it."""
    wired(
        _log(
            _said("m1", "I guess we could ship Friday"),
            _said("m2", "Maybe not, the migration isn't tested"),
            _said("m3", "That's the real risk"),
            _said("m4", "@agent foo bar"),
        )
    )
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert result["message_id"] == "m4"
    assert result["prompt"] == "@agent foo bar"
    assert [e["text"] for e in result["earlier"]] == [
        "I guess we could ship Friday",
        "Maybe not, the migration isn't tested",
        "That's the real risk",
    ]
    assert result["earlier"][0]["sender"] == "julia"


@pytest.mark.asyncio
async def test_earlier_starts_after_the_agents_own_last_message(wired):
    """What the agent already took part in isn't handed back to it."""
    wired(
        _log(
            _said("m1", "old news"),
            _said("m2", "my last reply", sender="agent"),
            _said("m3", "new since then"),
            _said("m4", "@agent and?"),
        )
    )
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert [e["text"] for e in result["earlier"]] == ["new since then"]


@pytest.mark.asyncio
async def test_earlier_is_what_was_said_in_the_same_place(wired):
    """A mention in the room brings the room's messages, not a thread's."""
    wired(
        _log(
            _said("m1", "in the room"),
            _said("m2", "in a task's thread", thread="task-1"),
            _said("m3", "@agent over here"),
        )
    )
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert [e["text"] for e in result["earlier"]] == ["in the room"]


@pytest.mark.asyncio
async def test_earlier_survives_awaiting_in_short_loops(wired):
    """An agent awaiting with a short timeout consumes the chatter on each empty
    poll; the turn that finally comes still carries it."""
    log = _log(_said("m1", "first thought"), _said("m2", "second thought"))
    wired(log)
    empty = await participate.await_message("r", _REQUEST, handle="agent", timeout=1)
    assert empty["message"] is None

    _add(log, _said("m3", "@agent your call"))
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert result["message_id"] == "m3"
    assert [e["text"] for e in result["earlier"]] == ["first thought", "second thought"]


@pytest.mark.asyncio
async def test_earlier_carries_only_what_was_said(wired):
    """A ping or a notice is a nudge, not something said; it isn't handed over."""
    wired(
        _log(
            _said("m1", "a real message"),
            _said("m2", "", payload_type=message_format.PING_PAYLOAD_TYPE),
            _said("m3", "@agent see above"),
        )
    )
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert [e["text"] for e in result["earlier"]] == ["a real message"]


@pytest.mark.asyncio
async def test_an_empty_poll_says_nothing(wired):
    """No turn, no signal: a handle polling an idle room is not responding."""
    from app.bus import bus, room_channel

    wired(persister.DeliveryLog())
    queue = bus.subscribe(room_channel("r"))
    try:
        result = await participate.await_message(
            "r", _REQUEST, handle="claude-code-agent", timeout=1
        )
        assert result["message"] is None
        assert queue.empty()
    finally:
        bus.unsubscribe(room_channel("r"), queue)


@pytest.mark.asyncio
async def test_a_turn_in_the_room_names_no_task(wired):
    """Asked in the room, the turn has no task: a bare ``respond`` answers it."""
    wired(_log(_said("m1", "@agent ship it?")))
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert result["task"] is None


@pytest.mark.asyncio
async def test_a_turn_in_a_tasks_thread_names_the_task(wired, monkeypatch):
    """Asked in a row's thread, the turn names the row, which is what the caller
    passes as ``respond --task`` to answer there: a reply never follows the turn
    on its own."""
    thread = message_format.episode_urn("r", "t3")
    rows = {thread: ("work/fix-receipt", "Fix the receipt")}
    monkeypatch.setattr(participate.tasks, "row_of_episode", lambda _room, ep: rows.get(ep))
    wired(_log(_said("m1", "@agent can you review?", thread="t3")))
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    assert result["episode"] == thread
    assert result["task"] == "work/fix-receipt"


@pytest.mark.asyncio
async def test_a_confirmed_await_hands_the_turn_over_again_until_it_is_confirmed(wired):
    """With ``confirm``, a turn whose response never arrived is handed over by
    the next await; confirming it is what marks it read."""
    log = _log(_said("m1", "@agent ship it?"))
    wired(log)
    first = await participate.await_message("r", _REQUEST, handle="agent", timeout=0, confirm=True)
    assert first["message_id"] == "m1"
    assert first["delivered"] == {"position": 1, "episode": None}

    # The response was lost on the way: the next await hands it over again.
    again = await participate.await_message("r", _REQUEST, handle="agent", timeout=0, confirm=True)
    assert again["message_id"] == "m1"

    await participate.confirm_delivery(
        "r", participate.ConfirmBody(handle="agent", **again["delivered"]), _REQUEST
    )
    after = await participate.await_message("r", _REQUEST, handle="agent", timeout=1, confirm=True)
    assert after["message"] is None


@pytest.mark.asyncio
async def test_a_turn_carries_the_wake_digest_with_the_reply_as_its_next_step(wired):
    """``await`` prints what a herdr wake types, minus the step to run
    ``await``: it already did."""
    wired(_log(_said("m1", "@agent ship it?")))
    turn = await participate.await_message("r", _REQUEST, handle="agent", timeout=0)
    digest = turn["digest"]
    assert digest.startswith("mycelium wake for @agent in r")
    assert "ship it?" in digest
    assert "mycelium await" not in digest
    assert "Next:    " in digest
    assert "mycelium respond --room r --handle agent" in digest


@pytest.mark.asyncio
async def test_an_await_whose_caller_hung_up_hands_nothing_over(wired, monkeypatch):
    """A caller gone while it waited (a proxy cut it) is let go, so a message
    said afterwards is left for its next await rather than lost."""
    log = _log()
    wired(log)

    async def gone(_request):
        return True

    monkeypatch.setattr(participate, "_hung_up", gone)
    result = await participate.await_message("r", _REQUEST, handle="agent", timeout=30)
    assert result["message"] is None
