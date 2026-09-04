# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A task is a board row and a thread — the binding, and what it survives.

``work/`` rows carry the episode URN their coordination happens in. These tests
hold the three properties the rest of the model rests on: the binding survives
every later write, it is the store's alone to set, and a task can be created and
worked with no episode ever opened.
"""

import pytest

from app.routes.memory import upsert_memories
from app.schemas import MemoryBatchCreate, MemoryCreate
from app.services import fields, tasks
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    read_memory_file,
    write_memory_file,
)


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


def _write_unbound(room: str, key: str, value: str, **meta) -> None:
    """Write a row straight to disk, with no episode, bypassing thread minting.

    Used to reach the unbound state that :func:`tasks.backfill_room` heals.
    """
    write_memory_file(get_room_dir(room), key, value, created_by="tester", extra_meta=meta or None)


class TestMinting:
    def test_a_urn_is_scoped_to_its_room(self):
        assert tasks.mint_episode_urn("atlas").startswith("urn:ioc:mycelium:episode:atlas:")

    def test_every_mint_is_a_distinct_thread(self):
        assert tasks.mint_episode_urn("atlas") != tasks.mint_episode_urn("atlas")

    def test_the_short_id_is_the_tail_a_reader_types(self):
        urn = tasks.mint_episode_urn("atlas")
        assert tasks.short_id_of(urn) == urn.rsplit(":", 1)[-1]


@pytest.mark.asyncio
class TestBoardFirstCreation:
    async def test_a_unit_is_born_with_a_thread(self):
        room = _room("u-create")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        assert written.key == "work/ship-passkey-login"
        assert written.episode
        assert _meta(room, written.key)[EPISODE_META] == written.episode

    async def test_a_unit_is_open_work_nobody_negotiated_for(self):
        # The inversion: today a work/ row exists only because a negotiation
        # converged into one. A task needs no episode to have *happened*.
        room = _room("u-create-2")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        meta = _meta(room, written.key)
        assert meta["status"] == "open"
        assert meta["kind"] == tasks.TASK_KIND
        assert "owner" not in meta and "custody" not in meta

    async def test_two_units_are_two_rows(self):
        room = _room("u-create-3")
        one = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        two = await tasks.create_task(room, "Rotate the signing keys", created_by="julia")
        assert one.key != two.key
        assert one.episode != two.episode


class TestWorkedIsTheOnlyLineLeft:
    """Everything is discussed; only the board namespaces are worked.

    :func:`tasks.is_board_row` is the one predicate: every namespace is
    threaded uniformly. What the tests below assert is behavior — that a
    memory of any namespace comes out of a write carrying a thread.
    """

    @pytest.mark.parametrize("key", ["work/passkey-login", "decisions/db", "status/ci"])
    def test_a_board_namespace_is_worked(self, key):
        assert tasks.is_board_row(key)

    @pytest.mark.parametrize(
        "key",
        ["context/goal", "skills/review", "agents/sec", "log/episodes/a1b2c3d4", "notebook"],
    )
    def test_everything_else_is_discussed_but_never_claimed(self, key):
        # A threaded `skills/` doc must not turn up on the board as something to
        # take: discussable is the wide word, worked is the narrow one.
        assert not tasks.is_board_row(key)


@pytest.mark.asyncio
class TestThreadOnEveryWrite:
    """The plain write path mints a thread for any memory, not just create_task.

    A decision dropped with ``memory set``, a status posted, a ``context/``
    design note, a ``skills/`` doc — each gets a thread the moment it exists, so
    nothing has to be coordinated first for there to be somewhere to argue.
    """

    async def test_a_decision_written_plainly_gets_its_own_thread(self):
        room = _room("u-write-decision")
        await _write(room, "decisions/token-ttl", "15m or 60m?")
        assert _meta(room, "decisions/token-ttl")[EPISODE_META]

    async def test_each_memory_gets_a_distinct_thread(self):
        room = _room("u-write-distinct")
        await _write(room, "work/one", "One")
        await _write(room, "decisions/two", "Two")
        assert _meta(room, "work/one")[EPISODE_META] != _meta(room, "decisions/two")[EPISODE_META]

    async def test_a_context_note_can_be_discussed_too(self):
        # A context note gets its own thread for discussion.
        room = _room("u-write-context")
        await _write(room, "context/goal", "Move off the legacy store")
        assert _meta(room, "context/goal")[EPISODE_META]

    async def test_a_skill_can_be_discussed_too(self):
        room = _room("u-write-skill")
        await _write(room, "skills/review", "How we review")
        assert _meta(room, "skills/review")[EPISODE_META]

    async def test_what_the_hub_writes_for_itself_is_discussable_too(self):
        # System-written records (agent manifests, episode logs) are
        # discussable like any other memory.
        room = _room("u-write-system")
        await _write(room, "agents/sec", "A manifest")
        await _write(room, "log/episodes/a1b2c3d4", "A closed negotiation")
        await _write(room, "context/synthesis", "The briefing")
        assert _meta(room, "agents/sec")[EPISODE_META]
        assert _meta(room, "log/episodes/a1b2c3d4")[EPISODE_META]
        assert _meta(room, "context/synthesis")[EPISODE_META]

    async def test_the_synthesizer_rewriting_its_briefing_keeps_its_thread(self):
        # Synthesis rewrites this key on its own schedule; the thread binding
        # is write-once and survives each rewrite.
        from app.services.synthesizer import SYNTHESIS_KEY

        room = _room("u-write-synthesis")
        await _write(room, SYNTHESIS_KEY, "First pass")
        first = _meta(room, SYNTHESIS_KEY)[EPISODE_META]
        await _write(room, SYNTHESIS_KEY, "Second pass, more of the room read")
        assert _meta(room, SYNTHESIS_KEY)[EPISODE_META] == first

    async def test_a_later_write_never_moves_the_thread(self):
        room = _room("u-write-stable")
        await _write(room, "work/one", "One")
        first = _meta(room, "work/one")[EPISODE_META]
        await _write(room, "work/one", "One, revised", status="in_review")
        assert _meta(room, "work/one")[EPISODE_META] == first


@pytest.mark.asyncio
class TestTheBindingSurvives:
    async def test_a_later_write_keeps_the_thread(self):
        room = _room("u-survive")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        await _write(room, written.key, "Ship passkey login, revised", priority="high")
        meta = _meta(room, written.key)
        assert meta[EPISODE_META] == written.episode
        assert meta["priority"] == "high"

    async def test_a_field_write_keeps_the_thread(self):
        # The board's own verb path. Without the carry-forward this is where a
        # binding evaporated: the first claim on a row unbound it from its thread.
        room = _room("u-survive-2")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        await fields.write(room, written.key, {"status": "in_review"}, "julia")
        meta = _meta(room, written.key)
        assert meta[EPISODE_META] == written.episode
        assert meta["status"] == "in_review"

    async def test_the_thread_is_the_store_s_to_set_not_a_caller_s(self):
        room = _room("u-survive-3")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        await _write(room, written.key, "Ship passkey login", episode="urn:someone:else")
        assert _meta(room, written.key)[EPISODE_META] == written.episode

    async def test_the_thread_is_not_in_the_meta_bag(self):
        # It is store-owned, so it reads back as its own field rather than as
        # something ``MemoryCreate.meta`` could have written.
        room = _room("u-survive-4")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
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
        urn = await tasks.bind_episode(room, "work/legacy")
        assert _meta(room, "work/legacy")[EPISODE_META] == urn

    async def test_the_binding_is_write_once_even_from_the_system_seam(self):
        # The store, not the caller, is what makes the binding stick: a second
        # writer offering a different thread gets the row's own back.
        room = _room("u-bind-5")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
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
        # Re-negotiating inside a task opens a NEW negotiation episode; it must
        # not re-point the row at it, or the row loses its own history.
        room = _room("u-bind-2")
        await _write(room, "work/legacy", "An older row")
        first = await tasks.bind_episode(room, "work/legacy")
        again = await tasks.bind_episode(room, "work/legacy", episode="urn:a:different:one")
        assert again == first

    async def test_binding_an_absent_row_says_so(self):
        room = _room("u-bind-3")
        with pytest.raises(KeyError):
            await tasks.bind_episode(room, "work/nothing-here")

    async def test_bound_episodes_is_what_tells_an_orphan_from_a_unit(self):
        room = _room("u-bind-4")
        written = await tasks.create_task(room, "Ship passkey login", created_by="julia")
        assert tasks.bound_episodes(room) == {written.episode}


@pytest.mark.asyncio
class TestMigration:
    async def test_a_row_written_before_the_binding_gets_a_thread(self):
        room = _room("u-migrate")
        _write_unbound(room, "work/legacy", "An older row")
        assert tasks.backfill_room(room) == 1
        assert _meta(room, "work/legacy")[EPISODE_META]

    async def test_minting_is_not_an_edit_anybody_made(self):
        # Going through the upsert would bump the version, re-date updated_at and
        # broadcast a write nobody made — shuffling every stale row to the top of
        # a time-ordered board on the first restart after the upgrade.
        room = _room("u-migrate-2")
        _write_unbound(room, "work/legacy", "An older row", status="in_review")
        before = _meta(room, "work/legacy")
        tasks.backfill_room(room)
        after = _meta(room, "work/legacy")
        assert after["version"] == before["version"]
        assert after["updated_at"] == before["updated_at"]
        assert after["created_at"] == before["created_at"]
        assert after["status"] == "in_review"

    async def test_a_second_pass_binds_nothing(self):
        room = _room("u-migrate-3")
        _write_unbound(room, "work/legacy", "An older row")
        tasks.backfill_room(room)
        bound = _meta(room, "work/legacy")[EPISODE_META]
        assert tasks.backfill_room(room) == 0
        assert _meta(room, "work/legacy")[EPISODE_META] == bound

    async def test_every_memory_is_bound_not_only_the_board(self):
        # A backfill binds a thread to every existing file in the room,
        # including agents/ and log/, not only memories written afterward.
        room = _room("u-migrate-4")
        keys = (
            "decisions/db",
            "failed/spoke",
            "context/goal",
            "procedures/deploy",
            "agents/sec",
            "log/episodes/a1b2c3d4",
            "context/synthesis",
        )
        for key in keys:
            _write_unbound(room, key, f"body of {key}")
        assert tasks.backfill_room(room) == len(keys)
        for key in keys:
            assert _meta(room, key)[EPISODE_META], key

    async def test_a_backfilled_memory_gets_a_thread_of_its_own(self):
        room = _room("u-migrate-5")
        _write_unbound(room, "context/one", "One")
        _write_unbound(room, "context/two", "Two")
        tasks.backfill_room(room)
        assert _meta(room, "context/one")[EPISODE_META] != _meta(room, "context/two")[EPISODE_META]
