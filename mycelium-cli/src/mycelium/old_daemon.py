# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Removing the background daemon earlier versions installed.

Before agents became resident ``await`` loops, ``mycelium install`` set up a
daemon as a launchd job (macOS) or a systemd user service (Linux) that ran
``python -m mycelium.daemon``. The daemon is gone from the CLI, but the job it
installed was never removed: it is set to restart forever, so it fails every
ten seconds into ``~/.mycelium/logs/cc-daemon.log`` until that file is
gigabytes. This stops and deletes it.

Only a unit under one of the names the daemon used, whose contents run
``mycelium.daemon``, is touched; anything else at that path is someone's own.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Every launchd label and systemd unit stem the daemon was ever installed under.
LAUNCHD_LABELS = ("io.mycelium.cc-daemon", "io.mycelium.daemon")
SYSTEMD_UNITS = ("mycelium-cc-daemon", "mycelium-daemon")

_MARKER = "mycelium.daemon"


def _ours(path: Path) -> bool:
    try:
        return _MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, capture_output=True, timeout=10, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        pass


def remove_old_daemon(home: Path | None = None) -> list[str]:
    """Stop and delete the old daemon's job, if this machine has one.

    Returns the units removed (empty when there were none). Never raises: a
    unit it cannot remove is left for the next run.
    """
    home = home or Path.home()
    removed: list[str] = []
    if sys.platform == "darwin":
        for label in LAUNCHD_LABELS:
            plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
            if not plist.is_file() or not _ours(plist):
                continue
            if shutil.which("launchctl"):
                _run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"])
            try:
                plist.unlink()
            except OSError:
                continue
            removed.append(label)
    elif sys.platform.startswith("linux"):
        for stem in SYSTEMD_UNITS:
            unit = home / ".config" / "systemd" / "user" / f"{stem}.service"
            if not unit.is_file() or not _ours(unit):
                continue
            if shutil.which("systemctl"):
                _run(["systemctl", "--user", "disable", "--now", f"{stem}.service"])
            try:
                unit.unlink()
            except OSError:
                continue
            if shutil.which("systemctl"):
                _run(["systemctl", "--user", "daemon-reload"])
            removed.append(f"{stem}.service")
    return removed
