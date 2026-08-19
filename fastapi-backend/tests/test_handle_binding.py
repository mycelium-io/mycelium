# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle binding: a verified token is the actor of record.

The gate proves a token; binding decides *who wrote this*. Both halves are
asserted here — with a principal the token's handle lands in the store and a body
claiming someone else is refused, and with no principal every path behaves
exactly as it did before the gate existed (the default posture, and the one that
keeps the try-it path working).

The principal is injected by overriding the gate dependency rather than by
signing a token: the token itself is ``test_auth_gate``'s subject, and the
end-to-end pass from a real signature through to a stored author lives there too.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from httpx import AsyncClient

from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
from app.services.persister import DeliveryLog

ROOM = "bind-room"


async def _make_room(client: AsyncClient, name: str = ROOM) -> None:
    assert (await client.post("/api/rooms", json={"name": name})).status_code in (200, 201)


async def _write(client: AsyncClient, *, key: str, created_by: str, room: str = ROOM):
    return await client.post(
        f"/api/rooms/{room}/memory",
        json={"items": [{"key": key, "value": "v", "created_by": created_by, "embed": False}]},
    )


def _seed_agent(
    room: str, handle: str, *, adapter: str = "claude_code", owner: str | None = None
) -> None:
    manifest: dict[str, Any] = {"adapter": adapter}
    if owner is not None:
        manifest["owner"] = owner
    write_memory_file(
        get_room_dir(room),
        f"agents/{handle}",
        yaml.safe_dump(manifest, sort_keys=False),
        created_by="tester",
    )


def _stored_meta(room: str, key: str) -> dict[str, Any]:
    """The frontmatter of a memory that must exist."""
    stored = read_memory_file(get_room_dir(room), key)
    assert stored is not None, f"{key} was not written"
    return stored[0]


# ── no principal: today's behavior, unchanged ─────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_memory_write_keeps_its_self_asserted_author(client: AsyncClient):
    await _make_room(client)
    resp = await _write(client, key="notes/a", created_by="whoever")
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "whoever"


@pytest.mark.asyncio
async def test_gate_off_leaves_the_body_actor_alone(client: AsyncClient, as_principal):
    """The override is installed but resolves to no principal — the gate-off path."""
    as_principal(None)
    await _make_room(client)
    resp = await _write(client, key="notes/a", created_by="whoever")
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "whoever"


@pytest.mark.asyncio
async def test_anonymous_message_keeps_its_self_asserted_sender(client: AsyncClient):
    await _make_room(client)
    resp = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"message_type": "broadcast", "sender_handle": "whoever", "content": "hi"},
    )
    assert resp.status_code == 201
    assert resp.json()["sender_handle"] == "whoever"


# ── a principal is the author ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_author_comes_from_the_token(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await _write(client, key="notes/a", created_by="alice")
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "alice"

    # …and it is what actually landed on disk, not just what was echoed back.
    assert _stored_meta(ROOM, "notes/a")["created_by"] == "alice"


@pytest.mark.asyncio
async def test_a_body_claiming_another_handle_is_refused(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await _write(client, key="notes/mallory", created_by="mallory")
    assert resp.status_code == 403
    assert "mallory" in resp.json()["detail"]
    # The refusal is a refusal: nothing was written under either handle.
    assert read_memory_file(get_room_dir(ROOM), "notes/mallory") is None


@pytest.mark.asyncio
async def test_one_impersonating_item_refuses_the_whole_batch(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await client.post(
        f"/api/rooms/{ROOM}/memory",
        json={
            "items": [
                {"key": "notes/ok", "value": "v", "created_by": "alice", "embed": False},
                {"key": "notes/bad", "value": "v", "created_by": "mallory", "embed": False},
            ]
        },
    )
    assert resp.status_code == 403
    assert read_memory_file(get_room_dir(ROOM), "notes/ok") is None


@pytest.mark.asyncio
async def test_an_omitted_or_differently_written_handle_still_matches(
    client: AsyncClient, as_principal
):
    """``@Alice`` and ``alice`` are one principal — normalization is shared with the store."""
    await _make_room(client)
    as_principal("alice")
    resp = await _write(client, key="notes/cased", created_by="@Alice")
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "alice"


@pytest.mark.asyncio
async def test_a_session_qualifier_rides_along(client: AsyncClient, as_principal):
    """``alice#a8f3`` is alice on one machine, not a second actor."""
    await _make_room(client)
    as_principal("alice")
    resp = await _write(client, key="notes/session", created_by="alice#a8f3")
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "alice#a8f3"


@pytest.mark.asyncio
async def test_a_session_qualifier_cannot_smuggle_another_handle(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await _write(client, key="notes/smuggle", created_by="mallory#a8f3")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_an_update_records_the_token_as_updated_by(client: AsyncClient, as_principal):
    """``created_by`` stays with the original author; the token owns ``updated_by``."""
    await _make_room(client)
    assert (await _write(client, key="notes/shared", created_by="bob")).status_code == 201

    as_principal("alice")
    resp = await _write(client, key="notes/shared", created_by="alice")
    assert resp.status_code == 201
    body = resp.json()[0]
    assert body["version"] == 2
    assert body["created_by"] == "bob"
    assert body["updated_by"] == "alice"


# ── transcript sender + L9 actor ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_sender_comes_from_the_token(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"message_type": "broadcast", "sender_handle": "@Alice", "content": "hi"},
    )
    assert resp.status_code == 201
    assert resp.json()["sender_handle"] == "alice"


@pytest.mark.asyncio
async def test_message_claiming_another_sender_is_refused(client: AsyncClient, as_principal):
    await _make_room(client)
    as_principal("alice")
    resp = await client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"message_type": "broadcast", "sender_handle": "mallory", "content": "hi"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reply_claiming_another_handle_is_refused(client: AsyncClient, as_principal):
    await _make_room(client)
    _seed_agent(ROOM, "mallory")
    as_principal("alice")
    resp = await client.post(f"/api/rooms/{ROOM}/reply", json={"handle": "mallory", "text": "hi"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reply_as_an_owned_agent_is_allowed(client: AsyncClient, as_principal, monkeypatch):
    """Regression (#657): await_message already honored owner/allow_from
    delegation via authorize_handle; post_reply used the stricter, delegation-
    blind bind_actor instead, so an agent's owner could watch for its turns but
    never actually post the reply as it. mallory owns the agent here, so replying
    as it must succeed even though mallory isn't the agent's own literal handle.
    """
    from app.services import room_channels

    class _Persister:
        def __init__(self) -> None:
            self.log = DeliveryLog([])
            self.ingested: list[Any] = []

        def ingest_local(self, envelope: Any, content: dict, list_write: bool = False) -> None:
            self.ingested.append(envelope)

    class _Channel:
        async def send(self, envelope: Any, *, extra: dict | None = None) -> None:
            return None

    class _Managed:
        def __init__(self) -> None:
            self.channel = _Channel()
            self.persister = _Persister()

    managed = _Managed()

    class _Manager:
        async def provision(self, room: str, **_kw: Any) -> _Managed:
            return managed

        def refresh_lease(self, room: str, handle: str) -> None:
            return None

        async def send_as_custodian(self, room: str, handle: str, data: bytes) -> bool:
            # PSK default: no custodial session, so the reply falls back to a moderator send.
            return False

    monkeypatch.setattr(room_channels, "manager", _Manager())

    await _make_room(client)
    _seed_agent(ROOM, "owned-agent", owner="mallory")
    as_principal("mallory")
    resp = await client.post(
        f"/api/rooms/{ROOM}/reply", json={"handle": "owned-agent", "text": "hi"}
    )
    assert resp.status_code == 200
    assert resp.json()["handle"] == "owned-agent"


@pytest.mark.asyncio
async def test_reply_stamps_the_token_handle_on_the_l9_actor(
    client: AsyncClient, as_principal, monkeypatch
):
    """The published envelope names the token's handle, whatever the body said."""
    from app.services import room_channels

    class _Persister:
        def __init__(self) -> None:
            self.log = DeliveryLog([])
            self.ingested: list[Any] = []

        def ingest_local(self, envelope: Any, content: dict, list_write: bool = False) -> None:
            self.ingested.append(envelope)

    class _Channel:
        async def send(self, envelope: Any, *, extra: dict | None = None) -> None:
            return None

    class _Managed:
        def __init__(self) -> None:
            self.channel = _Channel()
            self.persister = _Persister()

    managed = _Managed()

    class _Manager:
        async def provision(self, room: str, **_kw: Any) -> _Managed:
            return managed

        def refresh_lease(self, room: str, handle: str) -> None:
            return None

        async def send_as_custodian(self, room: str, handle: str, data: bytes) -> bool:
            # PSK default: no custodial session, so the reply falls back to a moderator send.
            return False

    monkeypatch.setattr(room_channels, "manager", _Manager())

    await _make_room(client)
    _seed_agent(ROOM, "alice")
    as_principal("alice")
    resp = await client.post(f"/api/rooms/{ROOM}/reply", json={"handle": "@Alice", "text": "x"})
    assert resp.status_code == 200
    assert resp.json()["handle"] == "alice"

    envelope = managed.persister.ingested[0]
    assert envelope.header.participants.actors[0].id == "alice"


# ── engine registration ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_registrar_defaults_to_the_web_ui_when_anonymous(client: AsyncClient):
    await _make_room(client)
    resp = await client.post(f"/api/rooms/{ROOM}/engines", json={"handle": "aligner"})
    assert resp.status_code == 201
    assert _stored_meta(ROOM, "agents/aligner")["created_by"] == "web-ui"


@pytest.mark.asyncio
async def test_engine_registrar_comes_from_the_token(client: AsyncClient, as_principal):
    """An omitted ``created_by`` is filled by the token, not read as impersonation."""
    await _make_room(client)
    as_principal("alice")
    resp = await client.post(f"/api/rooms/{ROOM}/engines", json={"handle": "aligner"})
    assert resp.status_code == 201
    assert _stored_meta(ROOM, "agents/aligner")["created_by"] == "alice"


@pytest.mark.asyncio
async def test_engine_registrar_claiming_another_handle_is_refused(
    client: AsyncClient, as_principal
):
    await _make_room(client)
    as_principal("alice")
    resp = await client.post(
        f"/api/rooms/{ROOM}/engines", json={"handle": "aligner", "created_by": "mallory"}
    )
    assert resp.status_code == 403
