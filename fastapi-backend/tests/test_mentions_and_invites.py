# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for human-in-the-room: @-parse + consent-gated invites (Step 6).

Node-free. The ``@``-parse is pure; the invite/consent flow is exercised against
a :class:`RoomChannelManager` with a faked managed channel injected directly into
its registry, so no SLIM node (and no real invite handshake) is needed. The live
wake-over-a-node slice lives in the CLI's
``test_human_mention_wakes_connector.py`` (guarded).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import invites, room_channels
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


def _manager_with_channel(
    members: set[str] | None = None,
) -> tuple[RoomChannelManager, ManagedRoomChannel]:
    """A manager whose room has a faked, always-'live' channel + persister."""
    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    channel = MagicMock()
    channel.send = AsyncMock()
    persister = MagicMock()
    managed = ManagedRoomChannel(
        room=_ROOM,
        workspace="mycelium",
        client=MagicMock(),
        channel=channel,
        members=set(members or set()),
    )
    managed.persister = persister
    manager._channels[_ROOM] = managed
    return manager, managed


# ── publish_human: recipients + wake vs invite ────────────────────────────────


@pytest.mark.asyncio
async def test_publish_human_maps_recipients_wakes_present_invites_absent():
    manager, managed = _manager_with_channel(members={"agent-x"})

    result = await manager.publish_human(_ROOM, sender="julia", text="@agent-x @agent-y ship it")

    assert result is not None
    # Both mentions become L9 recipients (the semantic "to").
    assert result.recipients == ["agent-x", "agent-y"]

    # The broadcast carried an exchange whose recipients are exactly the mentions.
    channel_send = cast(MagicMock, managed.channel.send)
    channel_send.assert_awaited_once()
    envelope = channel_send.await_args.args[0]
    actor_ids = [a.id for a in envelope.header.participants.actors]
    assert actor_ids == ["julia", "agent-x", "agent-y"]
    assert envelope.header.kind.value == "exchange"

    # Persister ingests the message locally exactly once (transcript + bus feed).
    cast(MagicMock, managed.persister).ingest_local.assert_called_once()

    # agent-x is present (a wake, no invite); agent-y is absent (consent invite).
    assert [inv.agent for inv in result.invites] == ["agent-y"]
    assert result.invites[0].status == invites.PENDING


@pytest.mark.asyncio
async def test_publish_human_returns_none_without_a_live_channel():
    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    assert await manager.publish_human("no-such-room", sender="julia", text="@x hi") is None


# ── consent: accept joins, decline does not ───────────────────────────────────


@pytest.mark.asyncio
async def test_absent_invite_accept_joins():
    manager, _managed = _manager_with_channel(members=set())
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="julia", text="@bob take a look")
    assert result is not None
    invite = result.invites[0]
    assert manager.pending_invites(_ROOM) == [invite]
    invite_mock.assert_not_awaited()  # consent gates the join

    accepted = await manager.accept_invite(invite.id)
    assert accepted is not None and accepted.status == invites.ACCEPTED
    invite_mock.assert_awaited_once_with(_ROOM, "bob")
    assert manager.pending_invites(_ROOM) == []  # no longer open


@pytest.mark.asyncio
async def test_absent_invite_decline_does_not_join():
    manager, _managed = _manager_with_channel(members=set())
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="julia", text="@carol ?")
    assert result is not None
    invite = result.invites[0]

    declined = manager.decline_invite(invite.id)
    assert declined is not None and declined.status == invites.DECLINED
    invite_mock.assert_not_awaited()
    assert manager.pending_invites(_ROOM) == []


# ── mid-episode: invite queued until the episode closes ───────────────────────


@pytest.mark.asyncio
async def test_mid_episode_invite_is_queued_then_flushed_on_close():
    manager, _managed = _manager_with_channel(members={"agent-a"})
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]
    manager.open_episode(_ROOM, "urn:ioc:mycelium:episode:step6-room:e1")

    result = await manager.publish_human(_ROOM, sender="julia", text="@dave join us")
    assert result is not None
    invite = result.invites[0]

    accepted = await manager.accept_invite(invite.id)
    assert accepted is not None and accepted.status == invites.QUEUED
    invite_mock.assert_not_awaited()  # deferred, not applied mid-episode

    # Closing the episode drains the queue → the deferred invite is applied.
    await manager.close_episode(_ROOM)
    invite_mock.assert_awaited_once_with(_ROOM, "dave")
    assert manager.pending_invites(_ROOM) == []


# ── in-room mention already present: no invite raised ─────────────────────────


def test_request_invite_returns_none_for_present_member():
    manager, _managed = _manager_with_channel(members={"agent-x"})
    assert manager.request_invite(_ROOM, "agent-x", requested_by="julia") is None
    assert manager.request_invite(_ROOM, room_channels.BACKEND_AGENT, requested_by="julia") is None
