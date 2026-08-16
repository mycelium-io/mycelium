# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for human-in-the-room: @-parse + consent-gated invites.

Node-free. The ``@``-parse is pure; the invite/consent flow is exercised against
a :class:`RoomChannelManager` with a faked managed channel injected directly into
its registry, so no SLIM node (and no real invite handshake) is needed. The live
wake-over-a-node slice lives in the CLI's
``test_human_mention_wakes_connector.py`` (guarded).
"""

from __future__ import annotations

import asyncio
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

    result = await manager.publish_human(_ROOM, sender="avery", text="@agent-x @agent-y ship it")

    assert result is not None
    # Both mentions become L9 recipients (the semantic "to").
    assert result.recipients == ["agent-x", "agent-y"]

    # The broadcast carried an exchange whose recipients are exactly the mentions.
    channel_send = cast(MagicMock, managed.channel.send)
    channel_send.assert_awaited_once()
    envelope = channel_send.await_args.args[0]
    actor_ids = [a.id for a in envelope.header.participants.actors]
    assert actor_ids == ["avery", "agent-x", "agent-y"]
    assert envelope.header.kind.value == "exchange"

    # Persister ingests the message locally exactly once (transcript + bus feed).
    cast(MagicMock, managed.persister).ingest_local.assert_called_once()

    # agent-x is present (a wake, no invite); agent-y is absent (consent invite).
    assert [inv.agent for inv in result.invites] == ["agent-y"]
    assert result.invites[0].status == invites.PENDING


@pytest.mark.asyncio
async def test_publish_human_returns_none_without_a_live_channel():
    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    assert await manager.publish_human("no-such-room", sender="avery", text="@x hi") is None


@pytest.mark.asyncio
async def test_publish_human_treats_await_lease_holder_as_present():
    """A bare-CLI agent long-polling ``await`` holds a presence lease but no SLIM
    membership. An @-mention of it must be a wake (delivered via the transcript its
    poll reads), not a consent invite."""
    manager, _managed = _manager_with_channel(members=set())
    manager.refresh_lease(_ROOM, "workpc")  # an active `await` long-poll

    result = await manager.publish_human(_ROOM, sender="avery", text="@workpc ping")

    assert result is not None
    assert result.invites == []  # present via lease → wake, no consent prompt
    assert manager.pending_invites(_ROOM) == []


def test_status_members_include_await_leases():
    """status() reports the roster the mediator sees — SLIM members plus live
    leases — so a server-held ``await`` participant is visible on ``/health``."""
    manager, _managed = _manager_with_channel(members={"agent-x"})
    manager.refresh_lease(_ROOM, "workpc")

    entry = next(r for r in manager.status()["rooms"] if r["room"] == _ROOM)
    assert set(entry["members"]) == {"agent-x", "workpc"}


# ── consent: accept joins, decline does not ───────────────────────────────────


@pytest.mark.asyncio
async def test_absent_invite_accept_joins():
    manager, _managed = _manager_with_channel(members=set())
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@bob take a look")
    assert result is not None
    invite = result.invites[0]
    assert manager.pending_invites(_ROOM) == [invite]
    invite_mock.assert_not_awaited()  # consent gates the join

    accepted = await manager.accept_invite(invite.id)
    assert accepted is not None and accepted.status == invites.ACCEPTED
    await asyncio.gather(*manager._tasks)  # accept schedules the SLIM invite off the request path
    invite_mock.assert_awaited_once_with(_ROOM, "bob")
    assert manager.pending_invites(_ROOM) == []  # no longer open


@pytest.mark.asyncio
async def test_absent_invite_decline_does_not_join():
    manager, _managed = _manager_with_channel(members=set())
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@carol ?")
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

    result = await manager.publish_human(_ROOM, sender="avery", text="@dave join us")
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
    assert manager.request_invite(_ROOM, "agent-x", requested_by="avery") is None
    assert manager.request_invite(_ROOM, room_channels.BACKEND_AGENT, requested_by="avery") is None


# ── cross-host consent: the invitee is addressed by identity, not by host ──────


@pytest.mark.asyncio
async def test_accept_invites_remote_agent_by_identity_only(monkeypatch):
    """Cross-host consent: accepting resolves the invitee purely by its
    ``workspace/room/agent`` SLIM identity — never a host or endpoint — so the
    moderator invites the same member whether its connector runs on this machine
    or another one on the shared node. This is why the consent → invite → join
    path needs no new cross-machine mechanism: membership is identity-addressed.
    """
    manager, managed = _manager_with_channel(members=set())

    # Bindings aren't installed in the unit env; record the identity the invite
    # would resolve and hand back an opaque token in place of a SLIM Name.
    resolved: list[tuple[str, str, str]] = []

    def _fake_name(ws: str, room: str, agent: str) -> object:
        resolved.append((ws, room, agent))
        return object()

    monkeypatch.setattr(room_channels, "to_slim_name", _fake_name)
    cast(MagicMock, managed.client).invite = AsyncMock()  # the real manager.invite() path runs
    cast(MagicMock, managed.persister).note_join.return_value = False  # no re-serve

    result = await manager.publish_human(_ROOM, sender="avery", text="@remote-bob join us")
    assert result is not None
    invite = result.invites[0]
    assert invite.agent == "remote-bob"

    accepted = await manager.accept_invite(invite.id)
    assert accepted is not None and accepted.status == invites.ACCEPTED
    await asyncio.gather(*manager._tasks)  # the invite now runs off the request path

    # Addressed by identity only (no host/endpoint) — host-independent membership.
    assert resolved == [("mycelium", _ROOM, "remote-bob")]
    cast(AsyncMock, managed.client.invite).assert_awaited_once()
    assert "remote-bob" in managed.members


# ── own agent: mid-episode invite must queue, not abort the episode ────────────


@pytest.mark.asyncio
async def test_own_agent_mention_outside_episode_invites_immediately(monkeypatch):
    """No active episode: a user's own registered agent joins directly (no prompt,
    no queue) — the pre-authorized fast path."""
    manager, _managed = _manager_with_channel(members=set())
    monkeypatch.setattr(room_channels, "_is_own_registered_agent", lambda *_: True)
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@mine hi")

    assert result is not None
    assert result.invites == []  # own agent → no consent prompt
    bg.assert_called_once_with(_ROOM, "mine")
    assert manager.pending_invites(_ROOM) == []  # nothing deferred


@pytest.mark.asyncio
async def test_own_agent_mention_mid_episode_is_queued_not_invited(monkeypatch):
    """A user's own agent, @-mentioned while an episode is active, must NOT be
    invited directly (that membership change would abort the episode). It is queued
    like a consent accept and applied once the episode closes."""
    manager, _managed = _manager_with_channel(members={"agent-a"})
    monkeypatch.setattr(room_channels, "_is_own_registered_agent", lambda *_: True)
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]
    manager.open_episode(_ROOM, "urn:ioc:mycelium:episode:step6-room:e1")

    result = await manager.publish_human(_ROOM, sender="avery", text="@mine come help")

    assert result is not None
    assert result.invites == []  # own agent → no consent prompt surfaced
    bg.assert_not_called()  # not invited directly mid-episode ...
    invite_mock.assert_not_awaited()
    assert [inv.agent for inv in manager.pending_invites(_ROOM)] == ["mine"]  # ... queued

    # Closing the episode drains the queue → the deferred own-agent invite lands.
    await manager.close_episode(_ROOM)
    invite_mock.assert_awaited_once_with(_ROOM, "mine")


# ── episode abort: recorded locally + queued invites flushed ───────────────────


@pytest.mark.asyncio
async def test_episode_abort_ingests_locally_and_flushes_queue():
    """A mid-episode membership change aborts the episode: the abort is broadcast
    AND ingested locally (so the transcript/UI see it, independent of SLIM
    loopback), and invites queued during the episode are applied once it closes."""
    manager, managed = _manager_with_channel(members={"agent-a", "agent-b"})
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]
    manager.open_episode(_ROOM, "urn:ioc:mycelium:episode:step6-room:e1")

    # A consent invite accepted mid-episode is deferred (queued).
    result = await manager.publish_human(_ROOM, sender="avery", text="@dave join")
    assert result is not None
    invite = result.invites[0]
    await manager.accept_invite(invite.id)
    assert invite.status == invites.QUEUED

    # A member drops → membership changed under the episode → abort.
    managed.members.discard("agent-b")
    await manager._enforce_membership_change(managed)

    # The abort is the last thing broadcast on the wire ...
    abort = cast(MagicMock, managed.channel.send).await_args.args[0]
    assert abort.header.kind.value == "commit"
    assert abort.header.subkind == "rejected"
    # ... and it was ingested locally (the fix — else it's missing from the UI).
    last_ingested = cast(MagicMock, managed.persister).ingest_local.call_args.args[0]
    assert last_ingested.header.kind.value == "commit"
    assert last_ingested.header.subkind == "rejected"
    # The queued invite is applied now the episode is closed.
    invite_mock.assert_awaited_once_with(_ROOM, "dave")
    assert not managed.lifecycle.active
