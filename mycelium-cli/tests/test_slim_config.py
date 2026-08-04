# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the SLIM node-endpoint config field and `mycelium connect`."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.config import MyceliumConfig, SlimConfig

runner = CliRunner()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://127.0.0.1:46357", "http://127.0.0.1:46357"),
        ("127.0.0.1:46357", "http://127.0.0.1:46357"),  # scheme added
        ("http://hub:46357/", "http://hub:46357"),  # trailing slash trimmed
        ("  hub:46357  ", "http://hub:46357"),  # whitespace trimmed
        ("https://rendezvous.example:46357", "https://rendezvous.example:46357"),
    ],
)
def test_endpoint_normalization(given: str, expected: str) -> None:
    assert SlimConfig(node_endpoint=given).node_endpoint == expected


def test_default_endpoint() -> None:
    assert MyceliumConfig().slim.node_endpoint == "http://127.0.0.1:46357"


def test_connect_persists_endpoint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`mycelium connect <addr>` writes a normalized endpoint to global config."""
    # Isolate HOME (global config) and cwd (project config discovery) to temp.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["connect", "hub:46357"])
    assert result.exit_code == 0, result.output

    reloaded = MyceliumConfig.load()
    assert reloaded.slim.node_endpoint == "http://hub:46357"
