# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``@here`` and ``@all``: who they reach, and that what's shown is who's asked."""

from __future__ import annotations

import pytest
import yaml

from app.services import groups, message_format, principals, room_people, tasks
from app.services.asks import asked, asks
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.in_memory_store import StoredMessage, add_message
from app.services.message_models import Kind
from app.services.message_slim import serialize_content
from app.services.persister import (
    parse_interrupt_mentions,
    parse_mentions,
    parse_named,
    parse_silent_mentions,
)

ROOM = "checkout"


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    # Filing a task indexes it; the index's model isn't what's under test.
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


def _agent(handle: str, *, adapter: str = "claude_code") -> None:
    body = yaml.safe_dump({"adapter": adapter})
    write_memory_file(get_room_dir(ROOM), f"agents/{handle}", body, created_by="test")


def _room() -> None:
    """A busy room: two people, four agents and an engine."""
    for person in ("julia", "sam"):
        principals.write_user({"handle": person})
    get_room_dir(ROOM)
    room_people.start(ROOM, "julia", ["sam"])
    for agent in ("builder", "reviewer", "scout", "lead"):
        _agent(agent)
    _agent("aligner", adapter=principals.ENGINE_ADAPTER)


def _said(sender: str, text: str, episode: str | None) -> None:
    add_message(
        ROOM,
        StoredMessage(
            sender_handle=sender,
            message_type="broadcast",
            content=text,
            room_name=ROOM,
            episode=episode,
        ),
    )


def _sent(sender: str, text: str, episode: str | None) -> dict:
    """A message's content as the hub keeps it, groups resolved as it's sent."""
    extra, _ = groups.on_message(ROOM, text=text, episode=episode, sender=sender)
    envelope = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode or message_format.live_episode_urn(ROOM),
        sender=sender,
        sender_role="human",
        recipients=parse_mentions(text),
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
    )
    return serialize_content(envelope, extra=extra)


def test_a_group_is_never_read_as_a_member_called_here_or_all():
    text = "@here and @!all, cc @~here, then @heres and @allison"
    assert parse_mentions(text) == ["heres", "allison"]
    assert parse_interrupt_mentions(text) == []
    assert parse_silent_mentions(text) == []
    assert parse_named(text) == ["heres", "allison"]
    assert groups.parse(text) == {"here": "mention", "all": "interrupt"}
    # Each group in the strongest form it's written in; code is quoted.
    assert groups.parse("@~all then @all") == {"all": "mention"}
    assert groups.parse("`@all` and x@here") == {}


@pytest.mark.asyncio
async def test_here_in_a_task_reaches_whoever_takes_part_not_the_whole_room():
    _room()
    row = await tasks.create_task(
        ROOM, "Turn on Apple Pay", created_by="julia", meta={"assignee": "scout"}
    )
    episode = row.episode
    _said("builder", "on it", episode)
    _said("reviewer", "I'll test it", episode)
    _said("lead", "in the room, not the thread", None)

    reached = groups.members(ROOM, episode=episode, sender="julia")
    here = {m.handle: m.role for m in reached["here"]}
    # The two who posted, and whoever holds the task but hasn't posted yet (a
    # task given to someone is held by them); never the sender.
    assert here == {"builder": "posted", "reviewer": "posted", "scout": "holder"}
    assert next(m for m in reached["here"] if m.handle == "builder").posted_at
    # @all is everyone but the sender, people and agents, never an engine.
    assert {m.handle for m in reached["all"]} == {"sam", "builder", "reviewer", "scout", "lead"}
    assert {m.kind for m in reached["all"] if m.handle == "sam"} == {"person"}

    # Whoever writes is left out, even when they've posted.
    assert "builder" not in {
        m.handle for m in groups.members(ROOM, episode=episode, sender="builder")["here"]
    }


def test_in_the_rooms_channel_here_is_all():
    _room()
    reached = groups.members(ROOM, episode=None, sender="julia")
    assert reached["here"] == reached["all"]
    live = groups.members(ROOM, episode=message_format.live_episode_urn(ROOM), sender="julia")
    assert live["here"] == live["all"]


@pytest.mark.asyncio
async def test_a_sent_group_asks_exactly_the_members_it_reached_then():
    _room()
    row = await tasks.create_task(ROOM, "Turn on Apple Pay", created_by="julia")
    episode = row.episode
    _said("builder", "on it", episode)
    _said("reviewer", "I'll test it", episode)

    content = _sent("julia", "@here can you two agree on the rollout?", episode)
    assert asked(content) == {"builder": "mention", "reviewer": "mention"}
    assert asks(content, "lead") is None
    assert asks(content, "julia") is None

    # Kept on the message: someone posting later isn't asked by it.
    _said("lead", "joining in", episode)
    assert asks(content, "lead") is None

    # A message sent now reaches who takes part now, lead included. Interrupt
    # and silent read the same way they do for one member.
    assert asked(_sent("julia", "@!here stop", episode)) == {
        "builder": "interrupt",
        "reviewer": "interrupt",
        "lead": "interrupt",
    }
    silent = _sent("julia", "fyi @~here", episode)
    assert asked(silent) == {}
    assert set(silent[groups.CONTENT_KEY]["named"]) == {"builder", "reviewer", "lead"}
    # A member named one way and asked another is asked.
    assert asked(_sent("julia", "@~here and @all", episode))["builder"] == "mention"


@pytest.mark.asyncio
async def test_the_endpoint_says_who_each_group_reaches(client):
    _room()
    row = await tasks.create_task(ROOM, "Turn on Apple Pay", created_by="julia")
    _said("builder", "on it", row.episode)

    resp = await client.get(
        f"/api/rooms/{ROOM}/mentions/groups", params={"episode": row.episode, "sender": "julia"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["here"]["count"] == 1
    assert body["here"]["members"][0] == {
        "handle": "builder",
        "kind": "agent",
        "status": None,
        "posted_at": body["here"]["members"][0]["posted_at"],
        "role": "posted",
    }
    assert body["all"]["count"] == 5

    channel = (
        await client.get(f"/api/rooms/{ROOM}/mentions/groups", params={"sender": "julia"})
    ).json()
    assert channel["here"] == channel["all"]
    assert (await client.get("/api/rooms/nowhere/mentions/groups")).status_code == 404
