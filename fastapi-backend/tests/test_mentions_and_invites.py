# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for human-in-the-room: @-parse + the invite it raises.

Node-free. The ``@``-parse is pure; the invite path is exercised against a
:class:`RoomChannelManager` with a faked managed channel injected directly into
its registry, so no SLIM node (and no real invite handshake) is needed. The live
wake-over-a-node slice lives in the CLI's
``test_human_mention_wakes_connector.py`` (guarded).
"""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

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


def _manager_with_channel(
    members: set[str] | None = None,
) -> tuple[RoomChannelManager, ManagedRoomChannel]:
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


def _registered(monkeypatch: pytest.MonkeyPatch, *handles: str) -> None:
    """Treat exactly ``handles`` as agents with a manifest in the room."""
    monkeypatch.setattr(
        room_channels, "_is_own_registered_agent", lambda _room, handle: handle in handles
    )


# ── publish_human: recipients + wake vs invite ────────────────────────────────


@pytest.mark.asyncio
async def test_publish_human_maps_recipients_wakes_present_invites_absent(monkeypatch):
    manager, managed = _manager_with_channel(members={"agent-x"})
    _registered(monkeypatch, "agent-x", "agent-y")
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@agent-x @agent-y ship it")

    assert result is not None
    # Mentions map to L9 recipients.
    assert result.recipients == ["agent-x", "agent-y"]

    # Exchange recipients match the mentions.
    channel_send = cast(MagicMock, managed.channel.send)
    channel_send.assert_awaited_once()
    envelope = channel_send.await_args.args[0]
    actor_ids = [a.id for a in envelope.header.participants.actors]
    assert actor_ids == ["avery", "agent-x", "agent-y"]
    assert envelope.header.kind.value == "exchange"

    # Persister ingests the message locally exactly once (transcript + bus feed).
    cast(MagicMock, managed.persister).ingest_local.assert_called_once()

    # agent-x is present (a wake, no invite); agent-y is absent (invited).
    bg.assert_called_once_with(_ROOM, "agent-y")


@pytest.mark.asyncio
async def test_publish_human_returns_none_without_a_live_channel():
    manager = RoomChannelManager(endpoint="http://127.0.0.1:46357", default_workspace="mycelium")
    assert await manager.publish_human("no-such-room", sender="avery", text="@x hi") is None


@pytest.mark.asyncio
async def test_publish_human_treats_await_lease_holder_as_present(monkeypatch):
    """A bare-CLI agent long-polling ``await`` holds a presence lease but no SLIM
    membership. An @-mention of it must be a wake (delivered via the transcript its
    poll reads), not an invite."""
    manager, _managed = _manager_with_channel(members=set())
    _registered(monkeypatch, "workpc")
    manager.refresh_lease(_ROOM, "workpc")  # an active `await` long-poll
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@workpc ping")

    assert result is not None
    bg.assert_not_called()  # present via lease → wake, nothing to admit


def test_status_members_include_await_leases():
    """status() reports the roster the mediator sees — SLIM members plus live
    leases — so a server-held ``await`` participant is visible on ``/health``."""
    manager, _managed = _manager_with_channel(members={"agent-x"})
    manager.refresh_lease(_ROOM, "workpc")

    entry = next(r for r in manager.status()["rooms"] if r["room"] == _ROOM)
    assert set(entry["members"]) == {"agent-x", "workpc"}


# ── the manifest gate: only a room's own agents are admitted by a mention ─────


@pytest.mark.asyncio
async def test_mention_of_a_handle_without_a_manifest_admits_nobody(monkeypatch):
    """Mentioning a human — including yourself — is addressing, not admitting.

    A human in the browser holds neither SLIM membership nor an ``await`` lease, so
    they are never "present"; without the manifest check every message naming one
    (an agent replying to you, you naming yourself) would try to admit them.
    """
    manager, _managed = _manager_with_channel(members=set())
    _registered(monkeypatch)  # nobody has a manifest
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@avery @dana @typo look")

    assert result is not None
    assert result.recipients == ["avery", "dana", "typo"]  # still addressed ...
    bg.assert_not_called()  # ... and none of them admitted
    assert manager._deferred_invites == {}


@pytest.mark.asyncio
async def test_own_agent_mention_outside_episode_invites_immediately(monkeypatch):
    """No active episode: a registered agent joins directly, off the request path."""
    manager, _managed = _manager_with_channel(members=set())
    _registered(monkeypatch, "mine")
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]

    result = await manager.publish_human(_ROOM, sender="avery", text="@mine hi")

    assert result is not None
    bg.assert_called_once_with(_ROOM, "mine")
    assert manager._deferred_invites == {}  # nothing deferred


# ── mid-episode: the invite is deferred until the episode closes ──────────────


@pytest.mark.asyncio
async def test_mid_episode_invite_is_deferred_then_flushed_on_close(monkeypatch):
    """A registered agent @-mentioned while an episode is active must NOT be
    invited directly — that membership change would abort the episode. It is held
    and applied once the episode closes."""
    manager, _managed = _manager_with_channel(members={"agent-a"})
    _registered(monkeypatch, "dave")
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]
    bg = MagicMock()
    manager.invite_in_background = bg  # type: ignore[method-assign]
    manager.open_episode(_ROOM, "urn:ioc:mycelium:episode:step6-room:e1")

    result = await manager.publish_human(_ROOM, sender="avery", text="@dave join us")
    assert result is not None
    bg.assert_not_called()  # not invited directly mid-episode ...
    invite_mock.assert_not_awaited()
    assert manager._deferred_invites[_ROOM] == {"dave"}  # ... held instead

    # Closing the episode drains the queue → the deferred invite is applied.
    await manager.close_episode(_ROOM)
    invite_mock.assert_awaited_once_with(_ROOM, "dave")
    assert manager._deferred_invites == {}


# ── the invitee is addressed by identity, not by host ─────────────────────────


@pytest.mark.asyncio
async def test_mention_invites_remote_agent_by_identity_only(monkeypatch):
    """The invite resolves the agent purely by its ``workspace/room/agent`` SLIM
    identity — never a host or endpoint — so the moderator invites the same member
    whether its connector runs on this machine or another one on the shared node.
    This is why the mention → invite → join path needs no cross-machine mechanism:
    membership is identity-addressed.
    """
    manager, managed = _manager_with_channel(members=set())
    _registered(monkeypatch, "remote-bob")

    # Bindings aren't installed in the task env; record the identity the invite
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
    await asyncio.gather(*manager._tasks)  # the invite runs off the request path

    # Addressed by identity only (no host/endpoint) — host-independent membership.
    assert resolved == [("mycelium", _ROOM, "remote-bob")]
    cast(AsyncMock, managed.client.invite).assert_awaited_once()
    assert "remote-bob" in managed.members


# ── episode abort: recorded locally + deferred invites flushed ─────────────────


@pytest.mark.asyncio
async def test_episode_abort_ingests_locally_and_flushes_queue(monkeypatch):
    """A mid-episode membership change aborts the episode: the abort is broadcast
    AND ingested locally (so the transcript/UI see it, independent of SLIM
    loopback), and invites deferred during the episode are applied once it closes."""
    manager, managed = _manager_with_channel(members={"agent-a", "agent-b"})
    _registered(monkeypatch, "dave")
    invite_mock = AsyncMock(return_value=True)
    manager.invite = invite_mock  # type: ignore[method-assign]
    manager.open_episode(_ROOM, "urn:ioc:mycelium:episode:step6-room:e1")

    # A mention mid-episode is deferred, not applied.
    result = await manager.publish_human(_ROOM, sender="avery", text="@dave join")
    assert result is not None
    assert manager._deferred_invites[_ROOM] == {"dave"}

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
    # The deferred invite is applied now the episode is closed.
    invite_mock.assert_awaited_once_with(_ROOM, "dave")
    assert not managed.lifecycle.active
