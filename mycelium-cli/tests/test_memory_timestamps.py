# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The CLI store's timestamps are recovered, never invented at read time.

Mirrors the backend's ``tests/test_memory_timestamps.py``. Falling back to
``now`` (or to an empty sort key) re-dates a memory on every read and parks it at
one end of the list regardless of its age.
"""

from datetime import UTC, datetime, timedelta

from mycelium.filesystem import (
    apply_knowledge,
    list_memories,
    parse_memory,
    parse_timestamp,
    read_memory,
    recover_updated_at,
    write_memory,
)


def _unstamped(base_dir, key: str) -> None:
    path = base_dir / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nkey: {key}\ncreated_by: julia\nversion: 1\n---\nnote\n")


class TestRecoverUpdatedAt:
    def test_uses_the_frontmatter_stamp(self, tmp_path):
        meta = {"updated_at": "2026-08-19T09:48:00+00:00"}
        assert recover_updated_at(meta, tmp_path / "x.md") == datetime(
            2026, 8, 19, 9, 48, tzinfo=UTC
        )

    def test_falls_back_to_the_file_not_to_now(self, tmp_path):
        path = tmp_path / "x.md"
        path.write_text("---\nkey: x\n---\nbody\n")
        assert recover_updated_at({}, path) == datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    def test_a_bare_yaml_datetime_is_read_as_utc(self, tmp_path):
        stamp = recover_updated_at({"updated_at": datetime(2026, 8, 19, 9, 48)}, tmp_path / "x.md")
        assert stamp == datetime(2026, 8, 19, 9, 48, tzinfo=UTC)


class TestListMemories:
    def test_an_unstamped_memory_sorts_by_its_file_not_to_the_bottom(self, tmp_path):
        old = datetime.now(UTC) - timedelta(days=3)
        write_memory(tmp_path, "decisions/old", "b", created_by="julia", updated_at=old)
        _unstamped(tmp_path, "agents/590")

        assert [key for key, _, _ in list_memories(tmp_path)] == ["agents/590", "decisions/old"]

    def test_a_bare_yaml_timestamp_sorts_against_a_quoted_one(self, tmp_path):
        write_memory(tmp_path, "decisions/new", "b", created_by="julia")
        path = tmp_path / "agents/hand.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nkey: agents/hand\ncreated_by: julia\nversion: 1\n"
            "updated_at: 2026-08-19T09:48:00+00:00\n---\nnote\n"
        )

        assert [key for key, _, _ in list_memories(tmp_path)] == ["decisions/new", "agents/hand"]


class TestApplyKnowledge:
    def test_a_carried_updated_at_is_replicated_not_restamped(self, tmp_path):
        apply_knowledge(
            tmp_path,
            key="plan/tasks",
            content="# Plan",
            version=1,
            updated_at="2026-08-04T00:00:00+00:00",
        )

        stored = read_memory(tmp_path, "plan/tasks")
        assert stored is not None
        assert parse_timestamp(stored[0]["updated_at"]) == datetime(2026, 8, 4, tzinfo=UTC)

    def test_an_update_keeps_the_created_at_already_on_disk(self, tmp_path):
        apply_knowledge(
            tmp_path, key="k", content="v1", version=1, updated_at="2026-08-04T00:00:00+00:00"
        )
        first = read_memory(tmp_path, "k")
        assert first is not None
        created = first[0]["created_at"]

        apply_knowledge(
            tmp_path, key="k", content="v2", version=2, updated_at="2026-08-05T00:00:00+00:00"
        )

        second = read_memory(tmp_path, "k")
        assert second is not None
        assert second[0]["created_at"] == created

    def test_without_a_carried_stamp_the_write_still_lands(self, tmp_path):
        result = apply_knowledge(tmp_path, key="k", content="v1", version=1)

        assert result.applied
        meta, _body = parse_memory((tmp_path / "k.md").read_text())
        assert parse_timestamp(meta["updated_at"]) is not None
