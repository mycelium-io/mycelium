# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium install` without a terminal says how to run it, rather than crashing."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium import cli


def test_install_without_a_tty_prints_its_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A home with nothing installed, so it reaches the interactive path, and
    # no old daemon to look for.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("mycelium.old_daemon.remove_old_daemon", lambda: [])

    # CliRunner's stdin is not a terminal.
    result = CliRunner().invoke(cli.app, ["install"])

    # CI renders the help in color, and the color codes split option names.
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert result.exit_code == 1, output
    assert not isinstance(result.exception, ModuleNotFoundError)
    assert "Non-interactive terminal detected" in output
    assert "--non-interactive" in output, "the help says how to run it in a script"
