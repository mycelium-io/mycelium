# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A memory's timestamps are recovered from what's stored, never from read time.

Substituting the read time for a missing stamp would make the memory report a
different time on every read, sorting it to a different position in every
time-ordered view.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.routes.memory import _memory_read_from_file
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    parse_memory,
    read_memory_file,
    recover_timestamps,
    write_memory_file,
)

ROOM = "stamps"


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """Keep the index test off the fastembed ONNX model (see test_memory_sync.py)."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


def _unstamped(room_dir, key: str, *, body: str = "note") -> None:
    """Write a memory whose frontmatter carries no timestamps at all."""
    path = room_dir / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nkey: {key}\ncreated_by: julia\nversion: 1\n---\n{body}\n")


def _bare_stamps(room_dir, key: str, when: str) -> None:
    """Write a memory with *unquoted* stamps — YAML hands these back as datetimes,
    where the store's own writes come back as strings."""
    path = room_dir / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nkey: {key}\ncreated_by: julia\nversion: 1\n"
        f"created_at: {when}\nupdated_at: {when}\n---\nnote\n"
    )


class TestRecoverTimestamps:
    def test_frontmatter_stamps_are_used_as_written(self, tmp_path):
        meta = {
            "created_at": "2026-08-19T09:48:00+00:00",
            "updated_at": "2026-08-20T10:12:00+00:00",
        }
        created, updated = recover_timestamps(meta, tmp_path / "missing.md")
        assert created == datetime(2026, 8, 19, 9, 48, tzinfo=UTC)
        assert updated == datetime(2026, 8, 20, 10, 12, tzinfo=UTC)

    def test_a_missing_stamp_falls_back_to_the_file_not_to_now(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("---\nkey: note\n---\nbody\n")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

        created, updated = recover_timestamps({}, path)

        assert created == mtime
        assert updated == mtime

    def test_updated_never_predates_created(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("---\nkey: note\n---\nbody\n")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        # A restore or `cp -p` can leave the file older than its created stamp.
        created_stamp = (mtime + timedelta(days=1)).isoformat()

        created, updated = recover_timestamps({"created_at": created_stamp}, path)

        assert updated >= created

    def test_a_naive_stamp_is_read_as_utc_so_it_stays_comparable(self, tmp_path):
        created, updated = recover_timestamps({"updated_at": datetime(2026, 8, 19, 9, 48)}, None)
        assert updated.tzinfo is not None
        assert created == updated

    def test_the_recovered_stamp_does_not_move_between_reads(self, tmp_path):
        path = tmp_path / "note.md"
        path.write_text("---\nkey: note\n---\nbody\n")
        assert recover_timestamps({}, path) == recover_timestamps({}, path)


class TestMemoryListOrdering:
    def test_a_memory_with_no_stamp_sorts_by_its_file_not_to_the_bottom(self):
        room_dir = get_room_dir(ROOM)
        old = datetime.now(UTC) - timedelta(days=3)
        write_memory_file(
            room_dir, "decisions/old", "b", created_by="julia", created_at=old, updated_at=old
        )
        _unstamped(room_dir, "agents/590")

        keys = [key for key, _, _ in list_memory_files(room_dir)]

        # An unstamped memory sorts first in the listing.
        assert keys == ["agents/590", "decisions/old"]

    def test_a_bare_yaml_timestamp_does_not_break_the_listing(self):
        room_dir = get_room_dir(ROOM)
        write_memory_file(room_dir, "decisions/quoted", "b", created_by="julia")
        _bare_stamps(room_dir, "agents/hand", "2026-08-19T09:48:00+00:00")

        # Sorting a str against a datetime raised TypeError and took out the
        # whole list, not just the one odd file.
        keys = [key for key, _, _ in list_memory_files(room_dir)]

        assert keys == ["decisions/quoted", "agents/hand"]

    def test_listing_reports_the_recovered_stamp_to_its_callers(self):
        room_dir = get_room_dir(ROOM)
        _unstamped(room_dir, "agents/590")

        (_key, meta, _content) = list_memory_files(room_dir)[0]

        assert meta["updated_at"]
        assert meta["updated_at"] == meta["created_at"]


class TestMemoryReadStability:
    def test_reading_the_same_file_twice_reports_the_same_updated_at(self):
        room_dir = get_room_dir(ROOM)
        _unstamped(room_dir, "agents/590")
        stored = read_memory_file(room_dir, "agents/590")
        assert stored is not None
        meta, body = stored

        first = _memory_read_from_file(ROOM, "agents/590", meta, body)
        second = _memory_read_from_file(ROOM, "agents/590", meta, body)

        assert first.updated_at == second.updated_at
        assert first.created_at == second.created_at

    def test_an_unstamped_memory_does_not_report_the_time_it_was_read(self):
        room_dir = get_room_dir(ROOM)
        _unstamped(room_dir, "agents/590")
        stored = read_memory_file(room_dir, "agents/590")
        assert stored is not None
        meta, body = stored

        read = _memory_read_from_file(ROOM, "agents/590", meta, body)

        assert read.updated_at < datetime.now(UTC)


@pytest.mark.asyncio
async def test_list_endpoint_orders_an_unstamped_memory_by_its_file(client):
    room_dir = get_room_dir(ROOM)
    old = datetime.now(UTC) - timedelta(days=3)
    write_memory_file(
        room_dir, "decisions/old", "b", created_by="julia", created_at=old, updated_at=old
    )
    _unstamped(room_dir, "agents/590")

    resp = await client.get(f"/api/rooms/{ROOM}/memory")

    assert resp.status_code == 200
    assert [m["key"] for m in resp.json()] == ["agents/590", "decisions/old"]


def test_parse_memory_still_returns_frontmatter_untouched():
    meta, body = parse_memory("---\nkey: k\nversion: 2\n---\nbody\n")
    assert meta == {"key": "k", "version": 2}
    assert body == "body"


class TestIndexSkipCheck:
    """The unchanged-file check compares when the record was *indexed* against the
    file's mtime. A memory synced from another store carries that store's write
    time, which is older than the mtime of the file it just landed in — reading
    it as an index time would re-embed the memory on every scan."""

    async def test_a_synced_memory_is_not_reindexed_on_every_scan(self):
        from app.services import memory_sync
        from app.services.indexer import index_room

        await memory_sync.apply_knowledge(
            ROOM,
            memory_sync.KnowledgeWrite(
                key="plan/tasks",
                content="# Plan",
                version=1,
                created_by="julia",
                updated_by="julia",
                updated_at="2026-08-04T00:00:00+00:00",
            ),
        )
        await index_room(ROOM)

        stats = await index_room(ROOM)

        assert stats["indexed"] == 0
        assert stats["skipped"] == 1


class TestSkillTimestamps:
    """A skill is a memory under ``skills/``, read through the same frontmatter —
    so ``GET /skills/{name}`` (a direct file read) must recover its stamps the way
    the list endpoint does, not report the time it was called."""

    async def test_get_skill_does_not_report_the_time_it_was_read(self, client):
        room_dir = get_room_dir(ROOM)
        _unstamped(room_dir, "skills/deploy")

        first = await client.get(f"/api/rooms/{ROOM}/skills/deploy")
        second = await client.get(f"/api/rooms/{ROOM}/skills/deploy")

        assert first.status_code == 200
        assert first.json()["updated_at"] == second.json()["updated_at"]

    async def test_get_and_list_agree_on_a_skill_s_stamps(self, client):
        room_dir = get_room_dir(ROOM)
        _unstamped(room_dir, "skills/deploy")

        listed = (await client.get(f"/api/rooms/{ROOM}/skills")).json()["skills"][0]
        fetched = (await client.get(f"/api/rooms/{ROOM}/skills/deploy")).json()

        assert listed["updated_at"] == fetched["updated_at"]
        assert listed["created_at"] == fetched["created_at"]


class TestTranscriptStampParsing:
    def test_a_naive_recorded_at_comes_back_aware(self):
        """Every other stamp the message list sorts against is aware; mixing the
        two raises rather than misordering."""
        from app.services.persister import parse_recorded_at

        parsed = parse_recorded_at("2026-08-19T09:48:00")

        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_an_unusable_recorded_at_is_none(self):
        from app.services.persister import parse_recorded_at

        assert parse_recorded_at("") is None
        assert parse_recorded_at("not a time") is None
