# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code install facet — hook registration is empty + stale-cleanup
is exhaustive.

This adapter no longer ships hook scripts (the in-process knowledge
extractor handles what those wrappers used to do, with cleaner privacy
gates). The risk in that change is twofold:

1. If ``_CLAUDE_CODE_HOOK_EVENTS`` ever drifts back to listing a hook,
   ``_register_claude_code_hooks`` would re-add a settings.json entry
   pointing at a hook script that the package no longer ships. Claude
   Code then aborts every spawn with ``SessionEnd hook ... not found``
   — which is exactly the regression that broke autonomous coordination
   for ``claude_code`` agents in 2026-05.

2. ``_CLAUDE_CODE_STALE_HOOKS`` must list every hook event a previous
   release may have registered. If a stale entry isn't covered here, an
   upgrader keeps a broken hook in their settings.json forever (we
   don't reinstall it, but we also don't clean it up).

Both invariants are static — no runtime call required, no fixtures —
and pinning them here means a future "let's re-add a hook" PR has to
make the choice consciously.
"""

from __future__ import annotations

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


def test_stale_and_live_hook_lists_are_disjoint() -> None:
    """If a hook is in both ``_CLAUDE_CODE_STALE_HOOKS`` and the live
    ``_CLAUDE_CODE_HOOK_EVENTS``, ``_install_claude_code`` would
    re-introduce the entry on every reinstall: the cleanup loop strips
    it from settings.json, then the registration loop adds it right
    back. That's the exact bug we hit in 2026-05 when claude_code
    spawns started failing with ``SessionEnd hook ... not found``."""
    stale_events = {event for _name, event in claude_install._CLAUDE_CODE_STALE_HOOKS}
    live_events = {event for _name, event in claude_install._CLAUDE_CODE_HOOK_EVENTS}
    assert stale_events.isdisjoint(live_events), (
        f"hook events {stale_events & live_events} are listed as both stale "
        "and live — reinstall would loop forever between cleanup and "
        "re-registration"
    )
