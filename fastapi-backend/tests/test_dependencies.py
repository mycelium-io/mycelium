# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A row that depends on another waits on it, and the board says so.

``depends-on`` is a typed link any memory can carry; on a ``work/`` row it
reads as a prerequisite. What a row waits on is derived off its targets'
own state, never written, so nothing has to be alive when a dependency
resolves. Refusing a claim on a waiting row is a room switch, off by default.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.services import assignments
from tests.test_assignments import make_room, make_work

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def test_dependencies_read_a_string_or_a_list():
    assert assignments.dependencies({"depends-on": "work/a"}) == ["work/a"]
    assert assignments.dependencies({"depends-on": ["work/a", " work/b ", 3, ""]}) == [
        "work/a",
        "work/b",
    ]
    assert assignments.dependencies({}) == []


def test_settled_is_a_done_status_or_a_resolved_lease():
    assert assignments.settled({"status": "resolved"}, NOW)
    assert assignments.settled({"status": "dismissed"}, NOW)
    assert assignments.settled({"assignment": "resolved"}, NOW)
    assert not assignments.settled({"status": "open"}, NOW)
    assert not assignments.settled({}, NOW)


class TestWaiting:
    @pytest.mark.asyncio
    async def test_a_row_waits_on_its_open_dependencies_and_not_its_done_ones(
        self, client: AsyncClient
    ):
        await make_room(client, "deps")
        await make_work(client, "deps", "work/schema")
        await make_work(client, "deps", "work/migrate", status="resolved")
        await make_work(
            client, "deps", "work/api", **{"depends-on": ["work/schema", "work/migrate"]}
        )

        read = await client.get("/api/rooms/deps/assignments/work/api")
        assert read.status_code == 200
        assert read.json()["waiting_on"] == ["work/schema"]

    @pytest.mark.asyncio
    async def test_a_note_and_a_missing_key_are_not_waited_on(self, client: AsyncClient):
        await make_room(client, "deps-refs")
        await client.post(
            "/api/rooms/deps-refs/memory",
            json={
                "items": [
                    {
                        "key": "context/design",
                        "value": "the design",
                        "created_by": "julia",
                        "embed": False,
                    }
                ]
            },
        )
        await make_work(
            client,
            "deps-refs",
            "work/api",
            **{"depends-on": ["context/design", "work/never-filed"]},
        )

        read = await client.get("/api/rooms/deps-refs/assignments/work/api")
        assert read.json()["waiting_on"] == []

    @pytest.mark.asyncio
    async def test_a_row_with_no_dependencies_waits_on_nothing(self, client: AsyncClient):
        await make_room(client, "deps-none")
        await make_work(client, "deps-none", "work/api")
        read = await client.get("/api/rooms/deps-none/assignments/work/api")
        assert read.json()["waiting_on"] == []


class TestTheGate:
    @pytest.mark.asyncio
    async def test_with_the_gate_off_a_waiting_row_is_claimable(self, client: AsyncClient):
        await make_room(client, "gate-off")
        await make_work(client, "gate-off", "work/schema")
        await make_work(client, "gate-off", "work/api", **{"depends-on": "work/schema"})

        resp = await client.post(
            "/api/rooms/gate-off/assignments/claim", json={"key": "work/api", "handle": "api"}
        )
        assert resp.status_code == 200
        assert resp.json()["waiting_on"] == ["work/schema"]

    @pytest.mark.asyncio
    async def test_with_the_gate_on_the_refusal_names_what_it_waits_on(
        self, client: AsyncClient, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "BOARD_DEPENDENCY_GATE", True)
        await make_room(client, "gate-on")
        await make_work(client, "gate-on", "work/schema")
        await make_work(client, "gate-on", "work/api", **{"depends-on": "work/schema"})

        resp = await client.post(
            "/api/rooms/gate-on/assignments/claim", json={"key": "work/api", "handle": "api"}
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["waiting_on"] == ["work/schema"]
        assert "waits on work/schema" in detail["message"]

        forced = await client.post(
            "/api/rooms/gate-on/assignments/claim",
            json={"key": "work/api", "handle": "api", "force": True},
        )
        assert forced.status_code == 200
        assert forced.json()["assignment"] == "held"

    @pytest.mark.asyncio
    async def test_the_gate_opens_when_the_dependency_resolves(
        self, client: AsyncClient, monkeypatch
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "BOARD_DEPENDENCY_GATE", True)
        await make_room(client, "gate-opens")
        await make_work(client, "gate-opens", "work/schema")
        await make_work(client, "gate-opens", "work/api", **{"depends-on": "work/schema"})
        await client.post(
            "/api/rooms/gate-opens/assignments/claim", json={"key": "work/schema", "handle": "db"}
        )
        await client.post(
            "/api/rooms/gate-opens/assignments/resolve", json={"key": "work/schema", "handle": "db"}
        )

        resp = await client.post(
            "/api/rooms/gate-opens/assignments/claim", json={"key": "work/api", "handle": "api"}
        )
        assert resp.status_code == 200


class TestResolving:
    @pytest.mark.asyncio
    async def test_resolving_a_dependency_unblocks_its_dependents_in_the_timeline(
        self, client: AsyncClient, monkeypatch
    ):
        from app.services import room_channels

        raised: list[dict] = []

        async def _notice(room, **kw):
            raised.append(kw)

        monkeypatch.setattr(room_channels.manager, "raise_notice", _notice)
        await make_room(client, "unblocks")
        await make_work(client, "unblocks", "work/schema")
        await make_work(client, "unblocks", "work/api", **{"depends-on": "work/schema"})
        # Waits on two, so resolving one is not enough to unblock it.
        await make_work(client, "unblocks", "work/other")
        await make_work(
            client, "unblocks", "work/deploy", **{"depends-on": ["work/schema", "work/other"]}
        )
        # Already done itself: nothing to unblock.
        await make_work(
            client, "unblocks", "work/old", status="resolved", **{"depends-on": "work/schema"}
        )

        await client.post(
            "/api/rooms/unblocks/assignments/resolve", json={"key": "work/schema", "handle": "db"}
        )

        unblocked = [n["key"] for n in raised if n["subkind"] == "unblocked"]
        assert unblocked == ["work/api"]
        assert [n["by"] for n in raised if n["subkind"] == "unblocked"] == ["db"]

    @pytest.mark.asyncio
    async def test_a_lease_watcher_wakes_when_the_row_becomes_claimable(self, client: AsyncClient):
        await make_room(client, "deps-watch")
        await make_work(client, "deps-watch", "work/schema")
        await make_work(client, "deps-watch", "work/api", **{"depends-on": "work/schema"})

        first = await client.get(
            "/api/rooms/deps-watch/assignments/await", params={"key": "work/api"}
        )
        since = first.json()["since"]
        await client.post(
            "/api/rooms/deps-watch/assignments/resolve", json={"key": "work/schema", "handle": "db"}
        )
        woke = await client.get(
            "/api/rooms/deps-watch/assignments/await",
            params={"key": "work/api", "since": since, "timeout": 2},
        )
        assert woke.json()["changed"] is True
        assert woke.json()["waiting_on"] == []
