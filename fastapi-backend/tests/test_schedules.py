# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Schedules: an agent's check-in, kept and fired by the hub.

The timing (intervals, cron lines, the minimum, coalescing missed runs), the
pre-check that keeps a quiet run from costing a model turn, the two ways a wake
reaches its owner (a herdr doorbell, or the next ``await``), and the routes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from starlette.requests import Request

from app.routes import participate
from app.services import schedules
from app.services.room_channels import manager
from app.services.schedules import ScheduleError

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh():
    schedules.reset()
    yield
    schedules.reset()


@pytest.fixture
def no_herdr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager, "herdr_status", lambda room, handle: None)


async def make_room(client: AsyncClient, name: str = "ops") -> None:
    await client.post("/api/rooms", json={"name": name})


async def make_row(client: AsyncClient, room: str, key: str, **meta: str) -> None:
    await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {
                    "key": key,
                    "value": "# Ship the checkout",
                    "created_by": "julia",
                    "embed": False,
                    "meta": meta or None,
                }
            ]
        },
    )


async def add(
    room: str = "ops",
    *,
    name: str = "check-in",
    owner: str = "builder",
    check: str | None = None,
) -> schedules.Schedule:
    return await schedules.create(
        room,
        name=name,
        owner=owner,
        every="17m",
        cron=None,
        prompt="look at the board",
        check=check,
        task=None,
        expires_in_days=None,
        created_by="julia",
        now=NOW,
    )


# ── timing ───────────────────────────────────────────────────────────────────


def test_every_reads_one_unit():
    assert schedules.parse_every("17m") == 17 * 60
    assert schedules.parse_every("2h") == 7200
    assert schedules.format_every(1020) == "17m"
    with pytest.raises(ScheduleError):
        schedules.parse_every("soon")


def test_cron_finds_the_next_minute_it_fires_on():
    cron = schedules.parse_cron("30 9 * * 1-5")  # weekdays at 09:30
    # 2026-10-08 is a Thursday; after noon the next is Friday 09:30.
    assert cron.next_after(NOW) == datetime(2026, 10, 9, 9, 30, tzinfo=UTC)
    # Friday 09:30 → Monday, over the weekend.
    assert cron.next_after(datetime(2026, 10, 9, 9, 30, tzinfo=UTC)) == datetime(
        2026, 10, 12, 9, 30, tzinfo=UTC
    )
    assert schedules.parse_cron("*/20 * * * *").next_after(NOW) == datetime(
        2026, 10, 8, 12, 20, tzinfo=UTC
    )


def test_a_cron_line_is_refused_plainly():
    with pytest.raises(ScheduleError, match="five fields"):
        schedules.parse_cron("every day")
    with pytest.raises(ScheduleError, match="outside"):
        schedules.parse_cron("61 * * * *")


def test_the_minimum_interval_holds_for_both_forms():
    with pytest.raises(ScheduleError, match="minimum"):
        schedules.validate_when("1m", None, NOW)
    with pytest.raises(ScheduleError, match="minimum"):
        schedules.validate_when(None, "* * * * *", NOW)
    assert schedules.validate_when(None, "0 * * * *", NOW) == (None, "0 * * * *")
    with pytest.raises(ScheduleError, match="exactly one"):
        schedules.validate_when("1h", "0 * * * *", NOW)


def test_only_checks_the_hub_runs_are_taken():
    assert schedules.validate_check(None) == "always"
    assert schedules.validate_check("search:mentions:me") == "search:mentions:me"
    with pytest.raises(ScheduleError, match="not one the hub runs"):
        schedules.validate_check("rm -rf /")


# ── the store and its guardrails ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_schedule_expires_by_default_and_renews(client: AsyncClient):
    await make_room(client)
    schedule = await add()
    assert schedule.expires_at == NOW + timedelta(days=7)
    assert schedule.next_run == NOW + timedelta(minutes=17)
    assert schedule.state(NOW + timedelta(days=8)) == "expired"
    later = NOW + timedelta(days=6)
    renewed = await schedules.update("ops", "check-in", renew=True, now=later)
    assert renewed.expires_at == later + timedelta(days=7)


@pytest.mark.asyncio
async def test_one_agent_holds_at_most_the_cap(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(schedules.settings, "SCHEDULE_MAX_PER_AGENT", 2)
    await make_room(client)
    await add(name="a")
    await add(name="b")
    with pytest.raises(ScheduleError, match="most one agent"):
        await add(name="c")
    await add(name="c", owner="reviewer")  # another agent's count is its own


@pytest.mark.asyncio
async def test_resuming_starts_the_clock_again(client: AsyncClient, no_herdr):
    await make_room(client)
    await add()
    await schedules.update("ops", "check-in", paused=True, now=NOW)
    assert schedules.due("ops", NOW + timedelta(hours=3)) == []
    resumed_at = NOW + timedelta(hours=3)
    schedule = await schedules.update("ops", "check-in", paused=False, now=resumed_at)
    assert schedule.next_run == resumed_at + timedelta(minutes=17)


# ── firing ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missed_runs_coalesce_into_one(client: AsyncClient, no_herdr):
    await make_room(client)
    await add()
    late = NOW + timedelta(hours=2)  # seven runs came due while nobody looked
    fired = await schedules.sweep(late)
    assert fired == [("ops", "check-in", "woke")]
    schedule = schedules.get("ops", "check-in")
    assert schedule.history[0].missed == 6
    assert schedule.next_run is not None
    assert schedule.next_run > late
    assert schedule.runs == 1
    assert await schedules.sweep(late) == []


@pytest.mark.asyncio
async def test_a_quiet_check_costs_no_turn(client: AsyncClient, no_herdr):
    await make_room(client)
    await add(check="stale")
    run = await schedules.fire("ops", "check-in", now=NOW + timedelta(minutes=17))
    assert run.result == "quiet"
    assert schedules.pending_for("ops", "builder") == []
    schedule = schedules.get("ops", "check-in")
    assert (schedule.quiet, schedule.wakes) == (1, 0)


@pytest.mark.asyncio
async def test_a_wake_waits_for_the_next_await_and_never_doubles(client: AsyncClient, no_herdr):
    await make_room(client)
    await add()
    first = await schedules.fire("ops", "check-in", now=NOW + timedelta(minutes=17))
    second = await schedules.fire("ops", "check-in", now=NOW + timedelta(minutes=34))
    assert (first.result, second.result) == ("woke", "held")
    wake = schedules.take_pending("ops", "builder")
    assert wake is not None
    assert "look at the board" in wake["prompt"]
    assert schedules.take_pending("ops", "builder") is None


@pytest.mark.asyncio
async def test_a_herdr_owner_gets_its_doorbell(client: AsyncClient, monkeypatch):
    await make_room(client)
    rung: list[dict] = []
    monkeypatch.setattr(manager, "herdr_status", lambda room, handle: "idle")
    monkeypatch.setattr(manager, "pending_herdr_wakes", lambda room: set())
    monkeypatch.setattr(
        manager, "enqueue_herdr_wake", lambda room, handle, **kw: rung.append({"h": handle, **kw})
    )
    await add()
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert run.result == "woke"
    assert rung[0]["h"] == "builder"
    assert rung[0]["reason"] == "schedule"
    assert rung[0]["title"] == "check-in"


@pytest.mark.asyncio
async def test_a_working_owner_is_not_woken(client: AsyncClient, monkeypatch):
    await make_room(client)
    monkeypatch.setattr(manager, "herdr_status", lambda room, handle: "working")
    await add()
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert run.result == "busy"


@pytest.mark.asyncio
async def test_the_stale_check_finds_a_lease_running_out(client: AsyncClient, no_herdr):
    await make_room(client)
    claimed = (NOW - timedelta(minutes=50)).isoformat()
    await make_row(
        client,
        "ops",
        "work/checkout",
        assignment="held",
        owner="builder",
        claimed_at=claimed,
        ttl_minutes="60",
    )
    await add(check="stale")
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert run.result == "woke"
    assert run.found == ['work/checkout "Ship the checkout": your lease is stale']
    wake = schedules.take_pending("ops", "builder")
    assert wake is not None
    assert "your lease is stale" in wake["prompt"]


@pytest.mark.asyncio
async def test_the_silent_check_names_an_absent_holder(client: AsyncClient, no_herdr):
    await make_room(client)
    claimed = (NOW - timedelta(hours=2)).isoformat()
    await make_row(
        client,
        "ops",
        "work/checkout",
        assignment="held",
        owner="reviewer",
        claimed_at=claimed,
        ttl_minutes="60",
    )
    await add(check="silent")
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert run.result == "woke"
    assert "@reviewer went quiet" in run.found[0]


@pytest.mark.asyncio
async def test_a_failing_check_is_recorded_not_raised(client: AsyncClient, no_herdr, monkeypatch):
    await make_room(client)
    await add(check="assigned")

    def boom(*_a, **_k):
        raise RuntimeError("board unreadable")

    monkeypatch.setattr(schedules, "_check_assigned", boom)
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert run.result == "error"
    assert run.detail == "board unreadable"


@pytest.mark.asyncio
async def test_await_hands_over_a_scheduled_wake(client: AsyncClient, no_herdr, monkeypatch):
    from app.services import persister

    await make_room(client)
    await add()
    await schedules.fire("ops", "check-in", now=NOW)

    class _Persister:
        log = persister.DeliveryLog()

    class _Managed:
        persister = _Persister()

    async def _provision(_room):
        return _Managed()

    monkeypatch.setattr(participate.actor, "authorize_handle", lambda *a, **k: None)
    monkeypatch.setattr(participate.room_channels.manager, "provision", _provision)
    request = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})
    turn = await participate.await_message("ops", request, handle="builder", timeout=0)
    assert turn["sender"] == "scheduler"
    assert turn["schedule"] == "check-in"
    assert "look at the board" in turn["prompt"]


# ── routes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_routes_create_list_pause_run_and_remove(client: AsyncClient, no_herdr):
    await make_room(client)
    resp = await client.post(
        "/api/rooms/ops/schedules",
        json={"name": "check-in", "owner": "@builder", "every": "30m", "check": "mentions"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["owner"] == "builder"
    assert resp.json()["every"] == "30m"

    listed = (await client.get("/api/rooms/ops/schedules")).json()
    assert listed["total"] == 1
    assert "mentions" in listed["checks"]

    paused = await client.patch("/api/rooms/ops/schedules/check-in", json={"paused": True})
    assert paused.json()["state"] == "paused"

    run = await client.post("/api/rooms/ops/schedules/check-in/run", json={})
    assert run.status_code == 200
    assert run.json()["result"] == "quiet"  # nobody mentioned it
    woke = await client.post("/api/rooms/ops/schedules/check-in/run", json={"wake": True})
    assert woke.json()["result"] == "woke"

    one = (await client.get("/api/rooms/ops/schedules/check-in")).json()
    assert [r["result"] for r in one["history"]] == ["woke", "quiet"]
    assert (one["wakes"], one["quiet"]) == (1, 1)

    assert (await client.delete("/api/rooms/ops/schedules/check-in")).status_code == 204
    assert (await client.get("/api/rooms/ops/schedules/check-in")).status_code == 404


@pytest.mark.asyncio
async def test_routes_refuse_what_the_hub_will_not_run(client: AsyncClient):
    await make_room(client)
    too_often = await client.post(
        "/api/rooms/ops/schedules", json={"name": "x", "owner": "builder", "every": "10s"}
    )
    assert too_often.status_code == 422
    assert "minimum" in too_often.json()["detail"]
    script = await client.post(
        "/api/rooms/ops/schedules",
        json={"name": "x", "owner": "builder", "every": "1h", "check": "./check.sh"},
    )
    assert script.status_code == 422


@pytest.mark.asyncio
async def test_a_schedule_is_written_as_its_owner(client: AsyncClient, as_principal):
    await make_room(client)
    as_principal("mallory")
    resp = await client.post(
        "/api/rooms/ops/schedules", json={"name": "x", "owner": "builder", "every": "1h"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_search_check_reads_me_as_the_owner(client: AsyncClient, no_herdr, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        schedules, "_check_search", lambda room, query, since: seen.append(query) or []
    )
    await make_room(client)
    await add(check="search:deploy -from:me mentions:me")
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert seen == ["deploy -from:builder mentions:builder"]
    assert run.result == "quiet"


@pytest.mark.asyncio
async def test_a_search_check_in_a_quiet_room_finds_nothing(client: AsyncClient, no_herdr):
    await make_room(client)
    await add(check="search:deploy")
    run = await schedules.fire("ops", "check-in", now=NOW)
    assert (run.result, run.detail) == ("quiet", None)
