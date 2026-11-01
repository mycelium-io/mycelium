# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Clearing the Cursor rule and AGENTS.md section older versions dropped.

``uninstall_workspace_assets`` removes ``.cursor/rules/mycelium.mdc`` and
strips just the ``<!-- mycelium:start --> ... <!-- mycelium:end -->`` region
from AGENTS.md, preserving any surrounding content the user has added. If the
file was *only* that section, the file itself is removed.
"""

from __future__ import annotations

from pathlib import Path

from mycelium.integrations.agents.cursor.workspace import (
    _AGENTS_SECTION_END,
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
    _strip_agents_md_section,
    uninstall_workspace_assets,
)


def _wrapped(body: str) -> str:
    return f"{_AGENTS_SECTION_START}\n{body}\n{_AGENTS_SECTION_END}\n"


def _old_install(cwd: Path, *, agents_md: str | None = None) -> Path:
    """What an earlier ``agent create --adapter cursor`` left in *cwd*."""
    rule = cwd / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    rule.parent.mkdir(parents=True)
    rule.write_text("---\nalwaysApply: true\n---\n# Mycelium\n", encoding="utf-8")
    (cwd / "AGENTS.md").write_text(agents_md or _wrapped("# Mycelium Agent"), encoding="utf-8")
    return rule


# ── _strip_agents_md_section ────────────────────────────────────────────────


def test_strip_returns_none_when_no_section() -> None:
    assert _strip_agents_md_section("# just user content\n") is None


def test_strip_removes_marker_region_preserving_surroundings() -> None:
    content = "# Header\n\n" + _wrapped("ours") + "\n# Tail\n"
    stripped = _strip_agents_md_section(content)
    assert stripped is not None
    assert "ours" not in stripped
    assert _AGENTS_SECTION_START not in stripped
    assert "# Header" in stripped
    assert "# Tail" in stripped


# ── uninstall_workspace_assets ───────────────────────────────────────────────


def test_uninstall_removes_rule_and_strips_section(tmp_path: Path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    rule_path = _old_install(tmp_path, agents_md="# User\nstuff\n\n" + _wrapped("ours"))

    modified = uninstall_workspace_assets(tmp_path)

    assert not rule_path.exists()
    assert not (tmp_path / ".cursor").exists()  # the folders it made, now empty
    assert agents_path.exists()  # user content preserved
    remaining = agents_path.read_text(encoding="utf-8")
    assert "# User" in remaining
    assert _AGENTS_SECTION_START not in remaining
    assert rule_path in modified
    assert agents_path in modified


def test_uninstall_keeps_the_persons_other_cursor_rules(tmp_path: Path) -> None:
    rule_path = _old_install(tmp_path)
    theirs = rule_path.parent / "style.mdc"
    theirs.write_text("their rule", encoding="utf-8")

    uninstall_workspace_assets(tmp_path)

    assert not rule_path.exists()
    assert theirs.read_text(encoding="utf-8") == "their rule"


def test_uninstall_removes_agents_md_if_only_our_section(tmp_path: Path) -> None:
    """When only the mycelium section is left, the file itself is removed."""
    _old_install(tmp_path)

    uninstall_workspace_assets(tmp_path)

    assert not (tmp_path / "AGENTS.md").exists()


def test_uninstall_is_idempotent_on_missing_assets(tmp_path: Path) -> None:
    """A second uninstall is a no-op — no crash, empty modified list."""
    _old_install(tmp_path)
    uninstall_workspace_assets(tmp_path)
    assert uninstall_workspace_assets(tmp_path) == []
