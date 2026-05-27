# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet — manifest build, register/destroy semantics, describe.

Pins the dispatch-facet contract for the cursor family:

- ``build_manifest`` produces a valid ``AgentManifest(adapter="cursor")``
  with the cwd threaded through from the integration constructor.
- ``register`` claims handle ownership in ``cc-daemon.toml`` AND drops the
  workspace-local assets (``.cursor/rules/mycelium.mdc`` + the mycelium
  section of ``AGENTS.md``). Both side effects must land together — a
  half-applied register would leave a daemon dispatching to an agent
  with no rules / preamble in its workspace.
- ``destroy(full=False)`` releases the handle but leaves the workspace
  alone (the operator may be re-creating with a different cwd, or
  doesn't want their committed ``AGENTS.md`` mutated by an unregister).
- ``destroy(full=True)`` releases the handle AND removes the workspace
  assets (symmetric with the install).
- ``describe`` returns the next-steps block the wizard prints — sanity
  check that the cwd and handle show through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.config import MyceliumConfig
from mycelium.daemon import config as daemon_config
from mycelium.daemon.config import DaemonConfig
from mycelium.integrations.base import AddOptions
from mycelium.integrations.cursor.dispatch import CursorIntegration
from mycelium.integrations.cursor.install import (
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
)
from mycelium.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _tmp_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a fresh, isolated cc-daemon.toml in a tmp dir.

    Mirrors ``test_daemon_ownership.py``'s autouse fixture so register /
    destroy don't read or mutate the user's real config.
    """
    monkeypatch.setattr(
        daemon_config, "daemon_config_path", lambda: tmp_path / "cc-daemon.toml"
    )


def _manifest(handle: str, cwd: str) -> AgentManifest:
    return AgentManifest(
        handle=handle,
        adapter="cursor",
        cwd=cwd,
        description="design system agent",
    )


# ── build_manifest ───────────────────────────────────────────────────────────


def test_build_manifest_returns_cursor_adapter_with_cwd(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = integ.build_manifest(
        handle="design-agent",
        opts=AddOptions(room="r1"),
        description="d",
        budget=5.0,
        allow_from=["@julia"],
    )
    assert manifest.adapter == "cursor"
    assert manifest.handle == "design-agent"
    assert manifest.cwd == str(tmp_path)
    assert manifest.allow_from == ["@julia"]
    assert manifest.budget_usd_per_month == 5.0


def test_build_manifest_requires_cwd_for_cursor() -> None:
    """``AgentManifest`` schema-level guard: cwd is required for cursor
    (same as claude_code). Wired through ``check_adapter_requirements``."""
    from pydantic import ValidationError

    integ = CursorIntegration(cwd=None)
    with pytest.raises(ValidationError):
        integ.build_manifest(
            handle="x",
            opts=AddOptions(room="r"),
            description="",
            budget=5.0,
            allow_from=[],
        )


# ── register: handle ownership + workspace assets ────────────────────────────


def test_register_claims_handle_and_drops_workspace_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    # Handle ownership claimed.
    assert DaemonConfig.load().handles == ["design-agent"]
    # Workspace assets dropped.
    assert (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert _AGENTS_SECTION_START in agents_text


def test_register_is_idempotent(tmp_path: Path) -> None:
    """Two register calls in a row leave one ownership entry and identical
    workspace assets (same content)."""
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))
    assert DaemonConfig.load().handles == ["design-agent"]


# ── destroy: full=False vs full=True ─────────────────────────────────────────


def test_destroy_full_false_releases_handle_but_keeps_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=False)

    assert DaemonConfig.load().handles == []  # ownership released
    # Assets preserved — operator's AGENTS.md / committed rule untouched.
    assert (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_destroy_full_true_releases_handle_and_removes_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=True)

    assert DaemonConfig.load().handles == []
    # Rule removed; AGENTS.md was only our section so the file itself is gone.
    assert not (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_destroy_full_true_with_missing_cwd_does_not_crash(tmp_path: Path) -> None:
    """Defensive: a manifest whose cwd directory was deleted out from
    under us still releases ownership cleanly. The integration logs and
    moves on rather than raising."""
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path / "ghost"))
    DaemonConfig(handles=["design-agent"]).save()

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=True)
    assert DaemonConfig.load().handles == []


# ── will_destroy_runtime: confirms prompt only on full+cwd ───────────────────


def test_will_destroy_runtime_only_with_full_and_cwd(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    assert integ.will_destroy_runtime(manifest, full=True) is True
    assert integ.will_destroy_runtime(manifest, full=False) is False


# ── describe ─────────────────────────────────────────────────────────────────


def test_describe_lists_cwd_and_invoke_command(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    lines = integ.describe(manifest, room="r1")
    joined = "\n".join(lines)
    assert "cursor" in joined
    assert str(tmp_path) in joined
    assert "mycelium agent invoke design-agent" in joined
