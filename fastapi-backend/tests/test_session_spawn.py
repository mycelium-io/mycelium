# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for coordination session spawning."""

import json
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoordinationSession, Message


async def _coord_for_room(client: AsyncClient, namespace: str) -> dict:
    """Return the most recent CoordinationSession dict for a namespace room."""
    resp = await client.get(f"/api/rooms/{namespace}/sessions/coordination")
    rows = resp.json()
    assert rows, f"no coordination sessions for {namespace}"
    return rows[0]


@pytest.mark.asyncio
async def test_create_room_defaults(client: AsyncClient):
    """Creating a room defaults to a persistent namespace."""
    resp = await client.post("/api/rooms", json={"name": "no-mode-test"})
    assert resp.status_code == 201
    assert resp.json()["is_persistent"] is True


@pytest.mark.asyncio
async def test_join_namespace_auto_spawns_session(client: AsyncClient):
    """Joining a room auto-spawns a coordination session."""
    await client.post("/api/rooms", json={"name": "ns-test"})

    resp = await client.post(
        "/api/rooms/ns-test/sessions",
        json={"agent_handle": "agent-a", "intent": "Let's negotiate"},
    )
    assert resp.status_code == 201
    coord = await _coord_for_room(client, "ns-test")
    assert resp.json()["coordination_session_id"] == coord["id"]
    assert coord["display_name"].startswith("ns-test:session:")


@pytest.mark.asyncio
async def test_join_persists_coordination_join_message_with_intent(
    client: AsyncClient, db_session: AsyncSession
):
    """The join handler writes a coordination_join Message carrying the intent.

    Auditing what positions agents brought into a negotiation has to survive
    past the live SSE NOTIFY — catchup readers (the messages API, the
    frontend on first load) only see persisted rows. Without this Message
    the opening position is unrecoverable after the connect window closes.
    """
    await client.post("/api/rooms", json={"name": "audit-ns"})
    await client.post(
        "/api/rooms/audit-ns/sessions",
        json={"agent_handle": "alice", "intent": "ship a tight scope this quarter"},
    )

    rows = (
        (
            await db_session.execute(
                select(Message).where(Message.message_type == "coordination_join")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    payload = json.loads(rows[0].content)
    assert payload == {"handle": "alice", "intent": "ship a tight scope this quarter"}
    assert rows[0].coordination_session_id is not None
    assert rows[0].sender_handle == "CognitiveEngine"


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session(client: AsyncClient):
    """Multiple agents joining the same room land in the same coord session."""
    await client.post("/api/rooms", json={"name": "shared-ns"})

    resp1 = await client.post(
        "/api/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-1", "intent": "First"},
    )
    resp2 = await client.post(
        "/api/rooms/shared-ns/sessions",
        json={"agent_handle": "agent-2", "intent": "Second"},
    )
    assert resp1.json()["coordination_session_id"] == resp2.json()["coordination_session_id"]


@pytest.mark.asyncio
async def test_explicit_spawn(client: AsyncClient):
    """Explicitly spawning a coordination session."""
    await client.post("/api/rooms", json={"name": "spawn-ns"})

    resp = await client.post("/api/rooms/spawn-ns/sessions/spawn")
    assert resp.status_code == 201
    data = resp.json()
    assert data["parent"] == "spawn-ns"
    assert data["session_room"].startswith("spawn-ns:session:")
    assert "coordination_session_id" in data


@pytest.mark.asyncio
async def test_spawn_on_session_display_404(client: AsyncClient):
    """Spawning under a session display name returns 404 (no real room)."""
    await client.post("/api/rooms", json={"name": "parent-ns"})
    resp = await client.post("/api/rooms/parent-ns/sessions/spawn")
    session_name = resp.json()["session_room"]

    resp = await client.post(f"/api/rooms/{session_name}/sessions/spawn")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_join_transitions_coord_session_to_waiting(client: AsyncClient):
    """Joining transitions the coord session state machine to waiting."""
    await client.post("/api/rooms", json={"name": "wait-ns"})

    await client.post(
        "/api/rooms/wait-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "wait-ns")
    assert coord["state"] == "waiting"
    assert coord["join_window_ends_at"] is not None


@pytest.mark.asyncio
async def test_namespace_room_stays_idle_after_join(client: AsyncClient):
    """The room itself stays idle; only the coord session enters waiting."""
    await client.post("/api/rooms", json={"name": "idle-ns"})

    await client.post(
        "/api/rooms/idle-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )

    resp = await client.get("/api/rooms/idle-ns")
    assert resp.json()["coordination_state"] == "idle"


@pytest.mark.asyncio
async def test_new_session_after_complete(client: AsyncClient, db_session: AsyncSession):
    """Completing a session lets a fresh one spawn in the same namespace."""
    await client.post("/api/rooms", json={"name": "multi-session-ns"})

    resp1 = await client.post(
        "/api/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "round 1"},
    )
    coord1_id = resp1.json()["coordination_session_id"]

    await db_session.execute(
        sa_update(CoordinationSession)
        .where(CoordinationSession.id == UUID(coord1_id))
        .values(state="complete")
    )
    await db_session.commit()

    resp2 = await client.post(
        "/api/rooms/multi-session-ns/sessions",
        json={"agent_handle": "agent-b", "intent": "round 2"},
    )
    assert resp2.json()["coordination_session_id"] != coord1_id


@pytest.mark.asyncio
async def test_list_participants_via_session_display_name(client: AsyncClient):
    """List participants by session display name returns the joined agents."""
    await client.post("/api/rooms", json={"name": "list-ns"})

    await client.post(
        "/api/rooms/list-ns/sessions",
        json={"agent_handle": "alpha", "intent": "first"},
    )
    coord = await _coord_for_room(client, "list-ns")
    session_name = coord["display_name"]

    await client.post(
        "/api/rooms/list-ns/sessions",
        json={"agent_handle": "beta", "intent": "second"},
    )

    resp = await client.get(f"/api/rooms/{session_name}/sessions")
    data = resp.json()
    assert data["total"] == 2
    handles = {p["agent_handle"] for p in data["participants"]}
    assert handles == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_session_display_name_is_not_a_room(client: AsyncClient):
    """Session display names have no backing Room row — only a CoordinationSession."""
    await client.post("/api/rooms", json={"name": "check-ns"})

    await client.post(
        "/api/rooms/check-ns/sessions",
        json={"agent_handle": "agent-a", "intent": "testing"},
    )
    coord = await _coord_for_room(client, "check-ns")
    session_name = coord["display_name"]

    # Display names don't exist as Room rows — only as CoordinationSession entities.
    resp = await client.get(f"/api/rooms/{session_name}")
    assert resp.status_code == 404


# ── Regressions: idempotency + uniqueness guarantees ──────────────────────


@pytest.mark.asyncio
async def test_duplicate_join_same_handle_returns_one_participant(
    client: AsyncClient, db_session: AsyncSession
):
    """Regression #284: joining twice with the same handle MUST NOT create two
    Participant rows. The SKILL.md protocol tells agents to run
    ``mycelium session join`` themselves on top of the harness/CLI doing it,
    which used to double-count and corrupt NegMAS quorum.
    """
    from app.models import Participant

    await client.post("/api/rooms", json={"name": "dup-join-ns"})

    r1 = await client.post(
        "/api/rooms/dup-join-ns/sessions",
        json={"agent_handle": "bob", "intent": "first"},
    )
    r2 = await client.post(
        "/api/rooms/dup-join-ns/sessions",
        json={"agent_handle": "bob", "intent": "second-call"},
    )

    assert r1.status_code == 201
    assert r2.status_code == 201
    # Both calls return the SAME participant id — the second is a no-op
    # upsert that re-fetches the original row instead of inserting.
    assert r1.json()["id"] == r2.json()["id"]

    from sqlalchemy import select

    rows = (
        (await db_session.execute(select(Participant).where(Participant.agent_handle == "bob")))
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected one Participant for bob, found {len(rows)}"


@pytest.mark.asyncio
async def test_participant_unique_index_rejects_direct_duplicate_inserts(
    client: AsyncClient, db_session: AsyncSession
):
    """Regression #284: the unique index on
    ``participants(coordination_session_id, agent_handle)`` is the
    defense-in-depth backstop. Even bypassing the API guards (via direct
    ORM inserts in two separate transactions), the index must reject the
    second insert with IntegrityError.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models import Participant

    await client.post("/api/rooms", json={"name": "index-ns"})
    # Seed one participant via the API so a coord session exists.
    r = await client.post(
        "/api/rooms/index-ns/sessions",
        json={"agent_handle": "ada", "intent": "first"},
    )
    coord_id = UUID(r.json()["coordination_session_id"])

    dup = Participant(coordination_session_id=coord_id, agent_handle="ada", intent="x")
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_multiple_agents_join_same_session_no_fork(
    client: AsyncClient, db_session: AsyncSession
):
    """Regression #280: two different agents joining the same room must land in
    the SAME CoordinationSession — not fork into two non-terminal sessions.

    True concurrency is hard to exercise under the SQLite test client (one
    async connection serves overlapping requests, which deadlocks rather than
    races). The unique-index backstop is covered by the direct-insert test
    below; this case covers the common sequential SELECT-then-INSERT path
    that the application code takes for non-racing joins.
    """
    from sqlalchemy import select

    await client.post("/api/rooms", json={"name": "no-fork-ns"})

    r1 = await client.post(
        "/api/rooms/no-fork-ns/sessions",
        json={"agent_handle": "bob", "intent": "x"},
    )
    r2 = await client.post(
        "/api/rooms/no-fork-ns/sessions",
        json={"agent_handle": "julie", "intent": "y"},
    )
    assert r1.json()["coordination_session_id"] == r2.json()["coordination_session_id"]

    rows = (
        (
            await db_session.execute(
                select(CoordinationSession).where(
                    CoordinationSession.parent_room_name == "no-fork-ns",
                    CoordinationSession.state.in_(["idle", "waiting", "negotiating"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected one non-terminal CoordinationSession, found {len(rows)}"


@pytest.mark.asyncio
async def test_coord_session_partial_unique_index_rejects_direct_fork(
    client: AsyncClient, db_session: AsyncSession
):
    """Regression #280: defense-in-depth — the partial unique index on
    ``coordination_sessions(parent_room_name) WHERE state IN
    ('idle','waiting','negotiating')`` rejects a direct INSERT that would
    fork the room into two non-terminal sessions. Bypasses the API guards
    to exercise the index itself.
    """
    from uuid import uuid4

    from sqlalchemy.exc import IntegrityError

    # Seed one room + one active session via the API.
    await client.post("/api/rooms", json={"name": "fork-guard-ns"})
    await client.post(
        "/api/rooms/fork-guard-ns/sessions",
        json={"agent_handle": "ada", "intent": "seed"},
    )

    # Now try to insert a second non-terminal session directly. The partial
    # unique index must reject it.
    second = CoordinationSession(
        parent_room_name="fork-guard-ns",
        short_id=uuid4().hex[:8],
        state="idle",
    )
    db_session.add(second)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_coord_session_unique_index_allows_post_terminal_replacement(
    client: AsyncClient, db_session: AsyncSession
):
    """The unique index is filtered to non-terminal states. Once a session
    completes (state=complete/agreed/failed), a NEW non-terminal session can
    be inserted for the same room. This is what ``test_new_session_after_complete``
    already validates at the API level; here we assert the index permits it.
    """
    from uuid import uuid4

    from sqlalchemy import update as sa_update

    await client.post("/api/rooms", json={"name": "post-term-ns"})
    await client.post(
        "/api/rooms/post-term-ns/sessions",
        json={"agent_handle": "x", "intent": "y"},
    )
    # Force the existing session terminal so the partial index no longer
    # covers it.
    await db_session.execute(
        sa_update(CoordinationSession)
        .where(CoordinationSession.parent_room_name == "post-term-ns")
        .values(state="complete")
    )
    await db_session.commit()

    fresh = CoordinationSession(
        parent_room_name="post-term-ns",
        short_id=uuid4().hex[:8],
        state="idle",
    )
    db_session.add(fresh)
    await db_session.commit()  # must NOT raise — terminal sessions don't block new ones


# ── leave_room: room-scoped participant removal ──────────────────────────


@pytest.mark.asyncio
async def test_leave_room_removes_participant(client: AsyncClient, db_session: AsyncSession):
    """Happy path: DELETE with the correct room_name removes the participant."""
    from sqlalchemy import select

    from app.models import Participant

    await client.post("/api/rooms", json={"name": "leave-room-ns"})
    join = await client.post(
        "/api/rooms/leave-room-ns/sessions",
        json={"agent_handle": "leaver", "intent": "going to leave"},
    )
    assert join.status_code == 201
    participant_id = join.json()["id"]

    resp = await client.delete(f"/api/rooms/leave-room-ns/sessions/{participant_id}")
    assert resp.status_code == 204

    remaining = (
        (
            await db_session.execute(
                select(Participant).where(Participant.id == UUID(participant_id))
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.asyncio
async def test_leave_room_rejects_cross_room_delete(client: AsyncClient, db_session: AsyncSession):
    """Regression: a DELETE addressed to the wrong room MUST NOT remove a
    participant that belongs to a different room.

    Before this fix the WHERE clause keyed only on ``Participant.id``, so an
    attacker (or buggy caller) who knew a participant UUID could remove
    that participant by posting DELETE to *any* room URL — silently
    yanking an agent out of a session it had nothing to do with.

    The route now joins through ``CoordinationSession.parent_room_name``
    so the room_name in the URL must match the participant's actual
    parent room; mismatches return 404 and leave the row in place.
    """
    from sqlalchemy import select

    from app.models import Participant

    await client.post("/api/rooms", json={"name": "leave-victim-ns"})
    await client.post("/api/rooms", json={"name": "leave-attacker-ns"})

    join = await client.post(
        "/api/rooms/leave-victim-ns/sessions",
        json={"agent_handle": "victim", "intent": "stay put"},
    )
    participant_id = join.json()["id"]

    # Try to delete the victim's participant row using the wrong room name.
    resp = await client.delete(f"/api/rooms/leave-attacker-ns/sessions/{participant_id}")
    assert resp.status_code == 404

    still_there = (
        (
            await db_session.execute(
                select(Participant).where(Participant.id == UUID(participant_id))
            )
        )
        .scalars()
        .one_or_none()
    )
    assert still_there is not None, (
        "leave_room must not delete a participant when the URL's room_name "
        "differs from the participant's parent CoordinationSession.parent_room_name"
    )


@pytest.mark.asyncio
async def test_leave_room_unknown_participant_returns_404(client: AsyncClient):
    """DELETE for an unknown participant id returns 404, not 500."""
    from uuid import uuid4 as _uuid4

    await client.post("/api/rooms", json={"name": "leave-unknown-ns"})

    resp = await client.delete(f"/api/rooms/leave-unknown-ns/sessions/{_uuid4()}")
    assert resp.status_code == 404
