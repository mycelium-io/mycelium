# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What keeps the CLI working on Windows: liveness, keys and hub errors."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mycelium.error_handler import format_error
from mycelium.filesystem import list_memories, read_memory, write_memory
from mycelium.utils.process import pid_alive
from mycelium_backend_client.errors import UnexpectedStatus


def test_pid_alive_sees_this_process() -> None:
    assert pid_alive(os.getpid())


def test_pid_alive_says_no_for_a_process_that_exited() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    proc.wait()
    assert not pid_alive(proc.pid)


@pytest.mark.parametrize("pid", [0, -1])
def test_pid_alive_says_no_for_no_pid(pid: int) -> None:
    assert not pid_alive(pid)


@pytest.mark.parametrize("key", ["a\\b", "", "a//b", "a/", "../outside", "/abs", "a/../b"])
def test_a_key_from_the_hub_cannot_land_outside_or_collide(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="not a valid memory key"):
        write_memory(tmp_path, key, "x", created_by="agent")
    assert read_memory(tmp_path, key) is None
    assert not (tmp_path.parent / "outside.md").exists()


def test_listed_keys_use_slashes(tmp_path: Path) -> None:
    write_memory(tmp_path, "work/plain-row", "x", created_by="agent")
    assert [key for key, _, _ in list_memories(tmp_path)] == ["work/plain-row"]


@pytest.mark.parametrize("key", ["", "  ", "stress\\empty", "work/"])
def test_memory_set_refuses_a_key_that_names_no_file(key: str) -> None:
    from typer.testing import CliRunner

    from mycelium.cli import app

    result = CliRunner().invoke(app, ["memory", "set", key, "x", "--room", "r"])
    assert result.exit_code == 1
    assert "isn't a memory key" in result.output


def test_a_hub_error_reads_as_its_message() -> None:
    error = UnexpectedStatus(404, b'{"detail":"Room or session not found"}')
    assert format_error(error) == "Error: Room or session not found"
