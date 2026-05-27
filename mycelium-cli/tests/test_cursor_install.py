# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Cursor install facet — workspace asset drop + idempotent AGENTS.md merge.

Pins the cursor-pkg milestone's three invariants:

1. ``install_workspace_assets`` drops exactly two files into a workspace:
   ``.cursor/rules/mycelium.mdc`` (owned wholly by mycelium, overwritten on
   every refresh) and ``AGENTS.md`` (non-destructive: writes only inside
   the ``<!-- mycelium:start --> ... <!-- mycelium:end -->`` markers).

2. The merge logic is idempotent across all three input states (no AGENTS.md,
   AGENTS.md with markers, AGENTS.md without markers) — a user can re-run
   the wizard or upgrade the adapter without their existing AGENTS.md
   content getting clobbered.

3. ``uninstall_workspace_assets`` is the exact inverse: removes the rule
   file and strips just the marker region from AGENTS.md, preserving any
   surrounding content the user has added. If the file was *only* our
   section, the file itself is removed (we didn't create an empty file
   the user didn't ask for).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium.integrations.cursor.install import (
    _AGENTS_SECTION_END,
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
    _strip_agents_md_section,
    _write_agents_md_section,
    install_workspace_assets,
    uninstall_workspace_assets,
)

# ── install_workspace_assets ─────────────────────────────────────────────────


def test_install_drops_both_assets_into_empty_workspace(tmp_path: Path) -> None:
    updated = install_workspace_assets(tmp_path)

    rule_path = tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    agents_path = tmp_path / "AGENTS.md"

    assert rule_path.exists()
    assert agents_path.exists()
    assert {rule_path, agents_path} == set(updated)

    # Sanity: bundled content carries our marker pair through to disk.
    agents_text = agents_path.read_text(encoding="utf-8")
    assert _AGENTS_SECTION_START in agents_text
    assert _AGENTS_SECTION_END in agents_text


def test_install_raises_for_missing_cwd(tmp_path: Path) -> None:
    """The integration's ``register`` lets this propagate so the command
    layer can print a friendly error rather than crashing on a stat call
    deep inside the asset write."""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(NotADirectoryError):
        install_workspace_assets(missing)


def test_install_is_idempotent_on_re_run(tmp_path: Path) -> None:
    """Two consecutive installs land identical content — no double-merge,
    no stacked separators, no churn on adapter upgrade."""
    install_workspace_assets(tmp_path)
    rule_path = tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    agents_path = tmp_path / "AGENTS.md"
    first_rule = rule_path.read_text(encoding="utf-8")
    first_agents = agents_path.read_text(encoding="utf-8")

    install_workspace_assets(tmp_path)

    assert rule_path.read_text(encoding="utf-8") == first_rule
    assert agents_path.read_text(encoding="utf-8") == first_agents


def test_install_preserves_user_content_in_existing_agents_md(tmp_path: Path) -> None:
    """A user (or another tool — Claude Code with --add-dir, for instance)
    may have populated AGENTS.md before cursor was wired in. The merge
    must NOT clobber that content; it appends our section."""
    agents_path = tmp_path / "AGENTS.md"
    user_content = "# My workspace\n\nNotes I wrote myself.\n"
    agents_path.write_text(user_content, encoding="utf-8")

    install_workspace_assets(tmp_path)

    merged = agents_path.read_text(encoding="utf-8")
    assert user_content.strip() in merged
    assert _AGENTS_SECTION_START in merged
    assert _AGENTS_SECTION_END in merged
    # Our content lands AFTER the user's, not before — the user's text is
    # at the top of the file where they put it.
    assert merged.index(user_content.strip()) < merged.index(_AGENTS_SECTION_START)


# ── _write_agents_md_section: the three input states ─────────────────────────


def _wrapped(body: str) -> str:
    return f"{_AGENTS_SECTION_START}\n{body}\n{_AGENTS_SECTION_END}\n"


def test_write_creates_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    _write_agents_md_section(path, _wrapped("hello"))
    assert path.read_text(encoding="utf-8") == _wrapped("hello")


def test_write_replaces_existing_marker_region(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text(
        "# Header\n\n" + _wrapped("old content") + "\n# Tail\n",
        encoding="utf-8",
    )
    _write_agents_md_section(path, _wrapped("new content"))
    text = path.read_text(encoding="utf-8")
    assert "old content" not in text
    assert "new content" in text
    # Surrounding content untouched.
    assert "# Header" in text
    assert "# Tail" in text


def test_write_appends_when_markers_absent(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# Existing\nuser stuff\n", encoding="utf-8")
    _write_agents_md_section(path, _wrapped("appended"))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Existing\nuser stuff\n")
    assert _AGENTS_SECTION_START in text
    assert "appended" in text


def test_write_skips_when_content_unchanged(tmp_path: Path) -> None:
    """Idempotency at the mtime level — re-running with identical input
    must not bump the file's modification time (relied on by setuptools
    file-watchers and CI diff checks)."""
    path = tmp_path / "AGENTS.md"
    _write_agents_md_section(path, _wrapped("same"))
    first_mtime = path.stat().st_mtime_ns

    _write_agents_md_section(path, _wrapped("same"))
    second_mtime = path.stat().st_mtime_ns
    assert first_mtime == second_mtime


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
    install_workspace_assets(tmp_path)
    # Pretend the user added their own content too.
    agents_path = tmp_path / "AGENTS.md"
    agents_text = agents_path.read_text(encoding="utf-8")
    agents_path.write_text("# User\nstuff\n\n" + agents_text, encoding="utf-8")

    modified = uninstall_workspace_assets(tmp_path)

    rule_path = tmp_path / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    assert not rule_path.exists()
    assert agents_path.exists()  # user content preserved
    remaining = agents_path.read_text(encoding="utf-8")
    assert "# User" in remaining
    assert _AGENTS_SECTION_START not in remaining
    assert rule_path in modified
    assert agents_path in modified


def test_uninstall_removes_agents_md_if_only_our_section(tmp_path: Path) -> None:
    """Symmetry: we never created an empty AGENTS.md the user didn't ask
    for, so when only our section remains, the file itself is removed."""
    install_workspace_assets(tmp_path)
    agents_path = tmp_path / "AGENTS.md"
    assert agents_path.exists()

    uninstall_workspace_assets(tmp_path)

    assert not agents_path.exists()


def test_uninstall_is_idempotent_on_missing_assets(tmp_path: Path) -> None:
    """A second uninstall is a no-op — no crash, empty modified list."""
    install_workspace_assets(tmp_path)
    uninstall_workspace_assets(tmp_path)
    modified = uninstall_workspace_assets(tmp_path)
    assert modified == []
