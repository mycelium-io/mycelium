# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The hub-side write for status-provider credentials, and the one rule it exists
to keep: nothing here can print a value.

The store is a flat ``name -> value`` file, 0600, outside ``config.toml``. The
CLI writes it and the backend resolver reads it; the two never share code (the
thin CLI can't import the backend), only the file, so these tests pin the write
side: values arrive from stdin not argv, the file is owner-only, ``ls`` shows
names and set/empty but never a value, and absent stays distinct from
configured-empty.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium import status_credentials
from mycelium.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a throwaway file, off the developer's real home."""
    path = tmp_path / "status-credentials.json"
    monkeypatch.setenv(status_credentials.STORE_ENV, str(path))
    return path


# ── the module ────────────────────────────────────────────────────────────────


def test_set_stores_a_value_and_round_trips(_store: Path) -> None:
    path = status_credentials.set_credential("GITHUB_TOKEN", "ghp_x")
    assert path == _store
    assert status_credentials._read() == {"GITHUB_TOKEN": "ghp_x"}


def test_the_store_is_owner_only(_store: Path) -> None:
    path = status_credentials.set_credential("GITHUB_TOKEN", "ghp_x")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_damaged_store_reads_as_empty(_store: Path) -> None:
    _store.write_text("{ not json", encoding="utf-8")
    assert status_credentials._read() == {}


def test_ls_maps_a_configured_empty_name_to_not_set(_store: Path) -> None:
    status_credentials.set_credential("GITHUB_TOKEN", "ghp_x")
    status_credentials.set_credential("EMPTY", "")
    listed = status_credentials.list_names()
    # Both present, so both are "configured"; only the non-empty one is "set".
    assert listed == {"EMPTY": False, "GITHUB_TOKEN": True}


def test_removing_reports_whether_there_was_one(_store: Path) -> None:
    status_credentials.set_credential("GITHUB_TOKEN", "ghp_x")
    assert status_credentials.remove_credential("GITHUB_TOKEN") is True
    assert status_credentials.remove_credential("GITHUB_TOKEN") is False


# ── the commands ──────────────────────────────────────────────────────────────


def test_set_reads_the_value_from_stdin_and_never_echoes_it() -> None:
    result = runner.invoke(
        app, ["board", "credential", "set", "GITHUB_TOKEN", "--stdin"], input="ghp_secret"
    )
    assert result.exit_code == 0, result.output
    assert "ghp_secret" not in result.output
    assert "GITHUB_TOKEN" in result.output


def test_set_without_stdin_and_no_tty_refuses_rather_than_reading_argv() -> None:
    # No value on the command line at all, so with no interactive prompt available
    # there is nothing to store; it must refuse, not invent an empty credential.
    result = runner.invoke(app, ["board", "credential", "set", "GITHUB_TOKEN"], input="")
    assert result.exit_code == 1, result.output


def test_ls_shows_names_and_set_state_never_values() -> None:
    runner.invoke(
        app, ["board", "credential", "set", "GITHUB_TOKEN", "--stdin"], input="ghp_secret"
    )
    result = runner.invoke(app, ["board", "credential", "ls"])
    assert result.exit_code == 0, result.output
    assert "GITHUB_TOKEN" in result.output
    assert "ghp_secret" not in result.output


def test_ls_on_an_empty_hub_says_so() -> None:
    result = runner.invoke(app, ["board", "credential", "ls"])
    assert result.exit_code == 0, result.output
    assert "No status-provider credentials" in result.output


def test_rm_forgets_a_credential() -> None:
    runner.invoke(
        app, ["board", "credential", "set", "GITHUB_TOKEN", "--stdin"], input="ghp_secret"
    )
    result = runner.invoke(app, ["board", "credential", "rm", "GITHUB_TOKEN"])
    assert result.exit_code == 0, result.output
    assert status_credentials.list_names() == {}


def test_set_json_output_reports_without_the_value() -> None:
    result = runner.invoke(
        app,
        ["--json", "board", "credential", "set", "GITHUB_TOKEN", "--stdin"],
        input="ghp_secret",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "GITHUB_TOKEN"
    assert payload["empty"] is False
    assert "ghp_secret" not in result.output
