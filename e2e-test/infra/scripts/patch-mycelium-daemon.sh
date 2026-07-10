#!/usr/bin/env bash
# Patch the baked mycelium CLI for supervisord foreground daemons in compose labs.
#
# Older wheels call systemctl when SIGHUP reload cannot find a PID. Containers
# run ``python -m mycelium.daemon --foreground`` under supervisord — patch
# install.py to discover that process via /proc and skip systemctl when absent.

set -euo pipefail

PY="${MYCELIUM_PYTHON:-/usr/local/share/uv/tools/mycelium-cli/bin/python}"

"$PY" <<'PY'
from __future__ import annotations

import mycelium
from pathlib import Path

path = Path(mycelium.__file__).parent / "daemon" / "install.py"
text = path.read_text()
if "_foreground_daemon_pid" in text and "mycelium.daemon" in text:
    print(f"[patch-mycelium-daemon] already patched {path}")
    raise SystemExit(0)

if "import shutil" not in text:
    text = text.replace("import signal\n", "import shutil\nimport signal\n", 1)

old_linux = '    if system == "Linux":\n        result = subprocess.run(  # noqa: S603,S607\n            ["systemctl", "--user", "show", f"{DAEMON_RUNNER}.service", "--property=MainPID"],'
new_linux = '    if system == "Linux" and shutil.which("systemctl"):\n        result = subprocess.run(  # noqa: S603,S607\n            ["systemctl", "--user", "show", f"{DAEMON_RUNNER}.service", "--property=MainPID"],'
if old_linux not in text:
    raise SystemExit(f"[patch-mycelium-daemon] systemd block not found in {path}")
text = text.replace(old_linux, new_linux, 1)

insert_after = "                        return pid\n\n    if system == \"Darwin\":"
proc_block = '''                        return pid

    if system == "Linux":
        pid = _foreground_daemon_pid()
        if pid is not None:
            return pid

    if system == "Darwin":'''
if insert_after not in text:
    raise SystemExit(f"[patch-mycelium-daemon] insert point not found in {path}")
text = text.replace(insert_after, proc_block, 1)

if "def _foreground_daemon_pid" not in text:
    fg_fn = '''

def _foreground_daemon_pid() -> int | None:
    """Find a foreground mycelium daemon process (no systemd unit)."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    markers = ("mycelium daemon run", "mycelium.daemon", DAEMON_RUNNER)
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\\x00", b" ").decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            continue
        if any(marker in cmdline for marker in markers):
            return int(entry.name)
    return None
'''
    anchor = "\n\ndef uninstall_daemon_service"
    if anchor not in text:
        raise SystemExit(f"[patch-mycelium-daemon] anchor not found in {path}")
    text = text.replace(anchor, fg_fn + anchor, 1)

restart_guard = '''        if not shutil.which("systemctl"):
            if verbose:
                typer.secho(
                    "systemctl not found; cannot restart daemon service",
                    fg=typer.colors.YELLOW,
                )
            return False
        subprocess.run(  # noqa: S603,S607
            ["systemctl", "--user", "restart", f"{DAEMON_RUNNER}.service"],'''
if restart_guard not in text:
    restart_old = '        subprocess.run(  # noqa: S603,S607\n            ["systemctl", "--user", "restart", f"{DAEMON_RUNNER}.service"],'
    if restart_old in text:
        text = text.replace(restart_old, restart_guard, 1)

path.write_text(text)
print(f"[patch-mycelium-daemon] patched {path}")
PY
