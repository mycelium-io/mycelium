# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Claude Code install facet — skill/hooks install + cc-daemon service core.

Relocated verbatim from ``commands/adapter.py`` so the single ``Integration``
contract (see ``integrations/base.py``) owns both the dispatch and install
facets per runtime family — closing #173. The typer command layer is now a
thin dispatcher over ``get_integration(...)``; nothing here changed behaviour.
"""

from __future__ import annotations

import importlib.resources
import json as json_module
import os
import subprocess
import time
from pathlib import Path

import typer

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
    skill_src = _resolve_asset(f"skills/{_CLAUDE_CODE_SKILL_NAME}", adapter="claude-code")
    skill_dst = claude_dir / "skills" / _CLAUDE_CODE_SKILL_NAME
    skill_dst.mkdir(parents=True, exist_ok=True)
    for f in skill_src.iterdir():
        dest = skill_dst / f.name
        dest.write_bytes(f.read_bytes())
        if verbose:
            typer.echo(f"  skill: {dest}")

    # Hooks
    hooks_src = _resolve_asset("hooks", adapter="claude-code")
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


# Maps hook script name → Claude Code hook event name. The knowledge-extract
# python script is NOT registered directly: it's invoked by the stop /
# session-end shell hooks which forward stdin to it.
_CLAUDE_CODE_HOOK_EVENTS: list[tuple[str, str]] = [
    ("mycelium-stop.sh", "Stop"),
    ("mycelium-session-end.sh", "SessionEnd"),
]


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


# ── cc-daemon user-service install / uninstall (relocated verbatim) ──────────

# ── claude-code --step=daemon ─────────────────────────────────────────────────
#
# The daemon mirrors the OpenClaw gateway for Claude Code agents. It runs as a
# user-level service that subscribes to room SSE, watches for `@handle`
# mentions of agents registered under `agents/<handle>`, and dispatches them to
# `claude -p` spawns. See `mycelium.daemon` for the dispatch implementation.


_CC_DAEMON_LABEL = "io.mycelium.cc-daemon"
_CC_DAEMON_RUNNER = "mycelium-cc-daemon"


def _cc_daemon_service_paths() -> tuple[Path, Path]:
    """Return (launchd_plist_path, systemd_service_path) for the current user."""
    home = Path.home()
    plist = home / "Library" / "LaunchAgents" / f"{_CC_DAEMON_LABEL}.plist"
    systemd = home / ".config" / "systemd" / "user" / f"{_CC_DAEMON_RUNNER}.service"
    return plist, systemd


def _render_template(text: str, **vars_: str) -> str:
    """Tiny `{{ name }}` substitution — keeps Jinja off the daemon path."""
    out = text
    for k, v in vars_.items():
        out = out.replace("{{ " + k + " }}", v)
    return out


def _resolve_python_binary() -> str:
    """Return an absolute path to the Python that loaded the CLI.

    The daemon runs via `python -m mycelium.daemon`, so we hardcode the
    Python that currently has `mycelium` installed. This avoids picking up
    a system Python that doesn't have the package, which was a frequent
    failure mode for the openclaw plugin's npm-install pattern.
    """
    import sys

    return sys.executable


def _install_runner_script() -> Path:
    """Drop a thin runner script at ``~/.local/bin/mycelium-cc-daemon`` for
    operators who want to launch the daemon outside the service unit (e.g.
    from a tmux pane during development). Pure convenience — the service
    invokes the daemon directly via `python -m mycelium.daemon`.
    """
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    runner = bin_dir / _CC_DAEMON_RUNNER
    python = _resolve_python_binary()
    runner.write_text(f'#!/usr/bin/env bash\nexec "{python}" -m mycelium.daemon "$@"\n')
    runner.chmod(0o755)
    return runner


def _read_service_template(name: str) -> str:
    """Read a daemon service template bundled inside the mycelium package."""
    pkg = importlib.resources.files("mycelium.daemon.service")
    src = Path(str(pkg)) / name
    if src.exists():
        return src.read_text()
    # Non-editable install: extract via importlib.resources
    ref = pkg / name
    return ref.read_text()


def _wait_for_daemon_health(timeout_s: float = 6.0) -> dict | None:
    """Poll the daemon's unix-socket /health until it responds, or timeout."""
    from mycelium.daemon.health import read_health_blocking

    deadline = time.time() + timeout_s
    last: dict | None = None
    while time.time() < deadline:
        last = read_health_blocking(timeout=1.0)
        if last is not None:
            return last
        time.sleep(0.3)
    return last


def _launchd_reload(
    label: str, domain: str, plist_path: Path, *, verbose: bool = False
) -> tuple[int, str]:
    """Reload a launchd agent: bootout, wait for it to clear, then bootstrap.

    ``launchctl bootout`` is asynchronous. A ``bootstrap`` issued before the
    previous instance has finished tearing down races and fails with
    "Bootstrap failed: 5: Input/output error", leaving the service down — the
    exact failure mode hit when re-running ``--step=daemon`` on a machine that
    already has the daemon loaded. We poll until the label is actually gone,
    then retry ``bootstrap`` through the transient EIO window.

    Returns ``(returncode, error_message)`` — ``(0, "")`` on success.
    """
    target = f"{domain}/{label}"
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    # bootout is async — wait for the label to actually disappear (~5s cap).
    for _ in range(20):
        printed = subprocess.run(["launchctl", "print", target], capture_output=True)
        if printed.returncode != 0:  # not found → fully booted out
            break
        time.sleep(0.25)
    last = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    for attempt in range(5):
        last = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            capture_output=True,
            text=True,
        )
        if last.returncode == 0:
            return 0, ""
        err = (last.stderr or last.stdout or "").strip()
        # Transient teardown race — back off and retry; surface anything else.
        if "Input/output error" in err or "Bootstrap failed: 5" in err:
            if verbose:
                typer.echo(f"  bootstrap retry {attempt + 1}/5 ({err})")
            time.sleep(0.5 * (attempt + 1))
            continue
        return last.returncode, err
    return last.returncode, (last.stderr or last.stdout or "").strip()


def _step_claude_daemon_install(verbose: bool = False) -> None:
    """Install mycelium-cc-daemon as a user-level service.

    Renders the right template (launchd on macOS, systemd --user on Linux),
    writes the unit file, registers it with the service manager, then polls
    the daemon's health socket to confirm it actually came up. The runner
    script (~/.local/bin/mycelium-cc-daemon) is bundled in for convenience.
    """
    import platform

    python = _resolve_python_binary()
    home = str(Path.home())
    path_env = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    log_path = str(Path.home() / ".mycelium" / "logs" / "cc-daemon.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    # Make sure the file exists so launchd/systemd can append to it cleanly.
    if not Path(log_path).exists():
        Path(log_path).touch()

    runner = _install_runner_script()
    typer.secho(f"  runner: {runner}", fg=typer.colors.CYAN)

    plist_dst, systemd_dst = _cc_daemon_service_paths()
    system = platform.system()

    if system == "Darwin":
        tmpl = _read_service_template("launchd.plist.j2")
        rendered = _render_template(
            tmpl, python_binary=python, home=home, path=path_env, log_path=log_path
        )
        plist_dst.parent.mkdir(parents=True, exist_ok=True)
        plist_dst.write_text(rendered)
        plist_dst.chmod(0o644)
        typer.secho(f"  unit:   {plist_dst}", fg=typer.colors.CYAN)
        # Reload cleanly if a previous version is loaded. bootout is async, so
        # this waits for teardown then retries bootstrap through the transient
        # "Input/output error 5" window instead of failing the install.
        rc, err = _launchd_reload(
            _CC_DAEMON_LABEL, f"gui/{os.getuid()}", plist_dst, verbose=verbose
        )
        if rc != 0:
            typer.secho(
                f"  launchctl bootstrap failed: {err}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
    elif system == "Linux":
        tmpl = _read_service_template("systemd.service.j2")
        rendered = _render_template(
            tmpl, python_binary=python, home=home, path=path_env, log_path=log_path
        )
        systemd_dst.parent.mkdir(parents=True, exist_ok=True)
        systemd_dst.write_text(rendered)
        systemd_dst.chmod(0o644)
        typer.secho(f"  unit:   {systemd_dst}", fg=typer.colors.CYAN)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{_CC_DAEMON_RUNNER}.service"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            typer.secho(
                f"  systemctl enable failed: {result.stderr.strip() or result.stdout.strip()}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
    else:
        typer.secho(
            f"  unsupported platform '{system}' — only macOS and Linux are wired up. "
            f"Run the daemon manually with: {python} -m mycelium.daemon",
            fg=typer.colors.YELLOW,
        )
        return

    health = _wait_for_daemon_health(timeout_s=8.0)
    if health is None:
        typer.secho(
            "  daemon did not respond on the health socket within 8s — "
            "check logs at ~/.mycelium/logs/cc-daemon.log.",
            fg=typer.colors.YELLOW,
        )
        return

    rooms = health.get("rooms_configured") or []
    if not rooms:
        typer.secho(
            "  ✓ daemon running (no rooms configured yet). "
            "Subscribe with: mycelium daemon subscribe <room>",
            fg=typer.colors.GREEN,
        )
    else:
        typer.secho(
            f"  ✓ daemon running, subscribed to: {', '.join(rooms)}",
            fg=typer.colors.GREEN,
        )


def _step_claude_daemon_uninstall(verbose: bool = False) -> None:
    """Reverse a daemon install — stop the service, remove the unit file."""
    import platform

    plist_dst, systemd_dst = _cc_daemon_service_paths()
    system = platform.system()

    if system == "Darwin":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{_CC_DAEMON_LABEL}"],
            capture_output=True,
        )
        if plist_dst.exists():
            plist_dst.unlink()
            typer.secho(f"  removed {plist_dst}", fg=typer.colors.CYAN)
    elif system == "Linux":
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{_CC_DAEMON_RUNNER}.service"],
            capture_output=True,
        )
        if systemd_dst.exists():
            systemd_dst.unlink()
            typer.secho(f"  removed {systemd_dst}", fg=typer.colors.CYAN)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    runner = Path.home() / ".local" / "bin" / _CC_DAEMON_RUNNER
    if runner.exists():
        runner.unlink()
        typer.secho(f"  removed {runner}", fg=typer.colors.CYAN)
    typer.secho("  ✓ daemon uninstalled.", fg=typer.colors.GREEN)
