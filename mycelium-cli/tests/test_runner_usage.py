# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What an agent uses, read from its pane's process tree (``runner/usage.py``),
and ending what runs in a pane while keeping the pane."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

from mycelium.runner import usage
from mycelium.runner.usage import Proc, Usage, command_of, end_foreground, tree


def test_a_command_keeps_its_program_and_leaves_out_what_looks_secret():
    home = str(Path.home())
    assert command_of(f"{home}/.local/bin/claude --resume 4f1c") == "claude --resume 4f1c"
    assert (
        command_of("node server.js --token abc --port 3000")
        == "node server.js --token … --port 3000"
    )
    assert command_of("env API_KEY=sk-live-123 run") == "env API_KEY=… run"
    assert command_of("tool " + "Zx9" * 15) == "tool …"
    assert command_of(f"python {home}/mcp/server.py") == "python ~/mcp/server.py"
    assert len(command_of("x " + "word " * 40)) == usage.COMMAND_CHARS


def test_ps_times_read_as_seconds():
    assert usage._seconds("0:01.50") == 1.5
    assert usage._seconds("01:02:03") == 3723
    assert usage._seconds("2-00:00:10") == 2 * 86400 + 10


def test_a_tree_is_its_roots_and_everything_under_them():
    procs = {
        p: Proc(p, parent, 0, 0, 0, "") for p, parent in [(1, 0), (2, 1), (3, 2), (4, 1), (9, 0)]
    }
    assert tree(procs, {2}) == {2, 3}
    assert tree(procs, {1}) == {1, 2, 3, 4}
    assert tree(procs, {42}) == set()


def test_cpu_is_averaged_over_the_last_minute():
    cpu = {"t": 0.0}
    clock = [0.0]
    reader = Usage(ps=lambda: {5: Proc(5, 1, 1024, cpu["t"], 1, "agent")}, clock=lambda: clock[0])
    pane = {"p": {"foreground_processes": [{"pid": 5}]}}
    assert reader.read(pane)["p"]["cpu"] is None
    clock[0], cpu["t"] = 20.0, 10.0
    assert reader.read(pane)["p"]["cpu"] == 50.0
    # Past the minute, the oldest read is let go: from 20s to 80s, 4s of CPU.
    clock[0], cpu["t"] = 80.0, 14.0
    assert reader.read(pane)["p"]["cpu"] == 6.7


def test_a_pane_with_nothing_running_reports_nothing():
    reader = Usage(ps=dict)
    assert reader.read({"p": {"shell_pid": 7, "foreground_processes": []}}) == {}


def test_ending_a_pane_stops_what_runs_in_it_and_leaves_its_shell():
    procs = {
        100: Proc(100, 1, 0, 0, 0, "-zsh"),
        200: Proc(200, 100, 0, 0, 0, "claude"),
        300: Proc(300, 200, 0, 0, 0, "mcp"),
    }
    sent: list[tuple[int, int]] = []
    stubborn = {300}
    info = {"shell_pid": 100, "foreground_processes": [{"pid": 200}]}

    ended = end_foreground(
        info,
        ps=lambda: procs,
        kill=lambda pid, sig: sent.append((pid, sig)),
        alive=lambda pid: pid in stubborn,
        wait_s=0.2,
    )

    assert ended == [200, 300]
    assert (100, signal.SIGTERM) not in sent
    assert sent[:2] == [(200, signal.SIGTERM), (300, signal.SIGTERM)]
    # What didn't stop when asked is made to.
    assert sent[2:] == [(300, signal.SIGKILL)]
    assert end_foreground({"shell_pid": 100, "foreground_processes": []}) == []


@pytest.mark.skipif(sys.platform == "win32", reason="reads ps")
def test_ps_is_read_on_this_machine():
    import os

    me = usage.read_ps().get(os.getpid())
    assert me is not None
    assert me.rss_kb > 0
    assert usage.total_ram_mb()
