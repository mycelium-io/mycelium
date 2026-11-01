# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet — manifest build, register/destroy semantics, describe.

Pins the dispatch-facet contract for the cursor family:

- ``build_manifest`` produces a valid ``AgentManifest(adapter="cursor")``
  with the cwd threaded through from the integration constructor.
- ``register`` writes nothing into the workspace: a Cursor agent learns how
  to take part from ``mycelium skill print``, like every other agent.
- ``destroy(full=False)`` leaves the workspace alone (the operator may be
  re-creating with a different cwd, or doesn't want their committed ``AGENTS.md``
  mutated by an unregister).
- ``destroy(full=True)`` clears the rule and AGENTS.md section an older
  ``register`` dropped.
- ``describe`` returns the next-steps block the wizard prints.
"""

from __future__ import annotations

from pathlib import Path

from mycelium.config import MyceliumConfig
from mycelium.integrations.agents.cursor import CursorIntegration
from mycelium.integrations.agents.cursor.workspace import (
    _AGENTS_SECTION_END,
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
)
from mycelium.integrations.base import AddOptions
from mycelium.protocol import AgentManifest


def _manifest(handle: str, cwd: str) -> AgentManifest:
    return AgentManifest(
        handle=handle,
        adapter="cursor",
        cwd=cwd,
        description="design system agent",
    )


def _old_install(cwd: Path) -> Path:
    """What an earlier ``register`` left in *cwd*: the rule, and AGENTS.md."""
    rule = cwd / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    rule.parent.mkdir(parents=True)
    rule.write_text("# Mycelium\n", encoding="utf-8")
    (cwd / "AGENTS.md").write_text(
        f"{_AGENTS_SECTION_START}\n# Mycelium Agent\n{_AGENTS_SECTION_END}\n", encoding="utf-8"
    )
    return rule


# ── build_manifest ───────────────────────────────────────────────────────────


def test_build_manifest_returns_cursor_adapter_with_cwd(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = integ.build_manifest(
        handle="design-agent",
        opts=AddOptions(room="r1"),
        description="d",
        allow_from=["@avery"],
    )
    assert manifest.adapter == "cursor"
    assert manifest.handle == "design-agent"
    assert manifest.cwd == str(tmp_path)
    assert manifest.allow_from == ["@avery"]


def test_build_manifest_allows_no_cwd_for_cursor() -> None:
    """cwd is optional — a cursor agent validates without one."""
    integ = CursorIntegration(cwd=None)
    manifest = integ.build_manifest(
        handle="x",
        opts=AddOptions(room="r"),
        description="",
        allow_from=[],
    )
    assert manifest.adapter == "cursor"
    assert manifest.cwd is None


# ── register: writes nothing ─────────────────────────────────────────────────


def test_register_writes_nothing_into_the_workspace(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    assert list(tmp_path.iterdir()) == []


# ── destroy: full=False vs full=True ─────────────────────────────────────────


def test_destroy_full_false_keeps_an_older_install(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    rule = _old_install(tmp_path)

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=False)

    # Untouched — the operator's AGENTS.md / committed rule stay.
    assert rule.exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_destroy_full_true_clears_an_older_install(tmp_path: Path) -> None:
    integ = CursorIntegration(cwd=str(tmp_path))
    manifest = _manifest("design-agent", str(tmp_path))
    rule = _old_install(tmp_path)

    integ.destroy(manifest=manifest, config=MyceliumConfig(), room="r", full=True)

    # Rule removed; AGENTS.md was only our section so the file itself is gone.
    assert not rule.exists()
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
