# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""mycelium experience: the server's way to add one, and get the hub to read it.

With a Docker stack running, adding recreates only the backend, with the .env
just written; without one, it says to restart; --no-restart touches nothing.
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mycelium.commands import experience
from mycelium.desktop import experiences as xp

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def pack(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(xp, "experiences_dir", lambda: tmp_path / "experiences")
    monkeypatch.setattr("mycelium.config.MyceliumConfig.save", lambda self, *a, **k: None)
    monkeypatch.setattr(
        "mycelium.docker_utils.write_env_file", lambda config: (tmp_path / ".env", False)
    )
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("scenarios/approval-gate-agent/scenario.yaml", "pattern: x\n")
    return archive


@pytest.mark.parametrize(
    ("running", "args", "restarted"),
    [
        (True, [], [["mycelium-backend"]]),
        (False, [], []),
        (True, ["--no-restart"], []),
    ],
)
def test_adding_one_restarts_the_backend_only_when_a_stack_runs(
    pack, monkeypatch, running, args, restarted
):
    calls: list[list[str] | None] = []
    monkeypatch.setattr(experience, "_docker_backend_running", lambda: running)
    monkeypatch.setattr(
        "mycelium.commands.config.restart_containers",
        lambda env_path, services=None: calls.append(services),
    )
    result = CliRunner().invoke(experience.app, ["add", "patterns-explorer", str(pack), *args])
    assert result.exit_code == 0, result.output
    assert "3 business" not in result.output  # one scenario in this pack
    assert "1 business scenario " in result.output
    assert calls == restarted


def test_ls_json_lists_every_experience(tmp_path, monkeypatch):
    monkeypatch.setattr(xp, "experiences_dir", lambda: tmp_path / "experiences")
    result = CliRunner().invoke(experience.app, ["ls", "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert isinstance(rows, list)
    assert all("id" in row and "added" in row for row in rows)


def test_a_bad_file_says_why_and_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(xp, "experiences_dir", lambda: tmp_path / "experiences")
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    result = CliRunner().invoke(experience.app, ["add", "patterns-explorer", str(other)])
    assert result.exit_code == 2
    assert "isn't a zip" in result.output
