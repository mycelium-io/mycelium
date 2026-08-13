# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code install facet — hook registration is empty + stale-cleanup
is exhaustive.

Hook registration is empty because knowledge extraction is handled
in-process; stale-cleanup covers the hooks a previous release may have
registered. Two invariants:

1. If ``_CLAUDE_CODE_HOOK_EVENTS`` ever drifts back to listing a hook,
   ``_register_claude_code_hooks`` would re-add a settings.json entry
   pointing at a hook script that the package no longer ships. Claude
   Code then aborts every spawn with ``SessionEnd hook ... not found``,
   which breaks autonomous coordination for ``claude_code`` agents.

2. ``_CLAUDE_CODE_STALE_HOOKS`` must list every hook event a previous
   release may have registered. If a stale entry isn't covered here, an
   upgrader keeps a broken hook in their settings.json forever (we
   don't reinstall it, but we also don't clean it up).

Both invariants are static — no runtime call required, no fixtures —
and pinning them here means a future "let's re-add a hook" PR has to
make the choice consciously.
"""

from __future__ import annotations

import json
from pathlib import Path

from mycelium.integrations.claude_code import install as claude_install


def test_hook_events_is_empty_so_reinstall_does_not_revive_stale_hooks() -> None:
    """The live hook list must be empty.

    With the assets bundle now omitting ``hooks/``, listing any event in
    ``_CLAUDE_CODE_HOOK_EVENTS`` would mean ``_register_claude_code_hooks``
    re-adds a settings.json entry every reinstall, pointing at a hook
    script that this package no longer ships. The next ``claude -p``
    spawn would then abort on the missing hook.
    """
    assert claude_install._CLAUDE_CODE_HOOK_EVENTS == [], (
        "Re-introducing a hook here is fine *only* if the assets bundle "
        "ships the matching script under hooks/. Otherwise this list "
        "must stay empty."
    )


def test_live_hooks_list_is_also_empty() -> None:
    """``_CLAUDE_CODE_HOOKS`` controls what gets copied from the assets
    bundle into ``~/.claude/hooks/``. It must agree with
    ``_CLAUDE_CODE_HOOK_EVENTS`` — both empty or both populated. A
    mismatch produces either dead files on disk or the missing-hook
    failure mode."""
    assert claude_install._CLAUDE_CODE_HOOKS == []


def test_stale_hooks_covers_every_known_retired_event() -> None:
    """Every retired hook script that any previous release of this
    adapter wired up must be listed in ``_CLAUDE_CODE_STALE_HOOKS`` so
    upgraders' settings.json gets cleaned up.

    This list is *append-only* — see the comment in install.py. We pin
    the current set so a refactor can't silently drop entries (which
    would leave upgraders pinned to a broken state).
    """
    stale = {(name, event) for name, event in claude_install._CLAUDE_CODE_STALE_HOOKS}
    # The five hooks earlier releases registered. If you're retiring a
    # *new* hook, append to ``_CLAUDE_CODE_STALE_HOOKS`` and add it here.
    expected = {
        ("mycelium-session-start.sh", "SessionStart"),
        ("mycelium-post-tool-use.sh", "PostToolUse"),
        ("mycelium-pre-compact.sh", "PreCompact"),
        ("mycelium-stop.sh", "Stop"),
        ("mycelium-session-end.sh", "SessionEnd"),
    }
    assert expected.issubset(stale), (
        "Removing a hook from _CLAUDE_CODE_STALE_HOOKS leaves upgraders "
        "stuck with that hook in their settings.json forever — append "
        "to the list, never delete entries."
    )


def test_mycelium_permission_is_added_idempotently(tmp_path: Path) -> None:
    """The install allowlists ``Bash(mycelium:*)`` in settings.json, preserving any
    existing permissions, and is a no-op on reinstall (no duplicate rules).

    This is what lets a background subagent — which can't answer a permission
    prompt — run ``mycelium await``/``respond`` unattended.
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    # A user who already has an unrelated allow-rule must keep it.
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": []}}))

    claude_install._register_claude_code_mycelium_permission(claude_dir)
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert claude_install._MYCELIUM_ALLOW_RULE in allow
    assert "Bash(ls:*)" in allow  # existing rule preserved

    # Reinstall must not duplicate the rule.
    claude_install._register_claude_code_mycelium_permission(claude_dir)
    allow2 = json.loads(settings.read_text())["permissions"]["allow"]
    assert allow2.count(claude_install._MYCELIUM_ALLOW_RULE) == 1


def test_mycelium_permission_bootstraps_absent_settings(tmp_path: Path) -> None:
    """With no settings.json at all, the install creates one carrying just the
    mycelium allow-rule — a fresh Claude Code user gets unattended participation
    with no manual step."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    claude_install._register_claude_code_mycelium_permission(claude_dir)

    settings = claude_dir / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert data["permissions"]["allow"] == [claude_install._MYCELIUM_ALLOW_RULE]


def test_stale_and_live_hook_lists_are_disjoint() -> None:
    """If a hook is in both ``_CLAUDE_CODE_STALE_HOOKS`` and the live
    ``_CLAUDE_CODE_HOOK_EVENTS``, ``_install_claude_code`` would
    re-introduce the entry on every reinstall: the cleanup loop strips
    it from settings.json, then the registration loop adds it right
    back, and claude_code spawns fail with ``SessionEnd hook ... not found``."""
    stale_events = {event for _name, event in claude_install._CLAUDE_CODE_STALE_HOOKS}
    live_events = {event for _name, event in claude_install._CLAUDE_CODE_HOOK_EVENTS}
    assert stale_events.isdisjoint(live_events), (
        f"hook events {stale_events & live_events} are listed as both stale "
        "and live — reinstall would loop forever between cleanup and "
        "re-registration"
    )
