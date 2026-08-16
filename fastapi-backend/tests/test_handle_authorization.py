# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle authorization: whose queue a token may drain, whose presence it may claim.

Binding (``test_handle_binding``) fixed *authorship*; this fixes *access*. The
handle on ``await`` and on the presence join is a request parameter naming someone
else's coordination stream, so the question is not "who wrote this" but "may this
principal act for that handle" — its own, or one whose manifest granted it.

Both halves are asserted: with a principal the grant decides, and with none every
path behaves exactly as it did before the gate existed.
"""

from __future__ import annotations

import pytest
import yaml
from httpx import AsyncClient

from app.services import principals
from app.services.filesystem import get_room_dir, room_exists, write_memory_file

ROOM = "authz-room"


async def _make_room(client: AsyncClient, name: str = ROOM) -> None:
    assert (await client.post("/api/rooms", json={"name": name})).status_code in (200, 201)


def _seed_agent(
    handle: str,
    *,
    room: str = ROOM,
    owner: str | None = None,
    allow_from: list[str] | None = None,
) -> None:
    """Register an agent manifest carrying whatever delegation the test needs."""
    body: dict[str, object] = {"adapter": "claude_code"}
    if owner is not None:
        body["owner"] = owner
    if allow_from is not None:
        body["allow_from"] = allow_from
    write_memory_file(
        get_room_dir(room),
        f"agents/{handle}",
        yaml.safe_dump(body, sort_keys=False),
        created_by="tester",
    )


async def _await_as(client: AsyncClient, handle: str, *, room: str = ROOM):
    """One long-poll. No SLIM node in the unit suite, so it returns immediately."""
    return await client.get(f"/api/rooms/{room}/await", params={"handle": handle, "timeout": 1})


async def _join_as(client: AsyncClient, handle: str, *, room: str = ROOM):
    return await client.post(f"/api/rooms/{room}/sessions", json={"agent_handle": handle})


# ── no principal: today's behavior, unchanged ─────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_await_may_drain_any_handle(client: AsyncClient):
    """The ungated hub is untouched — this is the try-it path."""
    await _make_room(client)
    assert (await _await_as(client, "alice")).status_code == 200


@pytest.mark.asyncio
async def test_gate_off_leaves_await_open(client: AsyncClient, as_principal):
    """The override is installed but resolves to no principal — the gate-off path."""
    as_principal(None)
    await _make_room(client)
    assert (await _await_as(client, "alice")).status_code == 200


@pytest.mark.asyncio
async def test_anonymous_join_may_claim_any_handle(client: AsyncClient):
    await _make_room(client)
    assert (await _join_as(client, "alice")).status_code == 201


# ── await: the queue is the token's own, or a granted one ─────────────────────


@pytest.mark.asyncio
async def test_a_token_may_drain_its_own_queue(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    assert (await _await_as(client, "alice")).status_code == 200


@pytest.mark.asyncio
async def test_a_token_may_not_drain_another_handles_queue(client: AsyncClient, as_principal):
    """The gap this closes: @bob long-polling @alice's coordination stream."""
    await _make_room(client)
    _seed_agent("alice")
    as_principal("bob")
    resp = await _await_as(client, "alice")
    assert resp.status_code == 403
    assert "alice" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_an_unregistered_handle_is_not_drainable_either(client: AsyncClient, as_principal):
    """No manifest means no grant — a phantom handle is not an open queue."""
    await _make_room(client)
    as_principal("bob")
    assert (await _await_as(client, "nobody")).status_code == 403


@pytest.mark.asyncio
async def test_the_owner_may_drain_its_agents_queue(client: AsyncClient, as_principal):
    """The human-proxy path: `mycelium await --handle bot` run by bot's owner."""
    await _make_room(client)
    _seed_agent("bot", owner="alice")
    as_principal("alice", role="user")
    assert (await _await_as(client, "bot")).status_code == 200


@pytest.mark.asyncio
async def test_allow_from_grants_a_non_owner(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent("bot", owner="alice", allow_from=["carol"])
    as_principal("carol")
    assert (await _await_as(client, "bot")).status_code == 200


@pytest.mark.asyncio
async def test_a_grant_to_someone_else_is_not_a_grant_to_you(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent("bot", owner="alice", allow_from=["carol"])
    as_principal("mallory")
    assert (await _await_as(client, "bot")).status_code == 403


@pytest.mark.asyncio
async def test_a_grant_is_scoped_to_the_room_it_is_written_in(client: AsyncClient, as_principal):
    """Manifests are per-room, so owning @bot in one room says nothing about another."""
    await _make_room(client)
    await _make_room(client, "other-room")
    _seed_agent("bot", room="other-room", owner="alice")
    _seed_agent("bot")
    as_principal("alice")
    assert (await _await_as(client, "bot", room="other-room")).status_code == 200
    assert (await _await_as(client, "bot")).status_code == 403


@pytest.mark.asyncio
async def test_handles_are_compared_normalized(client: AsyncClient, as_principal):
    """``@Alice`` in a manifest and ``alice`` on a token are one principal."""
    await _make_room(client)
    _seed_agent("bot", owner="@Alice")
    as_principal("alice")
    assert (await _await_as(client, "@Bot")).status_code == 200


@pytest.mark.asyncio
async def test_a_session_qualifier_still_names_its_own_queue(client: AsyncClient, as_principal):
    """``alice#a8f3`` is alice on one machine — her own queue, not a second actor's."""
    await _make_room(client)
    as_principal("alice")
    assert (await _await_as(client, "alice#a8f3")).status_code == 200


@pytest.mark.asyncio
async def test_a_session_qualifier_cannot_smuggle_another_queue(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent("mallory")
    as_principal("alice")
    assert (await _await_as(client, "mallory#a8f3")).status_code == 403


@pytest.mark.asyncio
async def test_an_empty_handle_names_no_queue(client: AsyncClient, as_principal):
    """Unlike an omitted write actor, a blank parameter is not a claim to fill in."""
    await _make_room(client)
    as_principal("alice")
    assert (await _await_as(client, "")).status_code == 403


# ── presence: registering as a handle is the same claim ───────────────────────


@pytest.mark.asyncio
async def test_a_token_may_join_as_itself(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    assert (await _join_as(client, "alice")).status_code == 201


@pytest.mark.asyncio
async def test_a_token_may_not_join_as_another_handle(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent("alice")
    as_principal("bob")
    resp = await _join_as(client, "alice")
    assert resp.status_code == 403
    # The refusal is a refusal: no roster entry landed under either handle.
    listed = await client.get(f"/api/rooms/{ROOM}/sessions")
    assert listed.json()["participants"] == []


@pytest.mark.asyncio
async def test_the_owner_may_register_presence_for_its_agent(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent("bot", owner="alice")
    as_principal("alice", role="user")
    resp = await _join_as(client, "bot")
    assert resp.status_code == 201
    assert resp.json()["agent_handle"] == "bot"


@pytest.mark.asyncio
async def test_a_refused_join_does_not_create_the_room(client: AsyncClient, as_principal):
    """Join creates its room on demand, so the claim is checked before anything is."""
    as_principal("bob")
    assert (await _join_as(client, "alice", room="ghost-room")).status_code == 403
    assert not room_exists("ghost-room")


# ── the rule itself ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegates_to_reads_only_explicit_grants(client: AsyncClient):
    await _make_room(client)
    _seed_agent("bot", owner="alice", allow_from=["carol"])
    _seed_agent("loner")
    assert principals.delegates_to(ROOM, "bot", "alice")
    assert principals.delegates_to(ROOM, "bot", "@Carol")
    assert not principals.delegates_to(ROOM, "bot", "mallory")
    assert not principals.delegates_to(ROOM, "loner", "alice")
    assert not principals.delegates_to(ROOM, "unregistered", "alice")
    assert not principals.delegates_to(ROOM, "bot", "")
