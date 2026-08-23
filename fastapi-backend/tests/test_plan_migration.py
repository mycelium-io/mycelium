# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Lifting an old ``plan/`` checklist into ``work/`` rows.

The properties this exists to hold: it runs on somebody's real room, so it must
never lose a task, never re-open one that was finished, never destroy the file
it read, and never do any of it twice.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import plan_migration
from app.services.filesystem import ensure_room_structure, get_room_dir, read_memory_file

CHECKLIST = """---
version: 1
---

# Migration plan

- [x] land the custody seam @dana
- [ ] write the migration
- [ ] ship it @growth
"""


@pytest.fixture
def room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    name = "atlas"
    room_dir = get_room_dir(name)
    ensure_room_structure(room_dir)
    (room_dir / "plan").mkdir(parents=True, exist_ok=True)
    (room_dir / "plan" / "tasks.md").write_text(CHECKLIST, encoding="utf-8")
    return name


async def run(room_name: str) -> list[str]:
    # The rows are written unembedded on purpose; these tests have no model.
    with patch("app.routes.memory.embed_text", return_value=[0.0]):
        return await plan_migration.migrate_room(room_name)


def row(room_name: str, key: str):
    found = read_memory_file(get_room_dir(room_name), key)
    assert found is not None, f"expected a row at {key}"
    return found


@pytest.mark.asyncio
class TestMigrate:
    async def test_every_task_becomes_a_row(self, room: str):
        keys = await run(room)
        assert keys == [
            "work/land-the-custody-seam",
            "work/write-the-migration",
            "work/ship-it",
        ]

    async def test_a_finished_task_stays_finished(self, room: str):
        # Re-opening work the room had already closed would be the migration
        # inventing a backlog.
        await run(room)
        assert row(room, "work/land-the-custody-seam")[0]["status"] == "resolved"
        assert row(room, "work/write-the-migration")[0]["status"] == "open"

    async def test_a_handle_becomes_an_assignee_not_a_holder(self, room: str):
        await run(room)
        meta, _ = row(room, "work/ship-it")
        assert meta["assignee"] == "@growth"
        assert "owner" not in meta
        assert "custody" not in meta

    async def test_the_row_says_where_it_came_from(self, room: str):
        await run(room)
        assert row(room, "work/ship-it")[0][plan_migration.ORIGIN_FIELD] == "plan/tasks"

    async def test_the_task_text_survives(self, room: str):
        await run(room)
        assert "write the migration" in row(room, "work/write-the-migration")[1]

    async def test_the_checklist_file_is_not_destroyed(self, room: str):
        # A migration that deletes what it converted leaves nobody a way to
        # check the conversion.
        await run(room)
        meta, content = row(room, "plan/tasks")
        assert "# Migration plan" in content
        assert "land the custody seam" in content
        assert meta[plan_migration.MIGRATED_FLAG] is True

    async def test_it_does_not_run_twice(self, room: str):
        await run(room)
        row_version = row(room, "work/ship-it")[0]["version"]
        source_version = row(room, "plan/tasks")[0]["version"]

        assert await run(room) == []

        # Not just "wrote no new rows": a second boot must not touch either
        # file again, or every restart re-versions the room's history.
        assert row(room, "work/ship-it")[0]["version"] == row_version
        assert row(room, "plan/tasks")[0]["version"] == source_version

    async def test_it_never_overwrites_a_row_that_already_stands(self, room: str):
        # A task somebody has already recorded as a row wins over the checklist:
        # the row is the live one, the checklist is what we are retiring.
        from app.services.fields import write as write_fields

        await run(room)
        await write_fields(room, "work/ship-it", {"status": "resolved"}, "dana")
        (get_room_dir(room) / "plan" / "tasks.md").write_text(CHECKLIST, encoding="utf-8")
        await run(room)
        assert row(room, "work/ship-it")[0]["status"] == "resolved"

    async def test_a_room_with_no_checklist_is_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
        ensure_room_structure(get_room_dir("empty"))
        assert await run("empty") == []

    async def test_prose_with_no_tasks_is_left_alone(self, room: str):
        # Nothing to lift means nothing to mark: a note under plan/ is just a
        # memory now, and flagging it would imply a conversion that never
        # happened.
        (get_room_dir(room) / "plan" / "notes.md").write_text(
            "Some background reading.\n", encoding="utf-8"
        )
        await run(room)
        assert plan_migration.MIGRATED_FLAG not in row(room, "plan/notes")[0]


@pytest.mark.asyncio
async def test_migrate_all_survives_a_bad_room(room: str):
    # Startup must not be blocked by one unreadable room.
    with patch.object(plan_migration, "migrate_room", side_effect=OSError("disk gone")):
        assert await plan_migration.migrate_all() == 0
