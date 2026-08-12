# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon dispatch routing — cursor + claude_code share one mycelium-daemon.

Pins three integration-level invariants the daemon-core refactor introduced:

1. ``DaemonConfig.binary_for("cursor") == "cursor-agent"`` by default, and
   the value round-trips through the toml file. Two cold-spawn families
   live on one host; the daemon picks the right CLI per-mention.

2. Lifecycle dispatch is family-agnostic: ``cold_spawn`` integrations
   override ``Integration.spawn``, ``long_lived_gateway`` integrations
   don't (and the daemon dispatch loop skips them).

3. Handle ownership in ``daemon.toml`` is family-blind: a single
   ``handles`` list serves both cursor and claude_code so a sibling
   daemon syncing a room via git doesn't double-dispatch either family.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.daemon import config as daemon_config
from mycelium.daemon.config import DaemonConfig
from mycelium.integrations import Integration, get_integration


@pytest.fixture(autouse=True)
def _tmp_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "daemon.toml")


# ── DaemonConfig.binary_for ──────────────────────────────────────────────────


def test_binary_for_returns_default_per_family() -> None:
    cfg = DaemonConfig()
    assert cfg.binary_for("claude_code") == "claude"
    assert cfg.binary_for("cursor") == "cursor-agent"


def test_binary_for_honours_override_and_round_trips() -> None:
    cfg = DaemonConfig(claude_binary="/opt/claude", cursor_binary="/opt/cursor-agent")
    cfg.save()
    reloaded = DaemonConfig.load()
    assert reloaded.binary_for("claude_code") == "/opt/claude"
    assert reloaded.binary_for("cursor") == "/opt/cursor-agent"


def test_binary_for_non_cold_spawn_family_returns_empty_string() -> None:
    """A family the daemon never cold-spawns has no binary. ``binary_for``
    returns an empty string so a programming bug that calls into it for the
    wrong family fails loudly rather than spawning ``claude`` against the
    wrong manifest."""
    assert DaemonConfig().binary_for("engine") == ""


# ── lifecycle dispatch routing ───────────────────────────────────────────────


def test_cold_spawn_families_share_one_daemon() -> None:
    """The two cold-spawn families both declare ``lifecycle="cold_spawn"``
    and both override ``Integration.spawn``. The daemon dispatch loop
    branches on lifecycle, not on family id — so a future Gemini /
    Codex / Aider integration that declares ``cold_spawn`` will be
    routed through the same loop the moment its class lands."""
    claude = get_integration("claude_code")
    cursor = get_integration("cursor")
    assert type(claude).lifecycle == "cold_spawn"
    assert type(cursor).lifecycle == "cold_spawn"
    assert type(claude).spawn is not Integration.spawn
    assert type(cursor).spawn is not Integration.spawn


# ── handle ownership is family-blind ─────────────────────────────────────────


def test_own_handle_serves_both_families() -> None:
    """A single ``handles`` list in daemon.toml works for both cursor
    and claude_code — the daemon doesn't need to know which family
    each handle belongs to (it discovers that by reading the agent
    manifest off disk at dispatch time)."""
    cfg = DaemonConfig()
    cfg.own_handle("claude-agent")
    cfg.own_handle("design-agent")  # cursor agent
    cfg.save()

    reloaded = DaemonConfig.load()
    assert set(reloaded.handles) == {"claude-agent", "design-agent"}

    # Disowning one leaves the other alone.
    assert reloaded.disown_handle("design-agent") is True
    reloaded.save()
    assert DaemonConfig.load().handles == ["claude-agent"]


def test_dispatch_loop_does_not_hard_code_family_names() -> None:
    """Guard against a regression: the daemon dispatch loop must NOT
    contain ``if manifest.adapter == "claude_code"`` or ``== "cursor"``
    style branches. The lifecycle discriminator is the only routing key."""
    src = (Path(__file__).resolve().parents[1] / "src/mycelium/daemon/dispatch.py").read_text(
        encoding="utf-8"
    )
    forbidden_patterns = [
        'manifest.adapter == "claude_code"',
        'manifest.adapter == "cursor"',
        'adapter == "claude_code"',
        'adapter == "cursor"',
    ]
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"daemon/dispatch.py contains hard-coded family branch {pat!r} — "
            "use integration.lifecycle / integration.spawn() instead"
        )
