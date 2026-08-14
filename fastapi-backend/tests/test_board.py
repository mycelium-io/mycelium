# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Coordination board — projection over the ledger, plan, and live episode (#493)."""

import pytest
from httpx import AsyncClient


async def _make_room(client: AsyncClient, name: str) -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


def _by_id(items: list[dict], item_id: str) -> dict:
    return next(i for i in items if i["id"] == item_id)


async def _post_event(
    client: AsyncClient, room: str, *, kind: str, title: str, sender: str = "agent-y"
) -> str:
    """Write a stateful ledger event the way an agent would (agent parity)."""
    resp = await client.post(
        f"/api/rooms/{room}/messages",
        json={
            "sender_handle": sender,
            "message_type": "event",
            "content": title,
            "metadata": {"kind": kind, "payload": {"title": title}},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
class TestBoard:
    async def test_empty_room_board(self, client: AsyncClient):
        await _make_room(client, "board-empty")
        resp = await client.get("/api/rooms/board-empty/board")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["counts"] == {"needs": 0, "flight": 0, "resolved": 0}

    async def test_missing_room_404(self, client: AsyncClient):
        assert (await client.get("/api/rooms/nope/board")).status_code == 404

    async def test_plan_tasks_project_and_resolve(self, client: AsyncClient):
        room = "board-plan"
        await _make_room(client, room)
        task = (await client.post(f"/api/rooms/{room}/plan/tasks", json={"text": "ship it"})).json()

        data = (await client.get(f"/api/rooms/{room}/board")).json()
        row = _by_id(data["items"], f"plan:{task['id']}")
        assert row["source"] == "plan"
        assert row["state"] == "in_progress"
        assert data["counts"]["flight"] == 1

        # resolve maps to a task toggle
        r = await client.post(f"/api/rooms/{room}/board/items/plan:{task['id']}/resolve")
        assert r.status_code == 204
        data = (await client.get(f"/api/rooms/{room}/board")).json()
        row = _by_id(data["items"], f"plan:{task['id']}")
        assert row["state"] == "resolved"
        assert data["counts"]["resolved"] == 1

    async def test_plan_rejects_non_resolve_verbs(self, client: AsyncClient):
        room = "board-plan-verb"
        await _make_room(client, room)
        task = (await client.post(f"/api/rooms/{room}/plan/tasks", json={"text": "x"})).json()
        r = await client.post(f"/api/rooms/{room}/board/items/plan:{task['id']}/claim")
        assert r.status_code == 409

    async def test_capture_creates_needs_you_concern(self, client: AsyncClient):
        room = "board-capture"
        await _make_room(client, room)
        resp = await client.post(
            f"/api/rooms/{room}/board/capture",
            json={"text": "auth migration might break spokes", "sender": "julia"},
        )
        assert resp.status_code == 201
        item = resp.json()
        assert item["kind"] == "concern"
        assert item["needs_you"] is True
        assert item["provenance"] == "captured by julia"

        data = (await client.get(f"/api/rooms/{room}/board")).json()
        assert data["counts"]["needs"] == 1

    async def test_ledger_event_projects(self, client: AsyncClient):
        """An event posted over the messages API surfaces on the board — parity."""
        room = "board-parity"
        await _make_room(client, room)
        eid = await _post_event(client, room, kind="action", title="migrate auth to JWT")
        data = (await client.get(f"/api/rooms/{room}/board")).json()
        row = _by_id(data["items"], eid)
        assert row["source"] == "ledger"
        assert row["title"] == "migrate auth to JWT"
        assert row["provenance"] == "from agent-y"

    async def test_verb_lifecycle_claim_block_resolve(self, client: AsyncClient):
        room = "board-lifecycle"
        await _make_room(client, room)
        eid = await _post_event(client, room, kind="concern", title="pick a TTL")

        # claim → owner set, moves to in-flight
        assert (
            await client.post(f"/api/rooms/{room}/board/items/{eid}/claim", json={"owner": "julia"})
        ).status_code == 204
        data = (await client.get(f"/api/rooms/{room}/board")).json()
        row = _by_id(data["items"], eid)
        assert row["state"] == "claimed"
        assert row["owner"]["handle"] == "julia"
        # claimed work is in flight, not awaiting the human
        assert row["needs_you"] is False
        assert data["counts"]["flight"] == 1

        # block → needs you
        assert (
            await client.post(
                f"/api/rooms/{room}/board/items/{eid}/block", json={"waiting_on": "#502"}
            )
        ).status_code == 204
        row = _by_id((await client.get(f"/api/rooms/{room}/board")).json()["items"], eid)
        assert row["state"] == "blocked"
        assert row["waiting_on"] == "#502"
        assert row["needs_you"] is True

        # resolve → leaves the active lenses
        assert (
            await client.post(f"/api/rooms/{room}/board/items/{eid}/resolve")
        ).status_code == 204
        data = (await client.get(f"/api/rooms/{room}/board")).json()
        assert _by_id(data["items"], eid)["state"] == "resolved"

    async def test_dismiss_hides_item(self, client: AsyncClient):
        room = "board-dismiss"
        await _make_room(client, room)
        eid = await _post_event(client, room, kind="concern", title="noise")
        assert (
            await client.post(f"/api/rooms/{room}/board/items/{eid}/dismiss")
        ).status_code == 204
        data = (await client.get(f"/api/rooms/{room}/board")).json()
        assert all(i["id"] != eid for i in data["items"])

    async def test_promote_stamps_backlink_and_resolves(self, client: AsyncClient):
        room = "board-promote"
        await _make_room(client, room)
        eid = await _post_event(client, room, kind="concern", title="durable decision")
        r = await client.post(f"/api/rooms/{room}/board/items/{eid}/promote", json={"issue": 512})
        assert r.status_code == 204
        row = _by_id((await client.get(f"/api/rooms/{room}/board")).json()["items"], eid)
        assert row["state"] == "resolved"
        assert row["github"]["issue"] == 512
        assert row["note"] == "promoted → #512"

    async def test_escalation_tops_needs_you_and_is_ephemeral(self, client: AsyncClient):
        """An agent-raised escalation floats to the top and self-expires (anti-rot)."""
        room = "board-escalate"
        await _make_room(client, room)
        # A prior plain concern, then an escalation raised after it.
        await _post_event(client, room, kind="concern", title="older concern")
        resp = await client.post(
            f"/api/rooms/{room}/board/escalate",
            json={"text": "bless the OpenFGA change", "agent": "agent-y", "ask": "sign-off"},
        )
        assert resp.status_code == 201, resp.text
        item = resp.json()
        assert item["kind"] == "escalation"
        assert item["escalated_by"] == "agent-y"
        assert item["ask"] == "sign-off"
        assert item["needs_you"] is True
        # Bespoke (no GitHub backing) → carries a TTL, marked ephemeral.
        assert item["ephemeral"] is True
        assert item["expires_in"] is not None

        # Escalation sorts ahead of the older concern in the projection.
        items = (await client.get(f"/api/rooms/{room}/board")).json()["items"]
        assert items[0]["escalated_by"] == "agent-y"

    async def test_github_backed_escalation_is_durable(self, client: AsyncClient):
        room = "board-escalate-gh"
        await _make_room(client, room)
        resp = await client.post(
            f"/api/rooms/{room}/board/escalate",
            json={"text": "auth rollout decision", "agent": "planner", "issue": 512},
        )
        item = resp.json()
        # Backed by a real issue → durable, not ephemeral.
        assert item["ephemeral"] is False
        assert item["github"]["issue"] == 512

    async def test_captured_concern_self_expires(self, client: AsyncClient):
        room = "board-capture-ttl"
        await _make_room(client, room)
        item = (
            await client.post(
                f"/api/rooms/{room}/board/capture", json={"text": "note", "sender": "julia"}
            )
        ).json()
        assert item["ephemeral"] is True
        assert item["expires_in"] is not None

    async def test_verb_on_missing_item_404(self, client: AsyncClient):
        room = "board-404"
        await _make_room(client, room)
        r = await client.post(
            f"/api/rooms/{room}/board/items/00000000-0000-0000-0000-000000000000/resolve"
        )
        assert r.status_code == 404
