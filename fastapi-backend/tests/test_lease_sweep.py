# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The lease sweep: the one detector for the ``expired`` timeline notice.

Expiry is derived, never written, so nothing raises ``expired`` at a seam the
way ``claimed``/``released``/``resolved`` are raised. The sweep watches for a
held lease crossing its TTL and raises once per lease.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.services import assignments, lease_sweep
from app.services.room_channels import manager

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_sweep():
    lease_sweep.reset()
    yield
    lease_sweep.reset()


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Every notice the sweep raises, captured at the manager."""
    raised: list[dict] = []

    async def capture(room: str, **data) -> None:
        raised.append({"room": room, **data})

    monkeypatch.setattr(manager, "raise_notice", capture)
    return raised


async def make_room(client: AsyncClient, name: str) -> None:
    await client.post("/api/rooms", json={"name": name})


async def make_work(client: AsyncClient, room: str, key: str) -> None:
    await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {
                    "key": key,
                    "value": "# Spike the auth rewrite",
                    "created_by": "julia",
                    "embed": False,
                }
            ]
        },
    )


async def claim(room: str, key: str, handle: str, *, at: datetime, ttl: int = 30) -> None:
    await assignments.claim(room, key, handle, ttl, at)


@pytest.mark.asyncio
async def test_a_lease_that_drains_is_announced_once(client: AsyncClient, notices: list[dict]):
    await make_room(client, "sweep-once")
    await make_work(client, "sweep-once", "work/auth-spike")
    await claim("sweep-once", "work/auth-spike", "growth", at=NOW)
    notices.clear()  # the claim's own notice is not what is under test

    # Primed while the lease is live; nothing has drained yet.
    assert await lease_sweep.sweep_expired_leases(NOW) == []
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(minutes=10)) == []
    assert notices == []

    # The crossing: raised exactly once, naming the task and who let it drain.
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(minutes=31)) == [
        ("sweep-once", "work/auth-spike")
    ]
    assert len(notices) == 1
    notice = notices[0]
    assert notice["room"] == "sweep-once"
    assert notice["subkind"] == "expired"
    assert notice["key"] == "work/auth-spike"
    assert notice["title"] == "Spike the auth rewrite"
    assert notice["by"] == "growth"

    # Still expired on every later look, still announced only the once.
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(hours=2)) == []
    assert len(notices) == 1


@pytest.mark.asyncio
async def test_a_reclaimed_row_is_a_new_lease_and_may_expire_again(
    client: AsyncClient, notices: list[dict]
):
    await make_room(client, "sweep-again")
    await make_work(client, "sweep-again", "work/auth-spike")
    await claim("sweep-again", "work/auth-spike", "growth", at=NOW)
    await lease_sweep.sweep_expired_leases(NOW)
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(minutes=31)) == [
        ("sweep-again", "work/auth-spike")
    ]

    # An expired lease is stealable; the new holder's lease drains on its own clock.
    later = NOW + timedelta(minutes=40)
    await claim("sweep-again", "work/auth-spike", "risk", at=later)
    assert await lease_sweep.sweep_expired_leases(later) == []
    assert await lease_sweep.sweep_expired_leases(later + timedelta(minutes=31)) == [
        ("sweep-again", "work/auth-spike")
    ]
    expired = [n for n in notices if n["subkind"] == "expired"]
    assert [n["by"] for n in expired] == ["growth", "risk"]


@pytest.mark.asyncio
async def test_a_released_or_resolved_row_is_not_expired(client: AsyncClient, notices: list[dict]):
    await make_room(client, "sweep-quiet")
    await make_work(client, "sweep-quiet", "work/handed-back")
    await make_work(client, "sweep-quiet", "work/finished")
    await make_work(client, "sweep-quiet", "work/never-taken")
    await claim("sweep-quiet", "work/handed-back", "growth", at=NOW)
    await claim("sweep-quiet", "work/finished", "growth", at=NOW)
    await lease_sweep.sweep_expired_leases(NOW)

    await assignments.release("sweep-quiet", "work/handed-back", "growth", None, NOW)
    await assignments.resolve("sweep-quiet", "work/finished", "growth", NOW)
    notices.clear()

    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(hours=1)) == []
    assert notices == []


@pytest.mark.asyncio
async def test_the_first_sweep_after_a_start_records_history_without_dating_it(
    client: AsyncClient, notices: list[dict]
):
    """A lease that drained while nobody was watching is on the board as
    ``expired`` (derived), but the timeline cannot honestly date its crossing
    at whatever moment the hub happened to come back."""
    await make_room(client, "sweep-restart")
    await make_work(client, "sweep-restart", "work/auth-spike")
    await claim("sweep-restart", "work/auth-spike", "growth", at=NOW)
    notices.clear()

    lease_sweep.reset()  # the process restarts after the lease has already drained
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(hours=1)) == []
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(hours=2)) == []
    assert notices == []
    # The board still says so, with nothing written.
    described = assignments.read("sweep-restart", "work/auth-spike", NOW + timedelta(hours=1))
    assert described["assignment"] == "expired"


@pytest.mark.asyncio
async def test_one_failing_notice_does_not_stop_the_others(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    await make_room(client, "sweep-robust")
    await make_work(client, "sweep-robust", "work/a")
    await make_work(client, "sweep-robust", "work/b")
    await claim("sweep-robust", "work/a", "growth", at=NOW)
    await claim("sweep-robust", "work/b", "growth", at=NOW)
    await lease_sweep.sweep_expired_leases(NOW)

    raised: list[str] = []

    async def flaky(room: str, key: str, subkind: str, by: str) -> None:
        if key == "work/a":
            raise RuntimeError("channel down")
        raised.append(key)

    monkeypatch.setattr(assignments, "raise_notice", flaky)
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(minutes=31)) == [
        ("sweep-robust", "work/b")
    ]
    assert raised == ["work/b"]
    # The one that failed is not marked announced, so the next look retries it.
    monkeypatch.setattr(assignments, "raise_notice", lambda *a, **k: _ok(raised, a[1]))
    assert await lease_sweep.sweep_expired_leases(NOW + timedelta(minutes=32)) == [
        ("sweep-robust", "work/a")
    ]


async def _ok(raised: list[str], key: str) -> None:
    raised.append(key)


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_cancels() -> None:
    lease_sweep.start_lease_sweep()
    task = lease_sweep._sweep_task
    assert task is not None and not task.done()
    lease_sweep.start_lease_sweep()
    assert lease_sweep._sweep_task is task
    lease_sweep.stop_lease_sweep()
    assert lease_sweep._sweep_task is None
    assert task.cancelled() or task.cancelling()


def test_expired_is_a_contracted_notice_subkind() -> None:
    from app.services.l9 import NOTICE_SUBKINDS

    assert "expired" in NOTICE_SUBKINDS
