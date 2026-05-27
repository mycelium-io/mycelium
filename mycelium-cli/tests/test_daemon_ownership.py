# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for cc-daemon handle ownership.

A claude_code agent is cold-spawned by the cc-daemon on the machine where it
was created. Ownership is recorded in cc-daemon.toml so a second machine that
syncs the room does not also dispatch it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.daemon import config as daemon_config
from mycelium.daemon.config import DaemonConfig


@pytest.fixture(autouse=True)
def _tmp_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect cc-daemon.toml to a temp file for each test."""
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "cc-daemon.toml")


# ── DaemonConfig.own_handle / disown_handle ──────────────────────────────────


def test_own_handle_adds_once() -> None:
    cfg = DaemonConfig()
    assert cfg.own_handle("builder") is True
    assert cfg.handles == ["builder"]
    # Idempotent — a second claim is a no-op and reports False.
    assert cfg.own_handle("builder") is False
    assert cfg.handles == ["builder"]


def test_disown_handle() -> None:
    cfg = DaemonConfig(handles=["builder", "echo"])
    assert cfg.disown_handle("builder") is True
    assert cfg.handles == ["echo"]
    # Removing something not owned reports False.
    assert cfg.disown_handle("builder") is False


def test_handles_round_trip_through_toml() -> None:
    cfg = DaemonConfig()
    cfg.own_handle("builder")
    cfg.save()
    reloaded = DaemonConfig.load()
    assert reloaded.handles == ["builder"]


def test_load_defaults_to_empty_handles() -> None:
    # No file on disk yet → empty ownership, not a crash.
    assert DaemonConfig.load().handles == []


# ── claude_code integration claims/releases ownership ────────────────────────


def _claude_code_manifest(handle: str):
    from mycelium.protocol import AgentManifest

    return AgentManifest(
        handle=handle,
        adapter="claude_code",
        cwd="/tmp",
        description="test agent",
    )


def test_claude_code_register_claims_ownership() -> None:
    from mycelium.config import MyceliumConfig
    from mycelium.integrations.base import AddOptions
    from mycelium.integrations.claude_code.dispatch import ClaudeCodeIntegration

    integ = ClaudeCodeIntegration()
    manifest = _claude_code_manifest("builder")
    integ.register(
        manifest=manifest,
        config=MyceliumConfig(),
        opts=AddOptions(room="r"),
    )
    assert DaemonConfig.load().handles == ["builder"]


def test_claude_code_destroy_releases_ownership() -> None:
    from mycelium.config import MyceliumConfig
    from mycelium.integrations.claude_code.dispatch import ClaudeCodeIntegration

    DaemonConfig(handles=["builder"]).save()
    integ = ClaudeCodeIntegration()
    integ.destroy(
        manifest=_claude_code_manifest("builder"),
        config=MyceliumConfig(),
        room="r",
        full=False,
    )
    assert DaemonConfig.load().handles == []
