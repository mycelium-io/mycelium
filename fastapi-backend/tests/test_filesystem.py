"""Tests for the filesystem-native memory service."""

import tempfile
from pathlib import Path

import pytest

from app.services.filesystem import (
    _key_from_path,
    _sanitize_filename,
    delete_memory_file,
    ensure_room_structure,
    list_memory_files,
    parse_memory,
    read_memory_file,
    serialize_memory,
    value_to_content,
    write_memory_file,
)


@pytest.fixture
def tmp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestSerializeMemory:
    def test_basic_serialization(self):
        text = serialize_memory(
            "PostgreSQL chosen for graph+SQL+vector support.",
            key="decisions/db",
            created_by="agent-a",
        )
        assert text.startswith("---\n")
        assert "key: decisions/db" in text
        assert "created_by: agent-a" in text
        assert "PostgreSQL chosen for graph+SQL+vector support." in text

    def test_with_tags(self):
        text = serialize_memory(
            "content",
            key="test/key",
            created_by="a",
            tags=["backend", "database"],
        )
        assert "tags:" in text
        assert "backend" in text
        assert "database" in text

    def test_with_version(self):
        text = serialize_memory(
            "content",
            key="test/key",
            created_by="a",
            version=3,
        )
        assert "version: 3" in text


class TestParseMemory:
    def test_basic_parse(self):
        text = "---\nkey: decisions/db\ncreated_by: agent-a\n---\nPostgreSQL chosen."
        meta, content = parse_memory(text)
        assert meta["key"] == "decisions/db"
        assert meta["created_by"] == "agent-a"
        assert content == "PostgreSQL chosen."

    def test_no_frontmatter(self):
        text = "Just plain markdown content."
        meta, content = parse_memory(text)
        assert meta == {}
        assert content == "Just plain markdown content."

    def test_roundtrip(self):
        original = serialize_memory(
            "Test content here.",
            key="work/api",
            created_by="agent-b",
            version=2,
            tags=["api"],
        )
        meta, content = parse_memory(original)
        assert meta["key"] == "work/api"
        assert meta["created_by"] == "agent-b"
        assert meta["version"] == 2
        assert meta["tags"] == ["api"]
        assert content == "Test content here."


class TestSanitizeFilename:
    def test_adds_md_extension(self):
        assert _sanitize_filename("decisions/db") == "decisions/db.md"

    def test_preserves_existing_md(self):
        assert _sanitize_filename("decisions/db.md") == "decisions/db.md"


class TestKeyFromPath:
    def test_strips_md_and_base(self):
        base = Path("/tmp/rooms/my-project")
        file_path = Path("/tmp/rooms/my-project/decisions/db.md")
        assert _key_from_path(file_path, base) == "decisions/db"


class TestFileOperations:
    def test_write_and_read(self, tmp_dir):
        write_memory_file(
            tmp_dir,
            "decisions/db",
            "PostgreSQL chosen.",
            created_by="agent-a",
        )
        result = read_memory_file(tmp_dir, "decisions/db")
        assert result is not None
        meta, content = result
        assert meta["key"] == "decisions/db"
        assert content == "PostgreSQL chosen."

    def test_write_creates_directories(self, tmp_dir):
        write_memory_file(
            tmp_dir,
            "deep/nested/key",
            "value",
            created_by="agent-a",
        )
        assert (tmp_dir / "deep" / "nested" / "key.md").exists()

    def test_read_nonexistent(self, tmp_dir):
        assert read_memory_file(tmp_dir, "does/not/exist") is None

    def test_delete(self, tmp_dir):
        write_memory_file(tmp_dir, "temp/data", "delete me", created_by="a")
        assert delete_memory_file(tmp_dir, "temp/data") is True
        assert read_memory_file(tmp_dir, "temp/data") is None

    def test_delete_nonexistent(self, tmp_dir):
        assert delete_memory_file(tmp_dir, "nope") is False

    def test_list_all(self, tmp_dir):
        write_memory_file(tmp_dir, "a/one", "content 1", created_by="x")
        write_memory_file(tmp_dir, "a/two", "content 2", created_by="x")
        write_memory_file(tmp_dir, "b/three", "content 3", created_by="y")

        entries = list_memory_files(tmp_dir)
        assert len(entries) == 3
        keys = [k for k, _, _ in entries]
        assert "a/one" in keys
        assert "a/two" in keys
        assert "b/three" in keys

    def test_list_with_prefix(self, tmp_dir):
        write_memory_file(tmp_dir, "decisions/db", "pg", created_by="a")
        write_memory_file(tmp_dir, "decisions/api", "rest", created_by="a")
        write_memory_file(tmp_dir, "work/setup", "done", created_by="a")

        entries = list_memory_files(tmp_dir, prefix="decisions/")
        assert len(entries) == 2
        keys = [k for k, _, _ in entries]
        assert all(k.startswith("decisions/") for k in keys)

    def test_list_with_limit(self, tmp_dir):
        for i in range(10):
            write_memory_file(tmp_dir, f"item/{i}", f"val {i}", created_by="a")

        entries = list_memory_files(tmp_dir, limit=3)
        assert len(entries) == 3

    def test_list_empty_dir(self, tmp_dir):
        entries = list_memory_files(tmp_dir / "nonexistent")
        assert entries == []

    def test_upsert_increments_version(self, tmp_dir):
        write_memory_file(tmp_dir, "status/deploy", "PENDING", created_by="a", version=1)
        write_memory_file(
            tmp_dir, "status/deploy", "ACTIVE", created_by="a", updated_by="b", version=2
        )
        result = read_memory_file(tmp_dir, "status/deploy")
        assert result is not None
        meta, content = result
        assert meta["version"] == 2
        assert meta["updated_by"] == "b"
        assert content == "ACTIVE"


class TestEnsureRoomStructure:
    def test_creates_standard_dirs(self, tmp_dir):
        ensure_room_structure(tmp_dir)
        for subdir in ("decisions", "failed", "status", "context", "work", "procedures", "log"):
            assert (tmp_dir / subdir).is_dir()


class TestValueToContent:
    def test_string_passthrough(self):
        assert value_to_content("hello") == "hello"

    def test_dict_with_text(self):
        assert value_to_content({"text": "hello", "extra": "data"}) == "hello"

    def test_dict_without_text(self):
        result = value_to_content({"key": "val"})
        assert "key: val" in result
