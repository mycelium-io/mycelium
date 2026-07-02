# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the typed ``event`` message primitive (#392)."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Message, Room
from app.services.event_sweep import sweep_expired_events


@pytest_asyncio.fixture()
async def room(db_session):
    r = Room(name="platform-eng")
    db_session.add(r)
    await db_session.commit()
    return r


def _event_body(**meta_overrides):
    metadata = {
        "kind": "source_event",
        "payload": {"source": "github", "event": "pr_opened", "number": 48},
        "provenance": [
            {"type": "pr", "ref": "org/repo#48", "url": "https://github.com/org/repo/pull/48"}
        ],
        **meta_overrides,
    }
    return {
        "sender_handle": "github-poller",
        "message_type": "event",
        "content": 'New PR: "fix recordings window" (#48)',
        "metadata": metadata,
    }


# ── POST ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_event_stores_and_returns_metadata(client, room):
    resp = await client.post("/api/rooms/platform-eng/messages", json=_event_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["message_type"] == "event"
    assert body["metadata"]["kind"] == "source_event"
    assert body["metadata"]["provenance"][0]["ref"] == "org/repo#48"
    assert body["metadata"]["payload"]["number"] == 48


@pytest.mark.asyncio
async def test_post_event_requires_metadata(client, room):
    body = _event_body()
    del body["metadata"]
    resp = await client.post("/api/rooms/platform-eng/messages", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_non_event_rejects_metadata(client, room):
    body = _event_body()
    body["message_type"] = "broadcast"
    resp = await client.post("/api/rooms/platform-eng/messages", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_source_event_rejects_status(client, room):
    resp = await client.post("/api/rooms/platform-eng/messages", json=_event_body(status="open"))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_action_defaults_to_open(client, room):
    resp = await client.post(
        "/api/rooms/platform-eng/messages",
        json=_event_body(kind="action", payload={"task": "rotate creds"}),
    )
    assert resp.status_code == 201
    assert resp.json()["metadata"]["status"] == "open"


@pytest.mark.asyncio
async def test_ttl_sets_expiry_column(client, room, db_session):
    resp = await client.post("/api/rooms/platform-eng/messages", json=_event_body(ttl_seconds=3600))
    assert resp.status_code == 201
    msg = (await db_session.execute(select(Message))).scalars().one()
    assert msg.event_expires_at is not None
    assert msg.event_kind == "source_event"


@pytest.mark.asyncio
async def test_durable_event_has_no_expiry(client, room, db_session):
    resp = await client.post("/api/rooms/platform-eng/messages", json=_event_body(kind="concern"))
    assert resp.status_code == 201
    msg = (await db_session.execute(select(Message))).scalars().one()
    assert msg.event_expires_at is None
    assert msg.event_status == "open"


@pytest.mark.asyncio
async def test_legacy_message_types_unchanged(client, room, db_session):
    resp = await client.post(
        "/api/rooms/platform-eng/messages",
        json={"sender_handle": "a1", "message_type": "broadcast", "content": "hello"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["metadata"] is None
    msg = (await db_session.execute(select(Message))).scalars().one()
    assert msg.event_kind is None and msg.event_status is None


# ── GET filters ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kind_and_status_filters(client, room):
    await client.post("/api/rooms/platform-eng/messages", json=_event_body())
    await client.post(
        "/api/rooms/platform-eng/messages", json=_event_body(kind="action", payload={})
    )
    await client.post(
        "/api/rooms/platform-eng/messages",
        json={"sender_handle": "a1", "message_type": "broadcast", "content": "chat"},
    )

    resp = await client.get("/api/rooms/platform-eng/messages?kind=source_event")
    assert [m["metadata"]["kind"] for m in resp.json()["messages"]] == ["source_event"]

    resp = await client.get("/api/rooms/platform-eng/messages?kind=action&status=open")
    assert len(resp.json()["messages"]) == 1

    resp = await client.get("/api/rooms/platform-eng/messages?status=resolved")
    assert resp.json()["messages"] == []


@pytest.mark.asyncio
async def test_since_filter(client, room):
    await client.post("/api/rooms/platform-eng/messages", json=_event_body())
    from urllib.parse import quote

    future = quote((datetime.now(UTC) + timedelta(hours=1)).isoformat())
    resp = await client.get(f"/api/rooms/platform-eng/messages?since={future}")
    assert resp.json()["messages"] == []


@pytest.mark.asyncio
async def test_expired_events_hidden_from_get(client, room, db_session):
    await client.post("/api/rooms/platform-eng/messages", json=_event_body(ttl_seconds=3600))
    msg = (await db_session.execute(select(Message))).scalars().one()
    msg.event_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    resp = await client.get("/api/rooms/platform-eng/messages")
    assert resp.json()["messages"] == []


# ── status transitions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_transition(client, room):
    resp = await client.post(
        "/api/rooms/platform-eng/messages", json=_event_body(kind="action", payload={})
    )
    msg_id = resp.json()["id"]

    resp = await client.patch(
        f"/api/rooms/platform-eng/messages/{msg_id}", json={"status": "resolved"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metadata"]["status"] == "resolved"
    assert "status_updated_at" in body["metadata"]

    # Queryable via the ledger filter.
    resp = await client.get("/api/rooms/platform-eng/messages?kind=action&status=resolved")
    assert len(resp.json()["messages"]) == 1
    resp = await client.get("/api/rooms/platform-eng/messages?kind=action&status=open")
    assert resp.json()["messages"] == []


@pytest.mark.asyncio
async def test_status_transition_rejected_for_stateless(client, room):
    resp = await client.post("/api/rooms/platform-eng/messages", json=_event_body())
    msg_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/rooms/platform-eng/messages/{msg_id}", json={"status": "resolved"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_status_transition_rejected_for_non_event(client, room):
    resp = await client.post(
        "/api/rooms/platform-eng/messages",
        json={"sender_handle": "a1", "message_type": "broadcast", "content": "chat"},
    )
    msg_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/rooms/platform-eng/messages/{msg_id}", json={"status": "resolved"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_status_transition_404_for_wrong_room(client, room, db_session):
    other = Room(name="other-room")
    db_session.add(other)
    await db_session.commit()
    resp = await client.post(
        "/api/rooms/platform-eng/messages", json=_event_body(kind="action", payload={})
    )
    msg_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/rooms/other-room/messages/{msg_id}", json={"status": "resolved"}
    )
    assert resp.status_code == 404


# ── TTL sweep ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_deletes_only_expired(client, room, db_session, monkeypatch):
    from app.services import event_sweep

    await client.post("/api/rooms/platform-eng/messages", json=_event_body(ttl_seconds=3600))
    await client.post(
        "/api/rooms/platform-eng/messages", json=_event_body(kind="action", payload={})
    )
    msgs = (await db_session.execute(select(Message))).scalars().all()
    for m in msgs:
        if m.event_expires_at is not None:
            m.event_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    # Point the sweep's session maker at the test database.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(
        event_sweep,
        "async_session_maker",
        async_sessionmaker(db_session.bind, expire_on_commit=False),
    )
    removed = await sweep_expired_events()
    assert removed == 1

    remaining = (await db_session.execute(select(Message))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].event_kind == "action"
