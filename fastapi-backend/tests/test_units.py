# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A unit of work is a board row and a thread — the binding, and what it survives.

``work/`` rows carry the episode URN their coordination happens in. These tests
hold the three properties the rest of the model rests on: the binding survives
every later write, it is the store's alone to set, and a unit can be created and
worked with no episode ever opened.
"""

import pytest

from app.routes.memory import upsert_memories
from app.schemas import MemoryBatchCreate, MemoryCreate
from app.services import fields, units
from app.services.filesystem import EPISODE_META, get_room_dir, read_memory_file


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    """Rows are written without a model; the vector is not what is under test."""
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


def _room(name: str) -> str:
    """A room is a folder; making it is all a write needs."""
    get_room_dir(name)
    return name


def _meta(room: str, key: str) -> dict:
    found = read_memory_file(get_room_dir(room), key)
    assert found is not None, f"expected a row at {key}"
    return found[0]


async def _write(room: str, key: str, value: str, **meta) -> None:
    await upsert_memories(
        room,
        MemoryBatchCreate(
            items=[MemoryCreate(key=key, value=value, created_by="tester", meta=meta or None)]
        ),
    )


class TestMinting:
    def test_a_urn_is_scoped_to_its_room(self):
        assert units.mint_episode_urn("atlas").startswith("urn:ioc:mycelium:episode:atlas:")

    def test_every_mint_is_a_distinct_thread(self):
        assert units.mint_episode_urn("atlas") != units.mint_episode_urn("atlas")

    def test_the_short_id_is_the_tail_a_reader_types(self):
        urn = units.mint_episode_urn("atlas")
        assert units.short_id_of(urn) == urn.rsplit(":", 1)[-1]


@pytest.mark.asyncio
class TestBoardFirstCreation:
    async def test_a_unit_is_born_with_a_thread(self):
        room = _room("u-create")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        assert written.key == "work/ship-passkey-login"
        assert written.episode
        assert _meta(room, written.key)[EPISODE_META] == written.episode

    async def test_a_unit_is_open_work_nobody_negotiated_for(self):
        # The inversion: today a work/ row exists only because a negotiation
        # converged into one. A unit needs no episode to have *happened*.
        room = _room("u-create-2")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        meta = _meta(room, written.key)
        assert meta["status"] == "open"
        assert meta["kind"] == units.TASK_KIND
        assert "owner" not in meta and "custody" not in meta

    async def test_two_units_are_two_rows(self):
        room = _room("u-create-3")
        one = await units.create_unit(room, "Ship passkey login", created_by="julia")
        two = await units.create_unit(room, "Rotate the signing keys", created_by="julia")
        assert one.key != two.key
        assert one.episode != two.episode


@pytest.mark.asyncio
class TestTheBindingSurvives:
    async def test_a_later_write_keeps_the_thread(self):
        room = _room("u-survive")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        await _write(room, written.key, "Ship passkey login, revised", priority="high")
        meta = _meta(room, written.key)
        assert meta[EPISODE_META] == written.episode
        assert meta["priority"] == "high"

    async def test_a_field_write_keeps_the_thread(self):
        # The board's own verb path. Without the carry-forward this is where a
        # binding evaporated: the first claim on a row unbound it from its thread.
        room = _room("u-survive-2")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        await fields.write(room, written.key, {"status": "in_review"}, "julia")
        meta = _meta(room, written.key)
        assert meta[EPISODE_META] == written.episode
        assert meta["status"] == "in_review"

    async def test_the_thread_is_the_store_s_to_set_not_a_caller_s(self):
        room = _room("u-survive-3")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        await _write(room, written.key, "Ship passkey login", episode="urn:someone:else")
        assert _meta(room, written.key)[EPISODE_META] == written.episode

    async def test_the_thread_is_not_in_the_meta_bag(self):
        # It is store-owned, so it reads back as its own field rather than as
        # something ``MemoryCreate.meta`` could have written.
        room = _room("u-survive-4")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        assert EPISODE_META not in (written.meta or {})
        assert written.episode

    async def test_a_write_outside_the_system_keys_is_refused(self):
        room = _room("u-survive-5")
        with pytest.raises(ValueError, match="system meta"):
            await upsert_memories(
                room,
                MemoryBatchCreate(
                    items=[MemoryCreate(key="work/x", value="x", created_by="julia")]
                ),
                system={"owner": "@julia"},
            )


@pytest.mark.asyncio
class TestBinding:
    async def test_binding_mints_for_a_row_that_has_none(self):
        room = _room("u-bind")
        await _write(room, "work/legacy", "An older row")
        urn = await units.bind_episode(room, "work/legacy")
        assert _meta(room, "work/legacy")[EPISODE_META] == urn

    async def test_the_binding_is_write_once_even_from_the_system_seam(self):
        # The store, not the caller, is what makes the binding stick: a second
        # writer offering a different thread gets the row's own back.
        room = _room("u-bind-5")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        await upsert_memories(
            room,
            MemoryBatchCreate(
                items=[
                    MemoryCreate(key=written.key, value="Ship passkey login", created_by="other")
                ]
            ),
            system={EPISODE_META: "urn:ioc:mycelium:episode:elsewhere:zzz"},
        )
        assert _meta(room, written.key)[EPISODE_META] == written.episode

    async def test_binding_twice_does_not_move_the_thread(self):
        # Re-negotiating inside a unit opens a NEW negotiation episode; it must
        # not re-point the row at it, or the row loses its own history.
        room = _room("u-bind-2")
        await _write(room, "work/legacy", "An older row")
        first = await units.bind_episode(room, "work/legacy")
        again = await units.bind_episode(room, "work/legacy", episode="urn:a:different:one")
        assert again == first

    async def test_binding_an_absent_row_says_so(self):
        room = _room("u-bind-3")
        with pytest.raises(KeyError):
            await units.bind_episode(room, "work/nothing-here")

    async def test_bound_episodes_is_what_tells_an_orphan_from_a_unit(self):
        room = _room("u-bind-4")
        written = await units.create_unit(room, "Ship passkey login", created_by="julia")
        assert units.bound_episodes(room) == {written.episode}


@pytest.mark.asyncio
class TestMigration:
    async def test_a_row_written_before_the_binding_gets_a_thread(self):
        room = _room("u-migrate")
        await _write(room, "work/legacy", "An older row")
        assert units.backfill_room(room) == 1
        assert _meta(room, "work/legacy")[EPISODE_META]

    async def test_minting_is_not_an_edit_anybody_made(self):
        # Going through the upsert would bump the version, re-date updated_at and
        # broadcast a write nobody made — shuffling every stale row to the top of
        # a time-ordered board on the first restart after the upgrade.
        room = _room("u-migrate-2")
        await _write(room, "work/legacy", "An older row", status="in_review")
        before = _meta(room, "work/legacy")
        units.backfill_room(room)
        after = _meta(room, "work/legacy")
        assert after["version"] == before["version"]
        assert after["updated_at"] == before["updated_at"]
        assert after["created_at"] == before["created_at"]
        assert after["status"] == "in_review"

    async def test_a_second_pass_binds_nothing(self):
        room = _room("u-migrate-3")
        await _write(room, "work/legacy", "An older row")
        units.backfill_room(room)
        bound = _meta(room, "work/legacy")[EPISODE_META]
        assert units.backfill_room(room) == 0
        assert _meta(room, "work/legacy")[EPISODE_META] == bound

    async def test_only_units_are_bound(self):
        # A decision is not a unit of work; nothing is coordinated *inside* it.
        room = _room("u-migrate-4")
        await _write(room, "decisions/db", "PostgreSQL")
        assert units.backfill_room(room) == 0
        assert EPISODE_META not in _meta(room, "decisions/db")
