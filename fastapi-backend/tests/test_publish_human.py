# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for human-in-the-room: the ``@``-parse and what a person's message does.

The ``@``-parse is pure; ``publish_human`` and the negotiation abort are
exercised against a :class:`RoomChannelManager` holding a room whose persister
records into a list.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import room_channels
from app.services.persister import parse_mentions
from app.services.room_channels import ManagedRoomChannel, RoomChannelManager

_ROOM = "step6-room"


# ── @-parse → participants ────────────────────────────────────────────────────


def test_parse_mentions_maps_tokens_and_ignores_emails():
    assert parse_mentions("@agent-x @agent-y do the thing") == ["agent-x", "agent-y"]
    # A bare word@host is an email, not a mention — the @ isn't at a boundary.
    assert parse_mentions("ping agentx@host.example now") == []
    # Deduped, first-seen order preserved.
    assert parse_mentions("@a hi @b then @a again") == ["a", "b"]
    # Leading and bracketed forms both count.
    assert parse_mentions("@lead go") == ["lead"]
    assert parse_mentions("(<@ping>)") == ["ping"]


# ── fixtures ──────────────────────────────────────────────────────────────────


class _Recording:
    """A persister that keeps what it is asked to record."""

    def __init__(self) -> None:
        self.recorded: list[tuple[Any, dict[str, Any]]] = []

    def record(self, envelope: Any, content: dict[str, Any], *, list_write: bool = False) -> None:
        self.recorded.append((envelope, content))


def _manager_with_room() -> tuple[RoomChannelManager, ManagedRoomChannel, _Recording]:
    manager = RoomChannelManager()
    persister = _Recording()
    managed = ManagedRoomChannel(room=_ROOM, persister=persister)  # ty: ignore[invalid-argument-type]
    manager._channels[_ROOM] = managed
    return manager, managed, persister


def _registered(monkeypatch: pytest.MonkeyPatch, *handles: str) -> None:
    """Treat exactly ``handles`` as agents with a manifest in the room."""
    monkeypatch.setattr(
        room_channels, "_is_own_registered_agent", lambda _room, handle: handle in handles
    )


# ── publish_human: recipients, recorded once ──────────────────────────────────


@pytest.mark.asyncio
async def test_publish_human_maps_mentions_to_recipients_and_records_once(monkeypatch):
    manager, _managed, persister = _manager_with_room()
    _registered(monkeypatch, "agent-x", "agent-y")

    result = await manager.publish_human(_ROOM, sender="avery", text="@agent-x @agent-y ship it")

    # Mentions map to message recipients.
    assert result.recipients == ["agent-x", "agent-y"]
    assert result.unrecognized == []

    # Recorded exactly once, as an exchange addressed to who it mentions.
    ((envelope, content),) = persister.recorded
    assert [a.id for a in envelope.header.participants.actors] == ["avery", "agent-x", "agent-y"]
    assert envelope.header.kind.value == "exchange"
    assert content["content"] == "@agent-x @agent-y ship it"
    assert result.message_id == envelope.header.message.id


@pytest.mark.asyncio
async def test_publish_human_opens_a_room_it_has_not_seen():
    """A person's message to a room is always recorded: there is no channel to
    wait for, so a room the manager hasn't opened yet is opened for it."""
    from app.services import persister
    from app.services.filesystem import get_room_dir

    get_room_dir("fresh-room")
    manager = RoomChannelManager()
    result = await manager.publish_human("fresh-room", sender="avery", text="hello")

    assert [r.message_id for r in persister.load_transcript("fresh-room")] == [result.message_id]


@pytest.mark.asyncio
async def test_an_await_lease_holder_is_a_recognized_mention(monkeypatch):
    """A bare-CLI agent long-polling ``await`` holds a presence lease: a mention
    of it reaches it through the transcript its poll reads."""
    manager, _managed, _persister = _manager_with_room()
    _registered(monkeypatch)  # no manifest: present by its lease alone
    manager.refresh_lease(_ROOM, "workpc")

    result = await manager.publish_human(_ROOM, sender="avery", text="@workpc ping")

    assert result.recipients == ["workpc"]
    assert result.unrecognized == []


@pytest.mark.asyncio
async def test_a_mention_of_nobody_the_room_knows_is_unrecognized(monkeypatch):
    """Mentioning a human (yourself included) or a typo still addresses them,
    and the result says no member of the room answers to the name."""
    manager, _managed, _persister = _manager_with_room()
    _registered(monkeypatch, "mine")

    result = await manager.publish_human(_ROOM, sender="avery", text="@mine @dana @typo look")

    assert result.recipients == ["mine", "dana", "typo"]  # still addressed ...
    assert result.unrecognized == ["dana", "typo"]  # ... but only @mine is a member


# ── a party leaving ends the negotiation, recorded with a line ────────────────


@pytest.mark.asyncio
async def test_a_party_leaving_aborts_the_negotiation_with_a_line_saying_why():
    """A party leaving the room aborts the negotiation: the abort is recorded
    with one plain line, so the transcript and the UI read why, not a bare
    protocol record."""
    manager, managed, persister = _manager_with_room()
    manager.open_episode(
        _ROOM, "urn:mycelium:episode:step6-room:e1", parties=["agent-a", "agent-b"]
    )

    # Someone who isn't a party leaving changes nothing.
    await manager._abort_if_party_left(managed, "bystander")
    assert managed.lifecycle.active
    assert persister.recorded == []

    # A party leaves → abort.
    await manager._abort_if_party_left(managed, "agent-b")

    ((abort, content),) = persister.recorded
    assert abort.header.kind.value == "commit"
    assert abort.header.subkind == "rejected"
    assert abort.payload.data["reason"] == "party_left"
    assert content["content"] == "Negotiation stopped: agent-b left the room."
    assert not managed.lifecycle.active
