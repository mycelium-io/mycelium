# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet — manifest build, register/destroy semantics, describe.

Pins the dispatch-facet contract for the cursor family:

- ``build_manifest`` produces a valid ``AgentManifest(adapter="cursor")``
  with the cwd threaded through from the integration constructor.
- ``register`` drops the workspace-local assets (``.cursor/rules/mycelium.mdc``
  + the mycelium section of ``AGENTS.md``) so a resident Cursor session knows how
  to coordinate. No runtime is started — cursor is a resident adapter.
- ``destroy(full=False)`` leaves the workspace alone (the operator may be
  re-creating with a different cwd, or doesn't want their committed ``AGENTS.md``
  mutated by an unregister).
- ``destroy(full=True)`` removes the workspace assets (symmetric with install).
- ``describe`` returns the next-steps block the wizard prints.
"""

from __future__ import annotations

from pathlib import Path

from mycelium.config import MyceliumConfig
from mycelium.integrations.base import AddOptions
from mycelium.integrations.cursor.dispatch import CursorIntegration
from mycelium.integrations.cursor.install import (
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
)
from mycelium.protocol import AgentManifest


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


def test_build_manifest_allows_no_cwd_for_cursor() -> None:
    """cwd is optional now — a cursor agent validates without one (it just
    won't drop workspace assets on register)."""
    integ = CursorIntegration(cwd=None)
    manifest = integ.build_manifest(
        handle="x",
        opts=AddOptions(room="r"),
        description="",
        budget=5.0,
        allow_from=[],
    )
    assert manifest.adapter == "cursor"
    assert manifest.cwd is None


# ── register: workspace assets ───────────────────────────────────────────────


def test_register_drops_workspace_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    assert (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert _AGENTS_SECTION_START in agents_text


def test_register_is_idempotent(tmp_path: Path) -> None:
    """Two register calls in a row leave identical workspace assets."""
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first


# ── destroy: full=False vs full=True ─────────────────────────────────────────


def test_destroy_full_false_keeps_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=False)

    # Assets preserved — operator's AGENTS.md / committed rule untouched.
    assert (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_destroy_full_true_removes_assets(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=True)

    # Rule removed; AGENTS.md was only our section so the file itself is gone.
    assert not (tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME).exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_destroy_full_true_with_missing_cwd_does_not_crash(tmp_path: Path) -> None:
    """Defensive: a manifest whose cwd directory was deleted out from under us
    still tears down cleanly — the integration moves on rather than raising."""
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path / "ghost"))

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=True)


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
