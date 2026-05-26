# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Cascade-delete invariants for the room → coord-session → participant chain.

The chain is:
    rooms.name → coordination_sessions.parent_room_name (CASCADE)
              → participants.coordination_session_id    (CASCADE)
              → messages.coordination_session_id        (CASCADE)
              → messages.room_name                      (CASCADE)

Deleting a room must take everything below it.
"""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoordinationSession, Message, Participant, Room


async def _counts(db: AsyncSession) -> dict:
    return {
        "rooms": (await db.execute(select(func.count()).select_from(Room))).scalar(),
        "coord": (await db.execute(select(func.count()).select_from(CoordinationSession))).scalar(),
        "participants": (await db.execute(select(func.count()).select_from(Participant))).scalar(),
        "messages": (await db.execute(select(func.count()).select_from(Message))).scalar(),
    }


@pytest.mark.asyncio
async def test_delete_room_cascades_to_coord_sessions_participants_messages(
    client: AsyncClient, db_session: AsyncSession
):
    """Deleting a parent room cascades through the entire chain."""
    await client.post("/api/rooms", json={"name": "parent"})
    await client.post(
        "/api/rooms/parent/sessions",
        json={"agent_handle": "alice", "intent": "x"},
    )
    await client.post(
        "/api/rooms/parent/sessions",
        json={"agent_handle": "bob", "intent": "y"},
    )
    coord = (await client.get("/api/rooms/parent/sessions/coordination")).json()[0]
    sid = coord["id"]
    display = coord["display_name"]

    # Two flavors of session-bound message: one via the new endpoint, one via
    # the legacy display-name URL. The polymorphic FK should pick them both up.
    await client.post(
        f"/api/coordination-sessions/{sid}/messages",
        json={"sender_handle": "alice", "message_type": "direct", "content": "hi"},
    )
    await client.post(
        f"/api/rooms/{display}/messages",
        json={"sender_handle": "bob", "message_type": "direct", "content": "lo"},
    )

    before = await _counts(db_session)
    assert before["rooms"] == 1
    assert before["coord"] == 1
    assert before["participants"] == 2
    # 4 = 2 coordination_join audit rows (one per join) + 2 direct chat messages.
    assert before["messages"] == 4

    resp = await client.delete("/api/rooms/parent")
    assert resp.status_code == 204

    await db_session.commit()  # ensure we see the cascade
    after = await _counts(db_session)
    assert after == {"rooms": 0, "coord": 0, "participants": 0, "messages": 0}


@pytest.mark.asyncio
async def test_delete_room_does_not_cascade_to_unrelated_rooms(
    client: AsyncClient, db_session: AsyncSession
):
    """A delete on one room must not touch sibling rooms or their sessions."""
    await client.post("/api/rooms", json={"name": "a"})
    await client.post("/api/rooms", json={"name": "b"})
    await client.post(
        "/api/rooms/a/sessions",
        json={"agent_handle": "alice", "intent": "x"},
    )
    await client.post(
        "/api/rooms/b/sessions",
        json={"agent_handle": "bob", "intent": "y"},
    )

    resp = await client.delete("/api/rooms/a")
    assert resp.status_code == 204

    after = await _counts(db_session)
    # b plus its coord_session, participant, and bob's coordination_join row
    # must remain — a's row was reaped, b's was not.
    assert after == {"rooms": 1, "coord": 1, "participants": 1, "messages": 1}


@pytest.mark.asyncio
async def test_delete_coord_session_cascades_to_participants_and_messages(
    client: AsyncClient, db_session: AsyncSession
):
    """Deleting a CoordinationSession alone reaps its participants + messages."""
    await client.post("/api/rooms", json={"name": "p"})
    await client.post(
        "/api/rooms/p/sessions",
        json={"agent_handle": "alice", "intent": "x"},
    )
    coord = (await client.get("/api/rooms/p/sessions/coordination")).json()[0]
    sid = coord["id"]
    await client.post(
        f"/api/coordination-sessions/{sid}/messages",
        json={"sender_handle": "alice", "message_type": "direct", "content": "hi"},
    )

    # Delete the coord session row directly via the DB.
    coord_row = (
        await db_session.execute(
            select(CoordinationSession).where(CoordinationSession.id == UUID(coord["id"]))
        )
    ).scalar_one()
    await db_session.delete(coord_row)
    await db_session.commit()

    after = await _counts(db_session)
    # The room itself stays; its coord_session, participants, messages don't.
    assert after == {"rooms": 1, "coord": 0, "participants": 0, "messages": 0}


@pytest.mark.asyncio
async def test_delete_room_keeps_namespace_messages_no_dangling_fks(
    client: AsyncClient, db_session: AsyncSession
):
    """Namespace-level (non-session) messages are deleted with the parent room."""
    await client.post("/api/rooms", json={"name": "ns"})
    # Direct chat in the namespace room — uses room_name, not coord_session.
    await client.post(
        "/api/rooms/ns/messages",
        json={"sender_handle": "alice", "message_type": "direct", "content": "lobby"},
    )

    before = await _counts(db_session)
    assert before["messages"] == 1

    await client.delete("/api/rooms/ns")
    after = await _counts(db_session)
    assert after == {"rooms": 0, "coord": 0, "participants": 0, "messages": 0}
