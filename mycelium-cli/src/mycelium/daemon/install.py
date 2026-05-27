# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Daemon service install/uninstall helpers — family-agnostic.

There is one cold-spawn daemon (``mycelium-cc-daemon``) per host, regardless
of how many cold-spawn families (claude_code, cursor, future Gemini/Codex/…)
are installed. This module owns the service-unit install/teardown logic that
all of those families consume via composition:

    # integrations/claude_code/install.py
    from mycelium.daemon.install import install_daemon_service
    def _step_claude_daemon_install(verbose: bool = False) -> None:
        install_daemon_service(verbose=verbose)

    # integrations/cursor/install.py
    from mycelium.daemon.install import install_daemon_service
    def _step_cursor_daemon_install(verbose: bool = False) -> None:
        install_daemon_service(verbose=verbose)

The two families both end up calling the same shared helper — the daemon
service unit is identical regardless of who asked for it.

Relocated verbatim from ``integrations/claude_code/install.py`` (L316-557)
on the feat/cursor-integration branch. The canonical on-disk names
(``io.mycelium.cc-daemon``, ``mycelium-cc-daemon``) stay; a future PR may
rename them to ``mycelium-daemon`` but that's a separate change.
"""

from __future__ import annotations

import importlib.resources
import os
import subprocess
import time
from pathlib import Path

import typer

#: launchd label / systemd service stem for the daemon.
CC_DAEMON_LABEL = "io.mycelium.cc-daemon"
CC_DAEMON_RUNNER = "mycelium-cc-daemon"


def cc_daemon_service_paths() -> tuple[Path, Path]:
    """Return (launchd_plist_path, systemd_service_path) for the current user."""
    home = Path.home()
    plist = home / "Library" / "LaunchAgents" / f"{CC_DAEMON_LABEL}.plist"
    systemd = home / ".config" / "systemd" / "user" / f"{CC_DAEMON_RUNNER}.service"
    return plist, systemd


def render_template(text: str, **vars_: str) -> str:
    """Tiny `{{ name }}` substitution — keeps Jinja off the daemon path."""
    out = text
    for k, v in vars_.items():
        out = out.replace("{{ " + k + " }}", v)
    return out


def resolve_python_binary() -> str:
    """Return an absolute path to the Python that loaded the CLI.

    The daemon runs via `python -m mycelium.daemon`, so we hardcode the
    Python that currently has `mycelium` installed. This avoids picking up
    a system Python that doesn't have the package, which was a frequent
    failure mode for the openclaw plugin's npm-install pattern.
    """
    import sys

    return sys.executable


def install_runner_script() -> Path:
    """Drop a thin runner script at ``~/.local/bin/mycelium-cc-daemon`` for
    operators who want to launch the daemon outside the service unit (e.g.
    from a tmux pane during development). Pure convenience — the service
    invokes the daemon directly via `python -m mycelium.daemon`.
    """
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    runner = bin_dir / CC_DAEMON_RUNNER
    python = resolve_python_binary()
    runner.write_text(f'#!/usr/bin/env bash\nexec "{python}" -m mycelium.daemon "$@"\n')
    runner.chmod(0o755)
    return runner


def read_service_template(name: str) -> str:
    """Read a daemon service template bundled inside the mycelium package."""
    pkg = importlib.resources.files("mycelium.daemon.service")
    src = Path(str(pkg)) / name
    if src.exists():
        return src.read_text()
    # Non-editable install: extract via importlib.resources
    ref = pkg / name
    return ref.read_text()


def wait_for_daemon_health(timeout_s: float = 6.0) -> dict | None:
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


def launchd_reload(
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
    subprocess.run(["launchctl", "bootout", target], capture_output=True)  # noqa: S603,S607
    # bootout is async — wait for the label to actually disappear (~5s cap).
    for _ in range(20):
        printed = subprocess.run(  # noqa: S603,S607
            ["launchctl", "print", target], capture_output=True
        )
        if printed.returncode != 0:  # not found → fully booted out
            break
        time.sleep(0.25)
    last = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    for attempt in range(5):
        last = subprocess.run(  # noqa: S603,S607
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


def install_daemon_service(verbose: bool = False) -> None:
    """Install mycelium-cc-daemon as a user-level service.

    Renders the right template (launchd on macOS, systemd --user on Linux),
    writes the unit file, registers it with the service manager, then polls
    the daemon's health socket to confirm it actually came up. The runner
    script (``~/.local/bin/mycelium-cc-daemon``) is bundled in for convenience.

    Family-agnostic — called by any cold-spawn family's ``--step=daemon`` flow
    (claude_code, cursor, future families). All of them want the same daemon.
    """
    import platform

    python = resolve_python_binary()
    home = str(Path.home())
    path_env = os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    log_path = str(Path.home() / ".mycelium" / "logs" / "cc-daemon.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    # Make sure the file exists so launchd/systemd can append to it cleanly.
    if not Path(log_path).exists():
        Path(log_path).touch()

    runner = install_runner_script()
    typer.secho(f"  runner: {runner}", fg=typer.colors.CYAN)

    plist_dst, systemd_dst = cc_daemon_service_paths()
    system = platform.system()

    if system == "Darwin":
        tmpl = read_service_template("launchd.plist.j2")
        rendered = render_template(
            tmpl, python_binary=python, home=home, path=path_env, log_path=log_path
        )
        plist_dst.parent.mkdir(parents=True, exist_ok=True)
        plist_dst.write_text(rendered)
        plist_dst.chmod(0o644)
        typer.secho(f"  unit:   {plist_dst}", fg=typer.colors.CYAN)
        # Reload cleanly if a previous version is loaded. bootout is async, so
        # this waits for teardown then retries bootstrap through the transient
        # "Input/output error 5" window instead of failing the install.
        rc, err = launchd_reload(CC_DAEMON_LABEL, f"gui/{os.getuid()}", plist_dst, verbose=verbose)
        if rc != 0:
            typer.secho(
                f"  launchctl bootstrap failed: {err}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
    elif system == "Linux":
        tmpl = read_service_template("systemd.service.j2")
        rendered = render_template(
            tmpl, python_binary=python, home=home, path=path_env, log_path=log_path
        )
        systemd_dst.parent.mkdir(parents=True, exist_ok=True)
        systemd_dst.write_text(rendered)
        systemd_dst.chmod(0o644)
        typer.secho(f"  unit:   {systemd_dst}", fg=typer.colors.CYAN)
        subprocess.run(  # noqa: S603,S607
            ["systemctl", "--user", "daemon-reload"], check=False
        )
        result = subprocess.run(  # noqa: S603,S607
            ["systemctl", "--user", "enable", "--now", f"{CC_DAEMON_RUNNER}.service"],
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

    health = wait_for_daemon_health(timeout_s=8.0)
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


def uninstall_daemon_service(verbose: bool = False) -> None:  # noqa: ARG001
    """Reverse a daemon install — stop the service, remove the unit file."""
    import platform

    plist_dst, systemd_dst = cc_daemon_service_paths()
    system = platform.system()

    if system == "Darwin":
        subprocess.run(  # noqa: S603,S607
            ["launchctl", "bootout", f"gui/{os.getuid()}/{CC_DAEMON_LABEL}"],
            capture_output=True,
        )
        if plist_dst.exists():
            plist_dst.unlink()
            typer.secho(f"  removed {plist_dst}", fg=typer.colors.CYAN)
    elif system == "Linux":
        subprocess.run(  # noqa: S603,S607
            ["systemctl", "--user", "disable", "--now", f"{CC_DAEMON_RUNNER}.service"],
            capture_output=True,
        )
        if systemd_dst.exists():
            systemd_dst.unlink()
            typer.secho(f"  removed {systemd_dst}", fg=typer.colors.CYAN)
        subprocess.run(  # noqa: S603,S607
            ["systemctl", "--user", "daemon-reload"], check=False
        )

    runner = Path.home() / ".local" / "bin" / CC_DAEMON_RUNNER
    if runner.exists():
        runner.unlink()
        typer.secho(f"  removed {runner}", fg=typer.colors.CYAN)
