# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room names and memory keys cannot reach outside their directory."""

from pathlib import Path

import pytest

from app.services.filesystem import (
    UnsafePathError,
    delete_memory_file,
    get_data_dir,
    get_room_dir,
    list_memory_files,
    read_memory_file,
    room_exists,
    write_memory_file,
)

ESCAPING_KEYS = ["../outside", "../../outside", "a/../../outside", "/tmp/outside"]


@pytest.mark.parametrize("key", ESCAPING_KEYS)
def test_write_rejects_escaping_key(tmp_path: Path, key: str) -> None:
    room = tmp_path / "room"
    room.mkdir()
    with pytest.raises(UnsafePathError):
        write_memory_file(room, key, "x", created_by="agent")
    assert not (tmp_path / "outside.md").exists()


@pytest.mark.parametrize("key", ESCAPING_KEYS)
def test_read_and_delete_treat_escaping_key_as_missing(tmp_path: Path, key: str) -> None:
    room = tmp_path / "room"
    room.mkdir()
    secret = tmp_path / "outside.md"
    secret.write_text("---\nkey: outside\n---\nsecret\n", encoding="utf-8")

    assert read_memory_file(room, key) is None
    assert delete_memory_file(room, key) is False
    assert secret.exists()


def test_list_prefix_cannot_escape_room(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    (tmp_path / "outside.md").write_text("---\nkey: outside\n---\nsecret\n", encoding="utf-8")
    write_memory_file(room, "decisions/db", "pg", created_by="agent")

    assert list_memory_files(room, prefix="../") == []
    assert [k for k, _, _ in list_memory_files(room, prefix="decisions/")] == ["decisions/db"]


def test_nested_key_inside_room_still_works(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    write_memory_file(room, "decisions/db", "pg", created_by="agent")
    found = read_memory_file(room, "decisions/db")
    assert found is not None
    assert found[1] == "pg"


def test_symlink_leaving_the_room_is_rejected(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (room / "link").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        write_memory_file(room, "link/note", "x", created_by="agent")
    assert not (elsewhere / "note.md").exists()


@pytest.mark.parametrize("name", ["..", ".", "../escaped", "a/../../escaped"])
def test_room_name_cannot_escape_rooms_dir(name: str) -> None:
    with pytest.raises(UnsafePathError):
        get_room_dir(name)
    assert room_exists(name) is False
    assert not (get_data_dir() / "escaped").exists()


def test_ordinary_room_name_still_works() -> None:
    room = get_room_dir("design-review")
    assert room.is_dir()
    assert room_exists("design-review")


@pytest.mark.parametrize("key", ["a\\b", "", "  ", "a//b", "a/", "/"])
def test_a_key_that_names_no_file_or_two_is_refused(tmp_path: Path, key: str) -> None:
    # `a\b` would be `a/b` on Windows, so two keys would share one file; an
    # empty key or segment names no file at all.
    with pytest.raises(UnsafePathError):
        write_memory_file(tmp_path, key, "x", created_by="agent")
    assert read_memory_file(tmp_path, key) is None


def test_a_key_read_from_a_windows_path_uses_slashes() -> None:
    from pathlib import PureWindowsPath

    from app.services.filesystem import _key_from_path

    base = PureWindowsPath("C:/data/rooms/r")
    key = _key_from_path(PureWindowsPath("C:/data/rooms/r/work/plain-row.md"), base)
    assert key == "work/plain-row"
