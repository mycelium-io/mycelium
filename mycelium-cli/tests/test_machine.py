# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: their state, the problems, and resuming after a restart."""

from __future__ import annotations

import dataclasses
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

#: Claude Code session ids, which are UUIDs.
S_BUILDER = "0b1d5c3e-4a6f-4c2d-9e8b-1f2a3b4c5d6e"
S_REVIEWER = "9b07c2d4-1e5f-4a8b-b3c6-7d9e0f1a44c0"
S_OLD = "5d1c2f0e-aaaa-4bbb-8ccc-0123456789ab"
S_OTHER = "7e6d5c4b-3a29-4180-9f7e-6d5c4b3a2918"


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
            workspace = args[2].split(":")[0]
            splits = sum(1 for c in self.calls if " ".join(c[:2]) == "pane split")
            pane = f"{workspace}:pNEW{'' if splits == 1 else splits}"
            self.panes.append({"pane_id": pane, "workspace_id": workspace})
            out = {"result": {"pane": {"pane_id": pane}}}
        elif head == "workspace create":
            self.panes.append({"pane_id": "w7:p1", "workspace_id": "w7"})
            out = {
                "result": {"workspace": {"workspace_id": "w7"}, "root_pane": {"pane_id": "w7:p1"}}
            }
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
            session=S_BUILDER,
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
            session=S_REVIEWER,
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
    assert start[start.index("--") + 1 : start.index("--") + 3] == ["--resume", S_REVIEWER]
    kept = bridge.registry.get("checkout", "reviewer")
    assert kept is not None and (kept.pane, kept.session, kept.managed) == (
        "w2:p2",
        S_REVIEWER,
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
            session=S_OLD,
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
    assert kept is not None and kept.pane == "w2:pNEW" and kept.session == S_OLD


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
    (project / f"{S_OLD}.jsonl").write_text("{}\n")
    (project / f"{S_REVIEWER}.jsonl").write_text("{}\n")
    # A file that isn't named for a session is never offered, however new.
    (project / "--settings=x.jsonl").write_text("{}\n")
    past = time.time() - 3600
    os.utime(project / f"{S_OLD}.jsonl", (past, past))

    agent = machine.Agent(
        handle="a",
        room="r",
        host="herdr",
        ref="w2:p1",
        state="stopped",
        folder=str(folder),
        kind="claude",
    )
    found = machine.find_session(agent)
    assert found is not None and found.id == S_REVIEWER
    # A kind Mycelium knows nothing about has nowhere to look.
    assert machine.find_session(dataclasses.replace(agent, kind="codex")) is None


def test_resuming_gone_agents_of_one_room_opens_one_workspace_for_them_all(herdr: FakeHerdr):
    bridge = _bridge(herdr)
    for handle, session in (("a", S_OLD), ("b", S_OTHER)):
        bridge.registry.set(
            HerdrPaneMapping(
                room="checkout",
                handle=handle,
                pane=f"w9:{handle}",
                kind="claude",
                session=session,
                cwd="/work/shop",
            )
        )
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    assert {a.state for a in r.agents} == {"gone"}

    first = machine.resume(_config(), r.find("a"), bridge=bridge)
    second = machine.resume(_config(), r.find("b"), bridge=bridge)

    assert len(herdr.of("workspace create")) == 1
    assert first == "w7:p1"
    assert second.startswith("w7:")
    assert bridge.registry.bindings() == {"w7": "checkout"}


def test_a_session_that_isnt_one_is_never_saved_or_passed_on(herdr: FakeHerdr):
    bridge = _setup(herdr)
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    for bad in ("--settings=x.json", "a;b", "$(x)", "s-1"):
        with pytest.raises(machine.MachineError, match="isn't a Claude Code session id"):
            machine.save_session(r.find("reviewer"), bad, bridge=bridge)
    kept = bridge.registry.get("checkout", "reviewer")
    assert kept is not None and kept.session == S_REVIEWER

    # One written into the file by hand is dropped on read, so it can't be resumed.
    data = json.loads(bridge.registry.path.read_text())
    data["checkout/reviewer"]["session"] = "--settings=x.json"
    bridge.registry.path.write_text(json.dumps(data))
    reviewer = machine.report(_config(), bridge=bridge, state=State(), machine="mac").find(
        "reviewer"
    )
    assert reviewer.session is None and not reviewer.resumable


def test_the_resume_command_shown_is_the_one_run(herdr: FakeHerdr):
    bridge = _setup(herdr)
    reviewer = machine.report(_config(), bridge=bridge, state=State(), machine="mac").find(
        "reviewer"
    )
    assert machine.resume_command(reviewer).startswith(
        f"cd /work/shop && claude --resume {S_REVIEWER}"
    )


def test_a_kind_mycelium_knows_nothing_of_is_never_resumable(herdr: FakeHerdr):
    bridge = _bridge(herdr)
    bridge.registry.set(
        HerdrPaneMapping(
            room="r", handle="c", pane="w2:p1", kind="codex", session=S_OLD, cwd="/work"
        )
    )
    herdr.panes = [{"pane_id": "w2:p1", "workspace_id": "w2"}]
    r = machine.report(_config(), bridge=bridge, state=State(), machine="mac")
    c = r.find("c")
    assert c.state == "stopped" and not c.resumable and not c.resumes
    # Its problem says to start it again, never to go looking for a session.
    (problem,) = [p for p in r.problems if "c" in p.handles]
    assert "can't resume its agent CLI" in problem.text
    assert problem.fix is None
    wired = r.wire()["workspaces"][0]["agents"][0]
    assert (wired["resumes"], wired["resumable"], wired["resume_command"]) == (False, False, None)
    with pytest.raises(machine.MachineError, match="can't resume"):
        machine.resume(_config(), c, bridge=bridge)


def test_a_heartbeat_names_its_workspace_whatever_its_file_is_called(isolated_home: Path):
    machine.mark_syncing(["w2:main", "w2.main"], "runner")
    assert machine.syncing() == {"w2:main": "runner", "w2.main": "runner"}
