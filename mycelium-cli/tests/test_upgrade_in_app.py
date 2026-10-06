# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium upgrade`` leaves the Mac app's own CLI to the app, which updates itself."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import install
from mycelium.desktop import supervisor


def test_the_apps_cli_is_told_the_app_updates_itself(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        supervisor, "bundle_dir", lambda: Path("/Applications/Mycelium.app/Contents/MacOS")
    )

    def no_network() -> str:
        raise AssertionError("an app's CLI must not look for a wheel")

    monkeypatch.setattr(install, "_get_latest_release_tag", no_network)
    result = CliRunner().invoke(app, ["upgrade"])
    assert result.exit_code == 0
    assert "Check for Updates" in result.output


def test_a_standalone_binary_still_upgrades_itself(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervisor, "bundle_dir", lambda: Path("/opt/homebrew/bin"))
    monkeypatch.setattr(install, "_get_latest_release_tag", lambda: None)
    result = CliRunner().invoke(app, ["upgrade"])
    assert "Could not fetch latest release" in result.output
