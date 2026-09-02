# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Assignments: claims that drain, and a watch that only the assignment can wake.

The property behind all of it: no session gets to announce that it ended, so a
claim has to stop being true without anyone writing that it did.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import assignments
from app.services.filesystem import get_room_dir, read_memory_file

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)["assignment"]


async def make_room(client: AsyncClient, name: str) -> None:
    await client.post("/api/rooms", json={"name": name})


async def make_work(client: AsyncClient, room: str, key: str, **meta) -> None:
    await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {
                    "key": key,
                    "value": "Spike the auth rewrite",
                    "created_by": "julia",
                    "embed": False,
                    "meta": meta or None,
                }
            ]
        },
    )


def frontmatter(room: str, key: str) -> dict:
    found = read_memory_file(get_room_dir(room), key)
    assert found is not None
    return found[0]


class TestContract:
    """The CLI and the GUI carry their own copies of every constant here."""

    def test_states_and_thresholds_match_the_contract(self):
        assert CONTRACT["states"] == list(assignments.STATES)
        assert CONTRACT["stored_states"] == list(assignments.STORED_STATES)
        assert CONTRACT["derived_states"] == list(assignments.DERIVED_STATES)
        assert CONTRACT["stale_after"] == assignments.STALE_AFTER
        assert CONTRACT["default_ttl_minutes"] == assignments.DEFAULT_TTL_MINUTES
        assert CONTRACT["runtime_author"] == assignments.RUNTIME_AUTHOR
        assert CONTRACT["assignable_namespaces"] == list(assignments.ASSIGNABLE_NAMESPACES)


class TestDerivation:
    """State read off frontmatter and the clock, with no write involved."""

    def now(self) -> datetime:
        return datetime(2026, 8, 23, 12, 0, tzinfo=UTC)

    def held(self, minutes: float, **over) -> dict:
        meta = {
            "assignment": "held",
            "owner": "@growth",
            "claimed_at": (self.now() - timedelta(minutes=minutes)).isoformat(),
            "ttl_minutes": 30,
        }
        meta.update(over)
        return meta

    def test_a_lease_ages_through_the_same_words_the_upstream_half_uses(self):
        assert assignments.freshness(self.held(1), self.now()) == "fresh"
        assert assignments.freshness(self.held(20), self.now()) == "stale"
        assert assignments.freshness(self.held(45), self.now()) == "expired"

    def test_a_claim_nobody_renewed_expires_with_nothing_written(self):
        meta = self.held(90)
        assert meta["assignment"] == "held"
        assert assignments.state_of(meta, self.now()) == "expired"

    def test_a_row_with_no_assignment_frontmatter_is_unclaimed(self):
        assert assignments.state_of({}, self.now()) == "unclaimed"

    def test_held_by_nobody_is_not_held(self):
        assert assignments.state_of(self.held(1, owner=None), self.now()) == "unclaimed"

    def test_an_undatable_claim_cannot_be_shown_to_be_alive(self):
        assert (
            assignments.state_of({"assignment": "held", "owner": "@growth"}, self.now())
            == "expired"
        )


@pytest.mark.asyncio
class TestClaim:
    async def test_a_claim_writes_the_lease_through_the_canonical_upsert(self, client):
        await make_room(client, "lease-claim")
        await make_work(client, "lease-claim", "work/auth-spike")

        resp = await client.post(
            "/api/rooms/lease-claim/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth", "ttl_minutes": 30},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["assignment"] == "held"
        assert body["owner"] == "growth"
        assert body["freshness"] == "fresh"

        # Versioned, and on disk as frontmatter a person can read.
        meta = frontmatter("lease-claim", "work/auth-spike")
        assert meta["assignment"] == "held"
        assert meta["owner"] == "@growth"
        assert meta["ttl_minutes"] == 30
        assert meta["version"] == 2

    async def test_a_claim_leaves_the_prose_alone(self, client):
        await make_room(client, "lease-body")
        await make_work(client, "lease-body", "work/auth-spike")
        await client.post(
            "/api/rooms/lease-body/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        resp = await client.get("/api/rooms/lease-body/memory/work/auth-spike")
        assert "Spike the auth rewrite" in resp.json()["content_text"]

    async def test_a_metadata_only_write_keeps_the_memory_searchable(self, client):
        """The index record is replaced whole, so a claim that dropped the vector
        would quietly take the memory out of semantic search."""
        from app.services import search_index

        await make_room(client, "lease-index")
        await make_work(client, "lease-index", "work/auth-spike")
        search_index.upsert(
            "lease-index",
            {"key": "work/auth-spike", "room_name": "lease-index", "embedding": [0.5, 0.25]},
        )
        await client.post(
            "/api/rooms/lease-index/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        assert search_index.embedding_for("lease-index", "work/auth-spike") == [0.5, 0.25]

    async def test_a_live_claim_is_not_stealable(self, client):
        await make_room(client, "lease-steal")
        await make_work(client, "lease-steal", "work/auth-spike")
        await client.post(
            "/api/rooms/lease-steal/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        resp = await client.post(
            "/api/rooms/lease-steal/assignments/claim",
            json={"key": "work/auth-spike", "handle": "risk"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["owner"] == "growth"

    async def test_an_expired_claim_is_retakeable(self, client):
        """The row is back in the pool. Refusing the next taker because a dead
        session's handle is still in the file is the original failure with extra
        steps."""
        await make_room(client, "lease-retake")
        await make_work(
            client,
            "lease-retake",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            ttl_minutes=30,
        )
        resp = await client.post(
            "/api/rooms/lease-retake/assignments/claim",
            json={"key": "work/auth-spike", "handle": "risk"},
        )
        assert resp.status_code == 200
        assert resp.json()["owner"] == "risk"

    async def test_a_plan_task_has_nowhere_to_put_a_lease(self, client):
        await make_room(client, "lease-refuse")
        resp = await client.post(
            "/api/rooms/lease-refuse/assignments/claim",
            json={"key": "plan/tasks", "handle": "growth"},
        )
        assert resp.status_code == 422
        assert "work/" in resp.json()["detail"]["message"]

    async def test_a_missing_row_says_so(self, client):
        await make_room(client, "lease-missing")
        resp = await client.post(
            "/api/rooms/lease-missing/assignments/claim",
            json={"key": "work/nothing-here", "handle": "growth"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestReleaseAndExpiry:
    async def test_a_release_clears_the_holder_and_signs_a_note(self, client):
        await make_room(client, "lease-release")
        await make_work(client, "lease-release", "work/auth-spike")
        await client.post(
            "/api/rooms/lease-release/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        resp = await client.post(
            "/api/rooms/lease-release/assignments/release",
            json={"key": "work/auth-spike", "handle": "growth", "note": "handing to @risk"},
        )
        body = resp.json()
        assert body["assignment"] == "released"
        assert body["owner"] is None
        assert body["assignment_note"] == "handing to @risk"
        assert body["assignment_note_by"] == "growth"

    async def test_a_release_with_nothing_to_add_still_leaves_a_note(self, client):
        await make_room(client, "lease-quiet-release")
        await make_work(client, "lease-quiet-release", "work/auth-spike")
        await client.post(
            "/api/rooms/lease-quiet-release/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        resp = await client.post(
            "/api/rooms/lease-quiet-release/assignments/release",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        assert resp.json()["assignment_note_by"] == "growth"

    async def test_an_expired_lease_is_signed_by_the_runtime_instead(self, client):
        """Delegation and abandonment converge on the same state; the note's
        author is the whole difference, and a reader can tell."""
        await make_room(client, "lease-expiry")
        await make_work(
            client,
            "lease-expiry",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            ttl_minutes=30,
        )
        resp = await client.get("/api/rooms/lease-expiry/assignments/work/auth-spike")
        body = resp.json()
        assert body["assignment"] == "expired"
        assert body["assignment_note_by"] == assignments.RUNTIME_AUTHOR
        assert "stopped renewing" in body["assignment_note"]

    async def test_expiry_is_not_written_down(self, client):
        """Reading a drained lease must not repair it into a stored state — the
        file still says `held`, and the clock still says otherwise."""
        await make_room(client, "lease-no-write")
        await make_work(
            client,
            "lease-no-write",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            ttl_minutes=30,
        )
        before = frontmatter("lease-no-write", "work/auth-spike")["version"]
        await client.get("/api/rooms/lease-no-write/assignments/work/auth-spike")
        after = frontmatter("lease-no-write", "work/auth-spike")
        assert after["assignment"] == "held"
        assert after["version"] == before

    async def test_resolving_takes_the_row_off_the_board(self, client):
        await make_room(client, "lease-resolve")
        await make_work(client, "lease-resolve", "work/auth-spike")
        resp = await client.post(
            "/api/rooms/lease-resolve/assignments/resolve",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        assert resp.json()["assignment"] == "resolved"


@pytest.mark.asyncio
class TestRenew:
    async def test_a_loop_renews_the_leases_its_handle_holds(self, client):
        await make_room(client, "lease-renew")
        await make_work(
            client,
            "lease-renew",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(minutes=25)).isoformat(),
            ttl_minutes=30,
        )
        resp = await client.post(
            "/api/rooms/lease-renew/assignments/renew", json={"handle": "growth"}
        )
        renewed = resp.json()["renewed"]
        assert [r["key"] for r in renewed] == ["work/auth-spike"]
        assert renewed[0]["freshness"] == "fresh"

    async def test_a_lease_still_in_its_first_half_is_left_alone(self, client):
        """A resident loop polls every few seconds. If every poll rewrote the
        room's files, residency would cost more than the work."""
        await make_room(client, "lease-quiet")
        await make_work(
            client,
            "lease-quiet",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=datetime.now(UTC).isoformat(),
            ttl_minutes=30,
        )
        before = frontmatter("lease-quiet", "work/auth-spike")["version"]
        resp = await client.post(
            "/api/rooms/lease-quiet/assignments/renew", json={"handle": "growth"}
        )
        assert resp.json()["renewed"] == []
        assert frontmatter("lease-quiet", "work/auth-spike")["version"] == before

    async def test_a_renewal_does_not_announce_itself(self, client):
        """A heartbeat is not news: a room whose transcript filled with 'still
        here' would be worse than one that forgot."""
        from app.services import in_memory_store

        await make_room(client, "lease-silent")
        await make_work(
            client,
            "lease-silent",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(minutes=25)).isoformat(),
            ttl_minutes=30,
        )
        in_memory_store.clear_all()
        resp = await client.post(
            "/api/rooms/lease-silent/assignments/renew", json={"handle": "growth"}
        )
        # It did renew — the silence is the point, not an absence of work.
        assert len(resp.json()["renewed"]) == 1
        messages = await client.get("/api/rooms/lease-silent/messages")
        assert messages.json()["messages"] == []

    async def test_nobody_renews_a_lease_they_do_not_hold(self, client):
        await make_room(client, "lease-not-mine")
        await make_work(
            client,
            "lease-not-mine",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(minutes=25)).isoformat(),
            ttl_minutes=30,
        )
        resp = await client.post(
            "/api/rooms/lease-not-mine/assignments/renew", json={"handle": "risk"}
        )
        assert resp.json()["renewed"] == []

    async def test_a_lease_that_already_drained_is_not_resurrected(self, client):
        """Renewal keeps a live claim alive; it does not take an abandoned row
        back off the pool without going through a claim."""
        await make_room(client, "lease-drained")
        await make_work(
            client,
            "lease-drained",
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            ttl_minutes=30,
        )
        resp = await client.post(
            "/api/rooms/lease-drained/assignments/renew", json={"handle": "growth"}
        )
        assert resp.json()["renewed"] == []


@pytest.mark.asyncio
class TestAwaitOnALease:
    async def test_the_first_call_is_orientation_not_a_wait(self, client):
        """An agent does not need a push, it needs the row current the next time
        it exists."""
        await make_room(client, "lease-await")
        await make_work(client, "lease-await", "work/auth-spike")
        resp = await client.get(
            "/api/rooms/lease-await/assignments/await", params={"key": "work/auth-spike"}
        )
        body = resp.json()
        assert body["assignment"] == "unclaimed"
        assert body["changed"] is False
        assert body["since"]

    async def test_it_wakes_on_a_claim(self, client):
        await make_room(client, "lease-wake")
        await make_work(client, "lease-wake", "work/auth-spike")
        first = await client.get(
            "/api/rooms/lease-wake/assignments/await", params={"key": "work/auth-spike"}
        )
        since = first.json()["since"]

        watcher = asyncio.create_task(
            client.get(
                "/api/rooms/lease-wake/assignments/await",
                params={"key": "work/auth-spike", "since": since, "timeout": 10},
            )
        )
        await asyncio.sleep(0.1)
        await client.post(
            "/api/rooms/lease-wake/assignments/claim",
            json={"key": "work/auth-spike", "handle": "growth"},
        )
        body = (await watcher).json()
        assert body["changed"] is True
        assert body["assignment"] == "held"
        assert body["owner"] == "growth"

    async def test_unrelated_room_traffic_does_not_wake_it(self, client):
        """Waking on channel traffic to watch a handoff is the wrong
        subscription: a dozen unrelated messages wake you for nothing."""
        await make_room(client, "lease-quiet-watch")
        await make_work(client, "lease-quiet-watch", "work/auth-spike")
        first = await client.get(
            "/api/rooms/lease-quiet-watch/assignments/await", params={"key": "work/auth-spike"}
        )
        since = first.json()["since"]

        watcher = asyncio.create_task(
            client.get(
                "/api/rooms/lease-quiet-watch/assignments/await",
                params={"key": "work/auth-spike", "since": since, "timeout": 3},
            )
        )
        for i in range(5):
            await client.post(
                "/api/rooms/lease-quiet-watch/messages",
                json={"sender": "growth", "content": f"unrelated chatter {i}"},
            )
        body = (await watcher).json()
        assert body["changed"] is False
        assert body["assignment"] == "unclaimed"

    async def test_a_lapsing_lease_is_a_transition_nobody_sent(self, client):
        """The one wake that has no writer: the holder went quiet, so the state
        moved on its own. A watcher keyed on the memory's version would sleep
        through exactly this."""
        room = "lease-lapse"
        await make_room(client, room)
        await make_work(
            client,
            room,
            "work/auth-spike",
            assignment="held",
            owner="@growth",
            claimed_at=(datetime.now(UTC) - timedelta(minutes=29, seconds=58)).isoformat(),
            ttl_minutes=30,
        )
        first = await client.get(
            f"/api/rooms/{room}/assignments/await", params={"key": "work/auth-spike"}
        )
        assert first.json()["assignment"] == "held"
        body = (
            await client.get(
                f"/api/rooms/{room}/assignments/await",
                params={"key": "work/auth-spike", "since": first.json()["since"], "timeout": 10},
            )
        ).json()
        assert body["changed"] is True
        assert body["assignment"] == "expired"

    async def test_the_watch_gives_up_and_says_nothing_moved(self, client):
        await make_room(client, "lease-timeout")
        await make_work(client, "lease-timeout", "work/auth-spike")
        first = await client.get(
            "/api/rooms/lease-timeout/assignments/await", params={"key": "work/auth-spike"}
        )
        body = (
            await client.get(
                "/api/rooms/lease-timeout/assignments/await",
                params={
                    "key": "work/auth-spike",
                    "since": first.json()["since"],
                    "timeout": 2,
                },
            )
        ).json()
        assert body["changed"] is False
