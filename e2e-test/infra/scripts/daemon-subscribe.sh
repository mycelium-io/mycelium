#!/usr/bin/env bash
# Subscribe the supervisord-managed mycelium-daemon to a room in compose labs.
#
# ``mycelium daemon subscribe`` falls back to systemctl when SIGHUP fails on
# older CLI builds. Containers run the daemon in the foreground under
# supervisord — this script updates daemon.toml and signals the process
# directly.

set -euo pipefail

ROOM="${1:?usage: daemon-subscribe.sh <room>}"
PY="${MYCELIUM_PYTHON:-/usr/local/share/uv/tools/mycelium-cli/bin/python}"

"$PY" - "$ROOM" <<'PY'
import os
import signal
import subprocess
import sys

from mycelium.daemon.config import DaemonConfig

room = sys.argv[1]
cfg = DaemonConfig.load()
if room not in cfg.rooms:
    cfg.rooms.append(room)
    cfg.save()
    print(f"[daemon-subscribe] added {room}")
else:
    print(f"[daemon-subscribe] already subscribed to {room}")

proc = subprocess.run(
    ["pgrep", "-f", "mycelium.daemon"],
    capture_output=True,
    text=True,
    check=False,
)
if proc.returncode != 0 or not proc.stdout.strip():
    raise SystemExit("[daemon-subscribe] no foreground mycelium daemon found")
pid = int(proc.stdout.strip().split()[0])
os.kill(pid, signal.SIGHUP)
print(f"[daemon-subscribe] sent SIGHUP to pid {pid}")
PY
