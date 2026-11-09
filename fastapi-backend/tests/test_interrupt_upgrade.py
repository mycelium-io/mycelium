# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Turning a plain ``@handle`` already sent into an interrupt.

Only the message's sender, only for a member it mentioned, only while that
member's wake for it is held and it is working, once per member per message.
The message's text stays as sent; the interrupt is kept beside it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import (
    asks,
    interrupts,
    message_format,
    persister,
    room_channels,
    wake_digest,
)
from app.services.message_models import Kind
from app.services.message_slim import serialize_content
from tests.test_interrupts import ROOM, _jobs, manager, runners  # noqa: F401 - fixtures

MESSAGE = "@coder keep #504 and close #506, they fix the same bug. @scout review #504 only."


@pytest.fixture
def hub(manager, runners, monkeypatch: pytest.MonkeyPatch):  # noqa: F811 - the fixtures above
    """The room's manager as the one ``interrupts`` reaches, with @coder working
    and @scout idle."""
    monkeypatch.setattr(room_channels, "manager", manager)
    manager.set_herdr_presence(ROOM, {"coder": "working", "scout": "idle"})
    return manager


def _send(hub: room_channels.RoomChannelManager, text: str, sender: str, n: int = 1) -> str:
    """``sender`` posts ``text``: recorded, and each handle it asks rung as the
    persister rings them. Returns its id in the room's history."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.live_episode_urn(ROOM),
        sender=sender,
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
        message_id=f"m-{n:03d}",
    )
    content = serialize_content(env, extra={"content": text})
    record = persister.record_from(env, content)
    persister.append_transcript(ROOM, record)
    hook = hub._asked_adapter(ROOM)
    for handle, why in asks.asked(content).items():
        hook(handle, why, env, text)
    return str(persister.read_id(record))


def _upgrade(ref: str, handle: str, by: str) -> interrupts.Interrupted:
    return asyncio.run(interrupts.upgrade(ROOM, ref, handle, by))


def test_the_sender_interrupts_a_working_member_with_a_message_already_sent(hub, runners):  # noqa: F811
    rid = _send(hub, MESSAGE, "operator")
    assert _jobs(runners) == []  # a plain mention: held, nothing stopped

    mark = _upgrade(rid[:8], "@coder", "operator")
    assert (mark.by, mark.handle, mark.message) == ("operator", "coder", rid)
    assert _jobs(runners) == [("interrupt", {"room": ROOM, "handle": "coder", "pane": "w1:p2"})]
    assert [m.handle for m in interrupts.interrupted(ROOM)[rid]] == ["coder"]

    # Once idle, its wake is an interrupt, and the digest says when it was sent.
    hub.set_herdr_presence(ROOM, {"coder": "idle", "scout": "idle"})
    (wake,) = [w for w in hub.drain_herdr_wakes(ROOM) if w["handle"] == "coder"]
    assert wake["reason"] == "interrupt"
    assert wake["from"] == "operator"
    digest = wake_digest.build(ROOM, wake, persister.load_transcript(ROOM))
    assert "operator interrupted you with a message they sent" in digest.replace("@", "")
    assert "while you were working" in digest
    assert "interrupted you just now" in digest


@pytest.mark.parametrize(
    ("handle", "by", "status", "says"),
    [
        ("coder", "scout", 403, "Only @operator, who sent"),
        (
            "aligner",
            "operator",
            422,
            "doesn't mention @aligner. To ask it now, send a message with @!aligner",
        ),
        ("scout", "operator", 409, "isn't working right now"),
        ("stranger", "operator", 409, "isn't running anywhere Mycelium can stop it"),
    ],
)
def test_a_refusal_says_why(hub, runners, handle, by, status, says):  # noqa: F811
    rid = _send(hub, f"{MESSAGE} @stranger too", "operator")
    with pytest.raises(interrupts.Refused) as refused:
        _upgrade(rid, handle, by)
    assert refused.value.status == status
    assert says in refused.value.detail
    assert _jobs(runners) == []
    assert interrupts.interrupted(ROOM) == {}


def test_it_is_once_per_member_per_message(hub):
    rid = _send(hub, MESSAGE, "operator")
    _upgrade(rid, "coder", "operator")
    with pytest.raises(interrupts.Refused) as refused:
        _upgrade(rid, "coder", "operator")
    assert refused.value.status == 409
    assert "already interrupted" in refused.value.detail


def test_nothing_to_interrupt_once_the_member_has_it(hub):
    rid = _send(hub, MESSAGE, "operator")
    # Its turn ends and the wake goes to it; then it starts another turn.
    hub.set_herdr_presence(ROOM, {"coder": "idle", "scout": "idle"})
    hub.drain_herdr_wakes(ROOM)
    hub.set_herdr_presence(ROOM, {"coder": "working", "scout": "idle"})
    with pytest.raises(interrupts.Refused) as refused:
        _upgrade(rid, "coder", "operator")
    assert "already, so there's nothing to interrupt" in refused.value.detail


def test_a_message_that_already_says_at_bang_is_refused(hub):
    rid = _send(hub, "@!coder stop, wrong checkout", "operator")
    with pytest.raises(interrupts.Refused) as refused:
        _upgrade(rid, "coder", "operator")
    assert "already interrupts @coder" in refused.value.detail


def test_a_later_message_doesnt_hold_an_earlier_one(hub):
    # The wake held now is for the second message; the first one was handed over.
    first = _send(hub, "@coder first", "operator", n=1)
    hub.set_herdr_presence(ROOM, {"coder": "idle"})
    hub.drain_herdr_wakes(ROOM)
    hub.set_herdr_presence(ROOM, {"coder": "working"})
    _send(hub, "@coder second", "operator", n=2)
    with pytest.raises(interrupts.Refused):
        _upgrade(first, "coder", "operator")


async def test_the_route_and_the_history_read(client, hub):
    await client.post("/api/rooms", json={"name": ROOM})
    rid = _send(hub, MESSAGE, "operator")
    resp = await client.post(
        f"/api/rooms/{ROOM}/messages/{rid[:8]}/interrupt",
        json={"handle": "coder", "by": "operator"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["handle"] == "coder"
    again = await client.post(
        f"/api/rooms/{ROOM}/messages/{rid[:8]}/interrupt",
        json={"handle": "coder", "by": "operator"},
    )
    assert again.status_code == 409
    read = (await client.get(f"/api/rooms/{ROOM}/messages", params={"id": rid[:8]})).json()
    (message,) = read["messages"]
    assert message["content"] == MESSAGE, "the text is as sent"
    assert [(m["by"], m["handle"]) for m in message["interrupted"]] == [("operator", "coder")]


async def test_the_id_the_send_route_returned_finds_the_message(
    client, hub, monkeypatch: pytest.MonkeyPatch
):
    """The app interrupts with the id ``POST /messages`` gave it, which is not
    the history read's; the wire id works too."""
    await client.post("/api/rooms", json={"name": ROOM})

    async def publish(_channel, *, sender, text, episode=None):
        _send(hub, text, sender)  # recorded and rung, as the persister does
        return SimpleNamespace(message_id="m-001", unrecognized=[])

    monkeypatch.setattr(hub, "is_live", lambda _channel: True)
    monkeypatch.setattr(hub, "publish_human", publish)
    sent = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"sender_handle": "operator", "message_type": "broadcast", "content": MESSAGE},
    )
    assert sent.status_code == 201, sent.text
    posted = sent.json()["id"]
    rid = str(persister.read_id_of("m-001"))
    assert posted != rid, "the two ids differ, or this tests nothing"

    resp = await client.post(
        f"/api/rooms/{ROOM}/messages/{posted}/interrupt",
        json={"handle": "coder", "by": "operator"},
    )
    assert resp.status_code == 201, resp.text
    assert [m.handle for m in interrupts.interrupted(ROOM)[rid]] == ["coder"]

    # By its wire id it's the same message, so it is already interrupted.
    by_wire = await client.post(
        f"/api/rooms/{ROOM}/messages/m-001/interrupt",
        json={"handle": "coder", "by": "operator"},
    )
    assert by_wire.status_code == 409, by_wire.text
    assert "already interrupted" in by_wire.json()["detail"]


def test_a_digest_box_names_who_else_is_working(hub):
    _send(hub, MESSAGE, "operator")
    hub.set_herdr_presence(ROOM, {"coder": "working", "scout": "idle"})
    (wake,) = [w for w in hub.drain_herdr_wakes(ROOM) if w["handle"] == "scout"]
    digest = wake_digest.build(ROOM, wake, persister.load_transcript(ROOM))
    assert "also for @coder (working)" in digest
