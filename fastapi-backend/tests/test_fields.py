# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Field writes: a board verb that reaches the room instead of the browser.

The property behind all of it: a row is a title plus its frontmatter, so
changing a row means writing frontmatter — and the write has to be the same one
every other memory change goes through, or the board becomes a second store.
"""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import fields, leases
from app.services.filesystem import get_room_dir, read_memory_file

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)["custody"]


async def make_room(client: AsyncClient, name: str) -> None:
    await client.post("/api/rooms", json={"name": name})


async def make_memory(client: AsyncClient, room: str, key: str, **meta) -> None:
    await client.post(
        f"/api/rooms/{room}/memory",
        json={
            "items": [
                {
                    "key": key,
                    "value": "Ship the aligner rewrite",
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
    """The reserved set is a derivation of the custody contract, not a copy."""

    def test_reserved_is_the_custody_field_its_companions_and_the_holder(self):
        assert {
            CONTRACT["field"],
            "owner",
            *CONTRACT["companion_fields"],
        } == fields.RESERVED


@pytest.mark.asyncio
class TestWrite:
    async def test_a_field_write_lands_in_frontmatter(self, client: AsyncClient):
        await make_room(client, "fw")
        await make_memory(client, "fw", "decisions/ttl")

        resp = await client.post(
            "/api/rooms/fw/fields",
            json={"key": "decisions/ttl", "handle": "julia", "fields": {"status": "in_review"}},
        )

        assert resp.status_code == 200
        assert resp.json()["fields"]["status"] == "in_review"
        assert frontmatter("fw", "decisions/ttl")["status"] == "in_review"

    async def test_it_writes_any_namespace_not_just_leasable_ones(self, client: AsyncClient):
        # Custody is restricted to work/; a status change is not. A decision
        # that cannot be moved is the overlay problem with extra steps.
        await make_room(client, "fw2")
        await make_memory(client, "fw2", "decisions/ttl")

        resp = await client.post(
            "/api/rooms/fw2/fields",
            json={"key": "decisions/ttl", "handle": "julia", "fields": {"priority": "urgent"}},
        )

        assert resp.status_code == 200
        assert not leases.leasable("decisions/ttl")
        assert frontmatter("fw2", "decisions/ttl")["priority"] == "urgent"

    async def test_a_null_clears_a_key(self, client: AsyncClient):
        await make_room(client, "fw3")
        await make_memory(client, "fw3", "work/spike", blocked_by="#502")

        await client.post(
            "/api/rooms/fw3/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"blocked_by": None}},
        )

        assert frontmatter("fw3", "work/spike").get("blocked_by") is None

    async def test_it_preserves_frontmatter_it_was_not_asked_to_change(self, client: AsyncClient):
        await make_room(client, "fw4")
        await make_memory(client, "fw4", "work/spike", priority="high", assignee="@dana")

        await client.post(
            "/api/rooms/fw4/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"status": "in_review"}},
        )

        meta = frontmatter("fw4", "work/spike")
        assert meta["priority"] == "high"
        assert meta["assignee"] == "@dana"
        assert meta["status"] == "in_review"

    async def test_it_versions_like_any_other_memory_write(self, client: AsyncClient):
        await make_room(client, "fw5")
        await make_memory(client, "fw5", "work/spike")
        before = frontmatter("fw5", "work/spike")["version"]

        await client.post(
            "/api/rooms/fw5/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"status": "in_review"}},
        )

        assert frontmatter("fw5", "work/spike")["version"] == before + 1

    async def test_it_leaves_the_prose_alone(self, client: AsyncClient):
        await make_room(client, "fw6")
        await make_memory(client, "fw6", "work/spike")

        await client.post(
            "/api/rooms/fw6/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"status": "in_review"}},
        )

        found = read_memory_file(get_room_dir("fw6"), "work/spike")
        assert found is not None
        assert "Ship the aligner rewrite" in found[1]


@pytest.mark.asyncio
class TestRefusals:
    @pytest.mark.parametrize("reserved", sorted(fields.RESERVED))
    async def test_custody_keys_are_refused_by_name(self, client: AsyncClient, reserved: str):
        await make_room(client, "fr")
        await make_memory(client, "fr", "work/spike")

        resp = await client.post(
            "/api/rooms/fr/fields",
            json={"key": "work/spike", "handle": "mallory", "fields": {reserved: "held"}},
        )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert reserved in detail["reserved"]
        assert "leases" in detail["message"]

    async def test_a_refused_write_changes_nothing(self, client: AsyncClient):
        # The point of the refusal is that a forged claim never lands, so a
        # partly-applied batch would defeat it.
        await make_room(client, "fr2")
        await make_memory(client, "fr2", "work/spike")
        before = frontmatter("fr2", "work/spike")

        await client.post(
            "/api/rooms/fr2/fields",
            json={
                "key": "work/spike",
                "handle": "mallory",
                "fields": {"status": "resolved", "owner": "@mallory"},
            },
        )

        after = frontmatter("fr2", "work/spike")
        assert after.get("status") == before.get("status")
        assert after.get("owner") == before.get("owner")
        assert after["version"] == before["version"]

    async def test_a_missing_row_is_a_404_not_a_new_file(self, client: AsyncClient):
        await make_room(client, "fr3")

        resp = await client.post(
            "/api/rooms/fr3/fields",
            json={"key": "work/never-existed", "handle": "julia", "fields": {"status": "open"}},
        )

        assert resp.status_code == 404
        assert read_memory_file(get_room_dir("fr3"), "work/never-existed") is None

    async def test_an_empty_write_is_refused_rather_than_bumping_a_version(
        self, client: AsyncClient
    ):
        await make_room(client, "fr4")
        await make_memory(client, "fr4", "work/spike")
        before = frontmatter("fr4", "work/spike")["version"]

        resp = await client.post(
            "/api/rooms/fr4/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {}},
        )

        assert resp.status_code == 422
        assert frontmatter("fr4", "work/spike")["version"] == before

    async def test_an_unknown_room_is_a_404(self, client: AsyncClient):
        resp = await client.post(
            "/api/rooms/no-such-room/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"status": "open"}},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestRead:
    async def test_it_returns_the_unmanaged_half_only(self, client: AsyncClient):
        await make_room(client, "fread")
        await make_memory(client, "fread", "work/spike", priority="high")

        resp = await client.get("/api/rooms/fread/fields/work/spike")

        assert resp.status_code == 200
        body = resp.json()
        assert body["fields"]["priority"] == "high"
        # The store's own keys are not the row's fields.
        assert "created_by" not in body["fields"]
        assert "version" not in body["fields"]


@pytest.mark.asyncio
class TestSharedWriterWithLeases:
    async def test_a_lease_still_moves_custody_through_the_shared_upsert(self, client: AsyncClient):
        # leases._write delegates to fields.upsert_patch; this is the guard that
        # the delegation did not change what a claim writes.
        await make_room(client, "fs")
        await make_memory(client, "fs", "work/spike")

        resp = await client.post(
            "/api/rooms/fs/leases/claim",
            json={"key": "work/spike", "handle": "dana", "ttl_minutes": 30},
        )

        assert resp.status_code == 200
        meta = frontmatter("fs", "work/spike")
        assert meta["custody"] == "held"
        assert meta["owner"] == "@dana"
        assert meta["claimed_at"]

    async def test_a_field_write_does_not_disturb_a_live_lease(self, client: AsyncClient):
        await make_room(client, "fs2")
        await make_memory(client, "fs2", "work/spike")
        await client.post(
            "/api/rooms/fs2/leases/claim",
            json={"key": "work/spike", "handle": "dana", "ttl_minutes": 30},
        )

        await client.post(
            "/api/rooms/fs2/fields",
            json={"key": "work/spike", "handle": "julia", "fields": {"priority": "urgent"}},
        )

        meta = frontmatter("fs2", "work/spike")
        assert meta["custody"] == "held"
        assert meta["owner"] == "@dana"
        assert meta["priority"] == "urgent"
