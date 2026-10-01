# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: their state, the problems, and resuming after a restart."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from mycelium import machine
from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping
from mycelium.runner.daemon import State


class FakeHerdr:
    """herdr's CLI as the bridge calls it: agents, panes and workspaces, and what it was told."""

    def __init__(
        self,
        *,
        agents: list[dict] | None = None,
        panes: list[dict] | None = None,
        workspaces: list[dict] | None = None,
        server: str = "0.9.1",
        client: str = "0.9.1",
    ) -> None:
        self.agents = agents or []
        self.panes = panes or []
        self.workspaces = workspaces or []
        self.server, self.client = server, client
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        head = " ".join(args[:2])
        out: object = {}
        if head == "agent list":
            out = {"result": {"agents": self.agents}}
        elif head == "pane list":
            out = {"result": {"panes": self.panes}}
        elif head == "workspace list":
            out = {"result": {"workspaces": self.workspaces}}
        elif head == "tab list":
            out = {"result": {"tabs": []}}
        elif head == "status server":
            return subprocess.CompletedProcess(
                args, 0, f"status: running\nversion: {self.server}\n", ""
            )
        elif args == ["--version"]:
            return subprocess.CompletedProcess(args, 0, f"herdr {self.client}\n", "")
        elif head == "pane split":
            out = {"result": {"pane": {"pane_id": "w2:pNEW"}}}
        elif head in ("pane run", "pane send-keys", "agent rename"):
            return subprocess.CompletedProcess(args, 0, "", "")
        elif head == "agent start":
            out = {"result": {"agent": {"pane_id": args[args.index("--pane") + 1]}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(out), "")

    def of(self, head: str) -> list[list[str]]:
        return [c for c in self.calls if " ".join(c[:2]) == head]


@pytest.fixture
def herdr(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> FakeHerdr:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("mycelium.commands.swarm.START_RETRY_S", 0)
    return FakeHerdr()


def _bridge(fake: FakeHerdr) -> HerdrBridge:
    return HerdrBridge(runner=fake)


def _config() -> MyceliumConfig:
    config = MyceliumConfig()
    config.server.api_url = "http://hub:8000"
    return config


def _setup(fake: FakeHerdr) -> HerdrBridge:
    """Three agents in workspace w2, bound to checkout: one working, one whose
    pane came back empty after a restart, one whose pane is gone."""
    bridge = _bridge(fake)
    reg = bridge.registry
    reg.bind("w2", "checkout")
    reg.set(
        HerdrPaneMapping(
            room="checkout",
            handle="builder",
            pane="w2:p1",
            kind="claude",
            managed=True,
            session="s-builder",
            cwd="/work/shop",
        )
    )
    reg.set(
        HerdrPaneMapping(
            room="checkout",
            handle="reviewer",
            pane="w2:p2",
            kind="claude",
            managed=True,
            session="s-reviewer",
            cwd="/work/shop",
        )
    )
    reg.set(HerdrPaneMapping(room="checkout", handle="old", pane="w2:p9", kind="claude"))
    fake.agents = [
        {"pane_id": "w2:p1", "workspace_id": "w2", "agent_status": "working", "agent": "claude"}
    ]
    fake.panes = [
        {"pane_id": "w2:p1", "workspace_id": "w2", "cwd": "/work/shop"},
        {"pane_id": "w2:p2", "workspace_id": "w2", "cwd": "/work/shop"},
    ]
    fake.workspaces = [{"workspace_id": "w2", "label": "tome-dev"}]
    return bridge


def test_each_agent_says_whether_it_runs_stopped_with_its_pane_or_lost_its_pane(herdr: FakeHerdr):
    bridge = _setup(herdr)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")

    by = {a.handle: a for a in r.agents}
    assert by["builder"].state == "working"
    assert by["reviewer"].state == "stopped"
    assert by["old"].state == "gone"
    assert by["reviewer"].resumable and not by["builder"].resumable and not by["old"].resumable
    tome = next(w for w in r.workspaces if w.id == "w2")
    assert (tome.label, tome.room) == ("tome-dev", "checkout")
    assert {a.handle for a in tome.agents} == {"builder", "reviewer"}
    gone = next(w for w in r.workspaces if w.id == machine.NOWHERE)
    assert [a.handle for a in gone.agents] == ["old"]


def test_the_problems_each_come_with_the_command_that_fixes_them(herdr: FakeHerdr):
    bridge = _setup(herdr)
    herdr.server, herdr.client = "0.8.0", "0.9.1"
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")

    fixes = {p.kind: p.fix for p in r.problems}
    assert fixes["stopped"] == "mycelium machine resume --all"
    assert fixes["unresumable"] == "mycelium machine unbind --gone"
    assert fixes["unsynced"] == "mycelium machine sync w2 on"
    assert (fixes["herdr_update"] or "").startswith("herdr server stop")
    stopped = next(p for p in r.problems if p.kind == "stopped")
    assert stopped.handles == ["reviewer"]


def test_choosing_the_runner_to_sync_a_workspace_clears_the_unsynced_problem(herdr: FakeHerdr):
    bridge = _setup(herdr)
    machine.set_runner_sync("w2", True)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    assert "unsynced" not in {p.kind for p in r.problems}
    assert next(w for w in r.workspaces if w.id == "w2").runner_keeps

    machine.set_runner_sync("w2", False)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    assert "unsynced" in {p.kind for p in r.problems}


def test_resuming_into_the_open_pane_sets_who_it_is_then_picks_up_its_session(herdr: FakeHerdr):
    bridge = _setup(herdr)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")

    pane = machine.resume(_config(), r.find("reviewer"), bridge=bridge)

    assert pane == "w2:p2"
    run = herdr.of("pane run")[0]
    assert run[2] == "w2:p2"
    assert "cd /work/shop" in run[3]
    assert "MYCELIUM_AGENT_HANDLE=reviewer" in run[3] and "MYCELIUM_ROOM_ID=checkout" in run[3]
    start = herdr.of("agent start")[0]
    assert start[2] == "reviewer"
    assert start[start.index("--") + 1 : start.index("--") + 3] == ["--resume", "s-reviewer"]
    kept = bridge.registry.get("checkout", "reviewer")
    assert kept is not None and (kept.pane, kept.session, kept.managed) == (
        "w2:p2",
        "s-reviewer",
        True,
    )


def test_resuming_an_agent_whose_pane_is_gone_opens_one_beside_its_workspace(herdr: FakeHerdr):
    bridge = _setup(herdr)
    bridge.registry.set(
        HerdrPaneMapping(
            room="checkout",
            handle="old",
            pane="w2:p9",
            kind="claude",
            session="s-old",
            cwd="/work/shop",
        )
    )
    # herdr still says which workspace it was in through the runner's record.
    from mycelium.runner.daemon import Tracked

    state = State(
        agents={
            "checkout/old": Tracked(
                handle="old",
                room="checkout",
                framework="claude",
                pane="w2:p9",
                cwd="/work/shop",
                started_at="",
                workspace="w2",
            )
        }
    )
    r = machine.report(_config(), bridge=bridge, state=state, machine="mac")
    old = r.find("old")
    assert old.state == "gone" and old.resumable

    pane = machine.resume(_config(), old, bridge=bridge)

    assert pane == "w2:pNEW"
    assert herdr.of("pane split")[0][2] == "w2:p2"  # beside a pane still in w2
    kept = bridge.registry.get("checkout", "old")
    assert kept is not None and kept.pane == "w2:pNEW" and kept.session == "s-old"


def test_an_agent_with_no_saved_session_isnt_resumed(herdr: FakeHerdr):
    bridge = _setup(herdr)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    with pytest.raises(machine.MachineError, match="running"):
        machine.resume(_config(), r.find("builder"), bridge=bridge)


def test_a_sync_heartbeat_says_who_syncs_until_it_goes_stale(isolated_home: Path):
    machine.mark_syncing(["w2"], "terminal")
    assert machine.syncing() == {"w2": "terminal"}

    beat = machine._heartbeat_dir() / "w2.json"
    stale = json.loads(beat.read_text()) | {"at": time.time() - machine.FRESH_S - 5}
    beat.write_text(json.dumps(stale))
    assert machine.syncing() == {}


def test_finding_a_session_reads_the_newest_conversation_in_the_agents_folder(isolated_home: Path):
    folder = isolated_home / "work" / "shop"
    folder.mkdir(parents=True)
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in str(folder.resolve()))
    project = isolated_home / ".claude" / "projects" / slug
    project.mkdir(parents=True)
    (project / "older.jsonl").write_text("{}\n")
    (project / "newer.jsonl").write_text("{}\n")
    past = time.time() - 3600
    os.utime(project / "older.jsonl", (past, past))

    agent = machine.Agent(
        handle="a", room="r", host="herdr", ref="w2:p1", state="stopped", folder=str(folder)
    )
    found = machine.find_session(agent)
    assert found is not None and found.id == "newer"
