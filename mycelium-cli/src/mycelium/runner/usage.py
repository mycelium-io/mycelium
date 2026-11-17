# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What each agent on this machine uses: its RAM, CPU and processes.

An agent is what runs in its herdr pane, so what it uses is its pane's process
tree: the shell herdr started, the agent CLI in it and whatever that started,
such as MCP servers. herdr names the shell and the foreground processes
(``pane process-info``); one ``ps`` read gives every process's memory, CPU
time and parent, and the tree is everything under those. RAM is the tree's
resident memory; CPU is the percent of one core it used over the last minute,
from the change in its CPU time between reads.

What goes to the hub is numbers and, for each process, its program and its
arguments with anything that looks like a secret left out (``command_of``).
Nothing an agent's screen shows is read.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: How far back CPU is averaged.
WINDOW_S = 60.0
#: How many of an agent's processes are listed, heaviest first.
PROCESSES_MAX = 8
#: How much of a process's command is kept.
COMMAND_CHARS = 80

#: An argument or flag whose value is left out of a command.
_SECRETISH = re.compile(r"key|token|secret|passw|auth|credential|bearer|cookie", re.IGNORECASE)
#: A long run of letters and digits: a key or a token, more often than not.
_OPAQUE = re.compile(r"^[A-Za-z0-9_\-+/=.]{32,}$")


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    rss_kb: int
    #: CPU time used so far, in seconds.
    cpu_s: float
    #: How long it has run, in seconds.
    elapsed_s: float
    args: str


def _seconds(text: str) -> float:
    """``[[dd-]hh:]mm:ss[.ss]``, as ``ps`` prints CPU and elapsed time, in seconds."""
    days, _, rest = text.strip().rpartition("-")
    total = 0.0
    for part in rest.split(":"):
        total = total * 60 + float(part or 0)
    return total + (int(days) * 86400 if days else 0)


def read_ps() -> dict[int, Proc]:
    """Every process on this machine, from one ``ps`` read. ``{}`` without ``ps``."""
    if sys.platform == "win32":
        return {}
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,rss=,time=,etime=,args="],  # noqa: S607 - the system's ps
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    procs: dict[int, Proc] = {}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        try:
            pid, ppid, rss = int(parts[0]), int(parts[1]), int(parts[2])
            cpu, elapsed = _seconds(parts[3]), _seconds(parts[4])
        except ValueError:
            continue
        procs[pid] = Proc(pid, ppid, rss, cpu, elapsed, parts[5] if len(parts) > 5 else "")
    return procs


def tree(procs: dict[int, Proc], roots: set[int]) -> set[int]:
    """``roots`` and every process under them."""
    children: dict[int, list[int]] = {}
    for p in procs.values():
        children.setdefault(p.ppid, []).append(p.pid)
    found: set[int] = set()
    todo = [r for r in roots if r in procs]
    while todo:
        pid = todo.pop()
        if pid in found:
            continue
        found.add(pid)
        todo.extend(children.get(pid, []))
    return found


def end_foreground(
    info: dict[str, Any],
    *,
    ps: Any = read_ps,
    kill: Any = os.kill,
    alive: Any = None,
    wait_s: float = 5.0,
) -> list[int]:
    """End what runs in a pane's foreground and everything it started, leaving
    the pane's shell, so the pane stays open. Asked to stop first (SIGTERM);
    whatever is still running after ``wait_s`` is made to (SIGKILL). The
    processes ended, by pid; none when only the shell was there."""
    import signal

    from mycelium.utils.process import pid_alive

    alive = alive or pid_alive
    shell = info.get("shell_pid")
    foreground = {
        int(p["pid"])
        for p in info.get("foreground_processes") or []
        if isinstance(p, dict) and isinstance(p.get("pid"), int) and p.get("pid") != shell
    }
    if not foreground:
        return []
    targets = sorted(tree(ps(), foreground) - {shell}) or sorted(foreground)
    for pid in targets:
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            continue
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and any(alive(p) for p in targets):
        time.sleep(0.1)
    for pid in targets:
        if alive(pid):
            try:
                kill(pid, signal.SIGKILL)
            except OSError:
                continue
    return targets


def command_of(args: str) -> str:
    """A process's command as the hub may see it: its program's name and its
    arguments, with the home folder said as ``~`` and any value that looks
    like a secret (after a flag that names one, in ``KEY=value``, or a long
    opaque string) shown as ``…``."""
    home = str(Path.home())
    words = args.split()
    if not words:
        return ""
    out = [os.path.basename(words[0])]
    hide_next = False
    for word in words[1:]:
        if hide_next:
            out.append("…")
            hide_next = False
            continue
        name, eq, _ = word.partition("=")
        if eq and _SECRETISH.search(name):
            out.append(f"{name}=…")
        elif word.startswith("-") and _SECRETISH.search(word):
            out.append(word)
            hide_next = True
        elif _OPAQUE.match(word) and os.sep not in word:
            out.append("…")
        else:
            out.append(word.replace(home, "~"))
    command = " ".join(out)
    return command if len(command) <= COMMAND_CHARS else command[: COMMAND_CHARS - 1] + "…"


def name_of(args: str) -> str:
    """A process's program, as a name."""
    first = args.split(None, 1)[0] if args.strip() else ""
    return os.path.basename(first).lstrip("-") or "?"


def total_ram_mb() -> int | None:
    """This machine's memory, in MB; ``None`` when it can't be read."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],  # noqa: S607 - the system's sysctl
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            return int(out.strip()) // (1024 * 1024)
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


class Usage:
    """Reads what each pane's agent uses, keeping a minute of CPU times."""

    def __init__(self, ps: Any = read_ps, clock: Any = time.monotonic) -> None:
        self._ps = ps
        self._clock = clock
        #: (when, CPU seconds by pid), oldest first, back to ``WINDOW_S``.
        self._samples: deque[tuple[float, dict[int, float]]] = deque()

    def read(self, panes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """For each pane (its ``process_info`` from herdr), what its agent uses:
        ``ram_mb``, ``cpu`` (percent of one core; ``None`` until there's an
        earlier read to compare), ``up_s`` and ``processes``."""
        procs = self._ps()
        now = self._clock()
        cpu_now = {pid: p.cpu_s for pid, p in procs.items()}
        while self._samples and now - self._samples[0][0] > WINDOW_S:
            self._samples.popleft()
        before = self._samples[0] if self._samples else None
        self._samples.append((now, cpu_now))

        used: dict[str, dict[str, Any]] = {}
        for pane, info in panes.items():
            foreground = [
                int(p["pid"])
                for p in info.get("foreground_processes") or []
                if isinstance(p, dict) and isinstance(p.get("pid"), int)
            ]
            shell = info.get("shell_pid")
            roots = set(foreground) | ({shell} if isinstance(shell, int) else set())
            pids = tree(procs, roots)
            if not pids:
                continue
            cpu = None
            if before is not None and now > before[0]:
                then = before[1]
                spent = sum(max(0.0, cpu_now[p] - then[p]) for p in pids if p in then)
                cpu = round(100 * spent / (now - before[0]), 1)
            ordered = sorted((procs[p] for p in pids), key=lambda p: p.rss_kb, reverse=True)
            used[pane] = {
                "ram_mb": round(sum(procs[p].rss_kb for p in pids) / 1024),
                "cpu": cpu,
                "up_s": round(
                    max((procs[p].elapsed_s for p in foreground if p in procs), default=0)
                ),
                "processes": [
                    {
                        "name": name_of(p.args),
                        "command": command_of(p.args),
                        "ram_mb": round(p.rss_kb / 1024),
                    }
                    for p in ordered[:PROCESSES_MAX]
                ],
            }
        return used
