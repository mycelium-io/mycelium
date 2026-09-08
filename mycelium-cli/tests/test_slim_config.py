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
    # Env vars outrank persisted config in pydantic-settings, so an exported
    # MYCELIUM_SLIM_ENDPOINT (set when running the guarded live-node slices)
    # would shadow the value we just wrote. Isolate it (debt D12).
    monkeypatch.delenv("MYCELIUM_SLIM_ENDPOINT", raising=False)

    result = runner.invoke(app, ["connect", "hub:46357"])
    assert result.exit_code == 0, result.output

    reloaded = MyceliumConfig.load()
    assert reloaded.slim.node_endpoint == "http://hub:46357"


# ── identity tier: signerjwt and psk (retired spire degrades to psk) ──────────
@pytest.mark.parametrize(("given", "expected"), [("psk", "psk"), ("SignerJWT", "signerjwt")])
def test_identity_tiers(given: str, expected: str) -> None:
    assert SlimConfig(identity=given).identity == expected


def test_identity_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="must be 'psk' or 'signerjwt'"):
        SlimConfig(identity="attested")


def test_retired_spire_tier_degrades_to_psk() -> None:
    """A config.toml naming the retired spire tier degrades to psk."""
    with pytest.warns(UserWarning, match="retired"):
        assert SlimConfig(identity="spire").identity == "psk"
