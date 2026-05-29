# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code install facet — skill/hooks install + cc-daemon service core.

Relocated verbatim from ``commands/adapter.py`` so the single ``Integration``
contract (see ``integrations/base.py``) owns both the dispatch and install
facets per runtime family — closing #173. The typer command layer is now a
thin dispatcher over ``get_integration(...)``; nothing here changed behaviour.
"""

from __future__ import annotations

import json as json_module
from pathlib import Path

import typer

from mycelium.daemon.install import install_daemon_service, uninstall_daemon_service
from mycelium.integrations._resources import _resolve_asset

# ── constants (relocated verbatim from commands/adapter.py) ───────────────────

_CLAUDE_CODE_SKILL_NAME = "mycelium"
_CLAUDE_CODE_HOOKS: list[str] = []

# Hook filenames + settings.json events that earlier versions of this adapter
# wired up but no longer does. On reinstall we remove the file + settings.json
# entry so upgraders aren't left with broken wiring pointing at files that no
# longer exist. Append here when retiring a hook; never remove entries, or
# upgraders who skipped a version will keep the stale state.
_CLAUDE_CODE_STALE_HOOKS: list[tuple[str, str]] = [
    ("mycelium-session-start.sh", "SessionStart"),
    ("mycelium-post-tool-use.sh", "PostToolUse"),
    ("mycelium-pre-compact.sh", "PreCompact"),
    # The silent KXP hooks. KXP now fires from deliberate room writes only.
    ("mycelium-stop.sh", "Stop"),
    ("mycelium-session-end.sh", "SessionEnd"),
]
_CLAUDE_CODE_STALE_SCRIPTS = [
    "flush-batch.sh",
    "mycelium-api.sh",
    "mycelium-knowledge-extract.py",
]

_CLAUDE_CODE_STEPS = {
    "daemon": "install + register the mycelium-cc-daemon user service",
}


# ── skill + hooks install (relocated verbatim) ───────────────────────────────


def _install_claude_code(verbose: bool = False) -> None:
    """
    Install the bundled Claude Code adapter assets into ~/.claude/.

    Installs three files total — the adapter is deliberately minimal:

    - ``skills/mycelium/SKILL.md`` — the mycelium skill the agent invokes
      via ``/mycelium``.
    - ``hooks/mycelium-stop.sh`` + ``hooks/mycelium-session-end.sh`` — thin
      shell wrappers that pipe hook stdin into the knowledge extractor as a
      background process.
    - ``hooks/mycelium-knowledge-extract.py`` — the actual work: reads the
      Claude Code transcript, ships the last turn to the backend if
      (and only if) both opt-in gates are on.

    Also rewrites ``settings.json`` to register Stop + SessionEnd, and
    *removes* any wiring + hook files from earlier adapter versions that
    this release no longer installs (see ``_CLAUDE_CODE_STALE_*``).
    """
    claude_dir = Path.home() / ".claude"

    # Skill
    skill_src = _resolve_asset(f"skills/{_CLAUDE_CODE_SKILL_NAME}", family="claude_code")
    skill_dst = claude_dir / "skills" / _CLAUDE_CODE_SKILL_NAME
    skill_dst.mkdir(parents=True, exist_ok=True)
    for f in skill_src.iterdir():
        dest = skill_dst / f.name
        dest.write_bytes(f.read_bytes())
        if verbose:
            typer.echo(f"  skill: {dest}")

    # Hooks
    # When the live hook list is empty (the current state — earlier
    # ``settings.json`` hook wiring was pulled out for privacy/clarity),
    # the bundled ``assets/hooks/`` directory is intentionally absent. Bail
    # out *before* calling :func:`_resolve_asset`, which would otherwise
    # crash on the missing-resource branch when the package is editable.
    # The cleanup loop further down still removes any pre-existing hook
    # files left over from older installs.
    if _CLAUDE_CODE_HOOKS:
        hooks_src = _resolve_asset("hooks", family="claude_code")
        hooks_dst = claude_dir / "hooks"
        hooks_dst.mkdir(parents=True, exist_ok=True)
        for hook_name in _CLAUDE_CODE_HOOKS:
            src_file = hooks_src / hook_name
            if not src_file.exists():
                if verbose:
                    typer.echo(f"  skip (not found): {hook_name}")
                continue
            dst_file = hooks_dst / hook_name
            dst_file.write_bytes(src_file.read_bytes())
            dst_file.chmod(0o755)
            if verbose:
                typer.echo(f"  hook: {dst_file}")

    # Snapshot the user's settings.json before any mutation. Incrementally
    # numbered so prior backups are never overwritten. We tell the user
    # exactly where it lives so a bad install can be rolled back with cp.
    backup_path = _backup_claude_settings(claude_dir)
    if backup_path is not None:
        typer.secho(f"  settings.json backup: {backup_path}", fg=typer.colors.CYAN)

    # Clean up hooks + scripts + settings.json entries from earlier versions
    # before rewriting the live wiring.
    _cleanup_stale_claude_code_assets(claude_dir, verbose=verbose)

    # Register lifecycle hooks in settings.json so Claude Code actually fires them.
    _register_claude_code_hooks(claude_dir, verbose=verbose)


# Maps hook script name → Claude Code hook event name. Must stay aligned
# with ``_CLAUDE_CODE_HOOKS`` above: registering a hook in settings.json
# without a matching script file results in Claude Code aborting with
# ``SessionEnd hook ... not found`` on every spawn — which is exactly what
# trips up cold-spawned agents the moment they try to honour an autonomous
# coordination_tick. Currently the live hook list is empty, so this list
# is empty too.
_CLAUDE_CODE_HOOK_EVENTS: list[tuple[str, str]] = []


def _register_claude_code_hooks(claude_dir: Path, verbose: bool = False) -> None:
    """Wire the mycelium lifecycle hooks into Claude Code's settings.json.

    Claude Code only invokes hooks that are registered under the matching
    event key in ``~/.claude/settings.json``. Dropping the scripts into
    ``~/.claude/hooks/`` isn't enough — without this registration the
    events never fire and the whole adapter is dead weight. Idempotent:
    skips events that already point at the same command.
    """
    settings_path = claude_dir / "settings.json"

    try:
        if settings_path.exists():
            settings = json_module.loads(settings_path.read_text())
        else:
            settings = {}

        hooks = settings.setdefault("hooks", {})
        registered: list[str] = []
        already: list[str] = []

        for script_name, event in _CLAUDE_CODE_HOOK_EVENTS:
            hook_command = str(claude_dir / "hooks" / script_name)
            event_entries = hooks.setdefault(event, [])

            duplicate = any(
                h.get("command", "") == hook_command
                for entry in event_entries
                for h in entry.get("hooks", [])
            )
            if duplicate:
                already.append(event)
                continue

            event_entries.append(
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command,
                            "timeout": 15,
                        }
                    ],
                }
            )
            registered.append(event)

        settings_path.write_text(json_module.dumps(settings, indent=2) + "\n")
        if verbose:
            for event in registered:
                typer.echo(f"  registered {event} hook")
            for event in already:
                typer.echo(f"  {event} hook already registered")
    except Exception as e:
        if verbose:
            typer.echo(f"  warning: could not register hooks: {e}")


def _backup_claude_settings(claude_dir: Path) -> Path | None:
    """Snapshot ``~/.claude/settings.json`` to an incrementally-numbered backup.

    Written adjacent to the original so users find it easily —
    ``~/.claude/settings.json.mycelium-backup.<N>``. ``N`` starts at 1 and
    increments until we find an unused slot; we never overwrite an
    existing backup. Returns the backup path, or ``None`` if there was
    nothing to back up or the write failed. Safe to call on every install
    — if settings.json didn't change since the last backup, the newest
    backup is still an exact duplicate, which is the safest failure mode.
    """
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        return None
    n = 1
    while True:
        candidate = claude_dir / f"settings.json.mycelium-backup.{n}"
        if not candidate.exists():
            break
        n += 1
    try:
        candidate.write_bytes(settings_path.read_bytes())
        return candidate
    except OSError:
        return None


def _cleanup_stale_claude_code_assets(claude_dir: Path, verbose: bool = False) -> None:
    """Remove hook files, scripts, and settings.json entries from earlier adapter versions.

    Earlier versions of the claude-code adapter wired up session-start /
    post-tool-use / pre-compact hooks plus a shell-script batch-flush
    pipeline. Those are no longer installed. If we don't actively clean
    them up, upgraders end up with stale hook files on disk and stale
    settings.json entries pointing at scripts that still exist but no
    longer match the current design — at best confusing, at worst they
    keep running old behavior the user doesn't want.

    Safe to run repeatedly — missing files / entries are ignored.
    """
    # 1) Stale hook files under ~/.claude/hooks/
    hooks_dir = claude_dir / "hooks"
    for script_name, _event in _CLAUDE_CODE_STALE_HOOKS:
        p = hooks_dir / script_name
        if p.exists():
            try:
                p.unlink()
                if verbose:
                    typer.echo(f"  removed stale hook: {p}")
            except OSError as e:
                if verbose:
                    typer.echo(f"  warning: could not remove {p}: {e}")

    # 2) Stale support scripts under ~/.claude/scripts/
    scripts_dir = claude_dir / "scripts"
    if scripts_dir.exists():
        for script_name in _CLAUDE_CODE_STALE_SCRIPTS:
            p = scripts_dir / script_name
            if p.exists():
                try:
                    p.unlink()
                    if verbose:
                        typer.echo(f"  removed stale script: {p}")
                except OSError as e:
                    if verbose:
                        typer.echo(f"  warning: could not remove {p}: {e}")
        # Remove the scripts dir if it's now empty so we don't leave a
        # dangling directory behind.
        try:
            if not any(scripts_dir.iterdir()):
                scripts_dir.rmdir()
        except OSError:
            pass

    # 3) Stale settings.json event registrations
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        return
    try:
        settings = json_module.loads(settings_path.read_text())
    except (OSError, json_module.JSONDecodeError):
        return
    hooks = settings.get("hooks") or {}
    changed = False
    for script_name, event in _CLAUDE_CODE_STALE_HOOKS:
        stale_command = str(hooks_dir / script_name)
        entries = hooks.get(event)
        if not entries:
            continue
        kept = []
        for entry in entries:
            inner = entry.get("hooks") or []
            filtered = [h for h in inner if h.get("command", "") != stale_command]
            if not filtered:
                # Entry had only the stale command — drop the whole entry.
                changed = True
                continue
            if len(filtered) != len(inner):
                changed = True
                entry = {**entry, "hooks": filtered}
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            # No entries remain for this event — drop the key so we don't
            # leave a dangling empty array in settings.json.
            hooks.pop(event, None)
            changed = True
    if changed:
        settings["hooks"] = hooks
        try:
            settings_path.write_text(json_module.dumps(settings, indent=2) + "\n")
            if verbose:
                typer.echo("  pruned stale settings.json entries")
        except OSError as e:
            if verbose:
                typer.echo(f"  warning: could not rewrite settings.json: {e}")


# ── cc-daemon user-service install / uninstall ───────────────────────────────
#
# The daemon mirrors the OpenClaw gateway for Claude Code agents. It runs as a
# user-level service that subscribes to room SSE, watches for `@handle`
# mentions of agents registered under `agents/<handle>`, and dispatches them to
# `claude -p` spawns. See `mycelium.daemon` for the dispatch implementation.
#
# The daemon service install/uninstall is shared with every cold-spawn family
# (currently claude_code, soon cursor) via composition — see
# ``mycelium.daemon.install``. The wrappers below add the family-specific bits
# (currently none) on top of the shared install path.


def _step_claude_daemon_install(verbose: bool = False) -> None:
    """Install the cc-daemon — claude_code's ``--step=daemon`` entrypoint.

    Currently a thin pass-through to the shared family-agnostic helper.
    Kept as a separate function so any future claude_code-specific daemon
    setup (e.g. binary discovery, settings checks) lands here without
    pulling family logic into ``daemon/install.py``.
    """
    install_daemon_service(verbose=verbose)


def _step_claude_daemon_uninstall(verbose: bool = False) -> None:
    """Reverse :func:`_step_claude_daemon_install`."""
    uninstall_daemon_service(verbose=verbose)
