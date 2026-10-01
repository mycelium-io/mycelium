# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: their state, the problems, restarting them, and herdr's integrations."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from mycelium import machine
from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping
from mycelium.runner.daemon import State, Tracked


class FakeHerdr:
    """herdr's CLI as the bridge calls it: agents, panes and workspaces, and what it was told."""

    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.panes: list[dict] = []
        self.workspaces: list[dict] = []
        self.server = self.client = "0.9.3"
        #: Each integration herdr has, and whether it's current.
        self.integrations: dict[str, bool] = {"claude": False, "codex": False, "pi": False}
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
            return self._text(args, f"status: running\nversion: {self.server}\n")
        elif args == ["--version"]:
            return self._text(args, f"herdr {self.client}\n")
        elif head == "integration status":
            lines = [
                f"{name}: {'current (v1)' if ok else 'not installed'} (/h/{name})"
                for name, ok in self.integrations.items()
            ]
            return self._text(args, "\n".join(lines) + "\n")
        elif head == "integration install":
            self.integrations[args[2]] = True
            return self._text(args, "")
        elif head == "pane split":
            workspace = args[2].split(":")[0]
            splits = len(self.of("pane split"))
            pane = f"{workspace}:pNEW{'' if splits == 1 else splits}"
            self.panes.append({"pane_id": pane, "workspace_id": workspace})
            out = {"result": {"pane": {"pane_id": pane}}}
        elif head == "workspace create":
            self.panes.append({"pane_id": "w7:p1", "workspace_id": "w7"})
            out = {
                "result": {"workspace": {"workspace_id": "w7"}, "root_pane": {"pane_id": "w7:p1"}}
            }
        elif head in ("pane run", "pane send-keys", "agent rename"):
            return self._text(args, "")
        elif head == "agent start":
            out = {"result": {"agent": {"pane_id": args[args.index("--pane") + 1]}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(out), "")

    @staticmethod
    def _text(args: list[str], text: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 0, text, "")

    def of(self, head: str) -> list[list[str]]:
        return [c for c in self.calls if " ".join(c[:2]) == head]


@pytest.fixture
def herdr(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> FakeHerdr:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("mycelium.commands.swarm.START_RETRY_S", 0)
    # The agent CLIs on PATH here: Claude Code and Codex, not Pi.
    monkeypatch.setattr(machine, "_installed_kinds", lambda: {"claude", "codex"})
    return FakeHerdr()


def _bridge(fake: FakeHerdr) -> HerdrBridge:
    return HerdrBridge(runner=fake)


def _config() -> MyceliumConfig:
    config = MyceliumConfig()
    config.server.api_url = "http://hub:8000"
    return config


def _report(bridge: HerdrBridge, state: State | None = None) -> machine.Report:
    return machine.report(_config(), bridge=bridge, state=state or State(), machine="mac")


def _setup(fake: FakeHerdr) -> HerdrBridge:
    """Three agents in workspace w2, bound to checkout: one working, one whose
    pane came back empty after a restart, one whose pane is gone with no folder."""
    bridge = _bridge(fake)
    reg = bridge.registry
    reg.bind("w2", "checkout")
    for handle, pane in (("builder", "w2:p1"), ("reviewer", "w2:p2")):
        reg.set(
            HerdrPaneMapping(
                room="checkout",
                handle=handle,
                pane=pane,
                kind="claude",
                managed=True,
                cwd="/work/shop",
            )
        )
    reg.set(HerdrPaneMapping(room="checkout", handle="old", pane="w2:p9", kind="claude"))
    fake.agents = [
        {"pane_id": "w2:p1", "workspace_id": "w2", "agent_status": "working", "agent": "claude"}
    ]
    fake.panes = [
        {"pane_id": "w2:p1", "workspace_id": "w2"},
        {"pane_id": "w2:p2", "workspace_id": "w2"},
    ]
    fake.workspaces = [{"workspace_id": "w2", "label": "tome-dev"}]
    return bridge


# ── the report ───────────────────────────────────────────────────────────────


def test_each_agent_says_whether_it_runs_stopped_with_its_pane_or_lost_its_pane(herdr: FakeHerdr):
    r = _report(_setup(herdr))

    by = {a.handle: a for a in r.agents}
    assert (by["builder"].state, by["reviewer"].state, by["old"].state) == (
        "working",
        "stopped",
        "gone",
    )
    # The stopped one can be started again; the gone one has no folder to start in.
    assert by["reviewer"].restartable and not by["builder"].restartable
    assert not by["old"].restartable
    tome = next(w for w in r.workspaces if w.id == "w2")
    assert (tome.label, tome.room) == ("tome-dev", "checkout")
    assert {a.handle for a in tome.agents} == {"builder", "reviewer"}
    gone = next(w for w in r.workspaces if w.id == machine.NOWHERE)
    assert [a.handle for a in gone.agents] == ["old"]


def test_the_problems_each_come_with_the_command_that_fixes_them(herdr: FakeHerdr):
    r = _report(_setup(herdr))

    fixes = {p.kind: p.fix for p in r.problems}
    assert fixes["stopped"] == "mycelium machine restart --all"
    assert fixes["lost"] == "mycelium machine unbind --gone"
    assert fixes["unsynced"] == "mycelium machine sync w2 on"
    assert fixes["no_restore"] == "mycelium machine integrations --install"
    assert next(p for p in r.problems if p.kind == "stopped").handles == ["reviewer"]


def test_with_herdrs_integration_current_an_agent_comes_back_on_its_own(herdr: FakeHerdr):
    herdr.integrations["claude"] = True
    r = _report(_setup(herdr))
    by = {a.handle: a.restores for a in r.agents}
    # A gone pane has nothing for herdr to restore, so it isn't said either way.
    assert by == {"builder": True, "reviewer": True, "old": None}
    assert r.missing_integrations == []
    assert "no_restore" not in {p.kind for p in r.problems}


def test_without_it_the_report_names_the_integration_missing(herdr: FakeHerdr):
    r = _report(_setup(herdr))
    assert r.missing_integrations == ["claude"]
    problem = next(p for p in r.problems if p.kind == "no_restore")
    assert "herdr's integration for claude" in problem.text
    assert problem.handles == ["builder", "reviewer"]  # not the gone one


def test_choosing_the_runner_to_sync_a_workspace_clears_the_unsynced_problem(herdr: FakeHerdr):
    bridge = _setup(herdr)
    machine.set_runner_sync("w2", True)
    r = _report(bridge)
    assert "unsynced" not in {p.kind for p in r.problems}
    assert next(w for w in r.workspaces if w.id == "w2").runner_keeps

    machine.set_runner_sync("w2", False)
    assert "unsynced" in {p.kind for p in _report(bridge).problems}


# ── herdr's version ──────────────────────────────────────────────────────────


def test_a_herdr_server_older_than_mycelium_needs_says_to_restart_it(herdr: FakeHerdr):
    herdr.server, herdr.client = "0.8.0", "0.9.3"
    update = next(p for p in _report(_setup(herdr)).problems if p.kind == "herdr_update")
    assert "herdr's server is 0.8.0, out of date: Mycelium needs 0.9.3 or newer" in update.text
    assert update.fix == "herdr server stop"


def test_a_herdr_client_older_than_mycelium_needs_says_to_update_it(herdr: FakeHerdr):
    herdr.server = herdr.client = "0.9.1"
    update = next(p for p in _report(_setup(herdr)).problems if p.kind == "herdr_update")
    assert update.text.startswith("herdr 0.9.1 is out of date. Mycelium needs 0.9.3 or newer.")
    assert update.fix == "herdr update"


def test_a_current_herdr_is_no_problem(herdr: FakeHerdr):
    assert "herdr_update" not in {p.kind for p in _report(_setup(herdr)).problems}


# ── restarting ───────────────────────────────────────────────────────────────


def test_restarting_into_the_open_pane_sets_who_it_is_and_tells_it_to_catch_up(herdr: FakeHerdr):
    bridge = _setup(herdr)

    pane = machine.restart(_config(), _report(bridge).find("reviewer"), bridge=bridge)

    assert pane == "w2:p2"
    run = herdr.of("pane run")[0]
    assert run[2] == "w2:p2"
    assert "cd /work/shop" in run[3]
    assert "MYCELIUM_AGENT_HANDLE=reviewer" in run[3] and "MYCELIUM_ROOM_ID=checkout" in run[3]
    start = herdr.of("agent start")[0]
    assert start[2] == "reviewer"
    # No session of its own: only what it needs to run unattended.
    assert start[start.index("--") + 1 :] == ["--allowedTools", "Bash(mycelium:*)"]
    prompt = herdr.of("agent prompt")[0][3]
    assert "You were restarted" in prompt
    assert "mycelium await --room checkout --handle reviewer" in prompt
    kept = bridge.registry.get("checkout", "reviewer")
    assert kept is not None and (kept.pane, kept.cwd, kept.managed) == ("w2:p2", "/work/shop", True)


def test_restarting_an_agent_whose_pane_is_gone_opens_one_beside_its_workspace(herdr: FakeHerdr):
    bridge = _setup(herdr)
    bridge.registry.set(
        HerdrPaneMapping(room="checkout", handle="old", pane="w2:p9", kind="claude", cwd="/w")
    )
    # The runner's record still says which workspace it was in.
    state = State(
        agents={
            "checkout/old": Tracked(
                handle="old",
                room="checkout",
                framework="claude",
                pane="w2:p9",
                cwd="/w",
                started_at="",
                workspace="w2",
            )
        }
    )
    old = _report(bridge, state).find("old")
    assert old.state == "gone" and old.restartable

    assert machine.restart(_config(), old, bridge=bridge) == "w2:pNEW"
    assert herdr.of("pane split")[0][2] == "w2:p2"  # beside a pane still in w2


def test_restarting_gone_agents_of_one_room_opens_one_workspace_for_them_all(herdr: FakeHerdr):
    bridge = _bridge(herdr)
    for handle in ("a", "b"):
        bridge.registry.set(
            HerdrPaneMapping(
                room="checkout", handle=handle, pane=f"w9:{handle}", kind="claude", cwd="/w"
            )
        )
    r = _report(bridge)
    assert {a.state for a in r.agents} == {"gone"}

    first = machine.restart(_config(), r.find("a"), bridge=bridge)
    second = machine.restart(_config(), r.find("b"), bridge=bridge)

    assert len(herdr.of("workspace create")) == 1
    assert (first, second[:3]) == ("w7:p1", "w7:")
    assert bridge.registry.bindings() == {"w7": "checkout"}


def test_a_running_agent_isnt_restarted(herdr: FakeHerdr):
    bridge = _setup(herdr)
    with pytest.raises(machine.MachineError, match="running"):
        machine.restart(_config(), _report(bridge).find("builder"), bridge=bridge)


def test_any_agent_cli_restarts_the_same_way(herdr: FakeHerdr):
    bridge = _bridge(herdr)
    bridge.registry.set(
        HerdrPaneMapping(room="r", handle="c", pane="w2:p1", kind="codex", cwd="/work")
    )
    herdr.panes = [{"pane_id": "w2:p1", "workspace_id": "w2"}]
    c = _report(bridge).find("c")
    assert c.state == "stopped" and c.restartable

    machine.restart(_config(), c, bridge=bridge)
    start = herdr.of("agent start")[0]
    assert start[2:5] == ["c", "--kind", "codex"]
    assert "--" not in start  # nothing added for a CLI Mycelium adds nothing to


# ── herdr's integrations ─────────────────────────────────────────────────────


def test_integrations_are_named_only_for_agent_clis_installed_here(herdr: FakeHerdr):
    state = machine.integrations(bridge=_bridge(herdr))
    # Pi isn't on PATH here, so its integration isn't anything to install.
    assert state.current == {"claude": False, "codex": False}
    assert state.missing == ["claude", "codex"]
    assert (state.answer, state.out_of_date) == (None, False)


def test_installing_them_installs_each_missing_one_and_remembers_the_yes(herdr: FakeHerdr):
    bridge = _bridge(herdr)
    herdr.integrations["codex"] = True

    assert machine.install_integrations(bridge=bridge) == ["claude"]
    assert [c[2] for c in herdr.of("integration install")] == ["claude"]
    state = machine.integrations(bridge=bridge)
    assert (state.missing, state.answer) == ([], "yes")


def test_declining_is_remembered_and_installs_nothing(herdr: FakeHerdr):
    machine.decline_integrations()
    assert machine.integrations(bridge=_bridge(herdr)).answer == "no"
    assert herdr.of("integration install") == []


def test_an_out_of_date_herdr_shows_in_the_integrations_state(herdr: FakeHerdr):
    herdr.server = "0.8.0"
    state = machine.integrations(bridge=_bridge(herdr))
    assert state.out_of_date and state.wire()["minimum"] == "0.9.3"


# ── sync heartbeats ──────────────────────────────────────────────────────────


def test_a_sync_heartbeat_says_who_syncs_until_it_goes_stale(isolated_home: Path):
    machine.mark_syncing(["w2"], "terminal")
    assert machine.syncing() == {"w2": "terminal"}

    beat = machine._heartbeat_dir() / "w2.json"
    stale = json.loads(beat.read_text()) | {"at": time.time() - machine.FRESH_S - 5}
    beat.write_text(json.dumps(stale))
    assert machine.syncing() == {}


def test_a_heartbeat_names_its_workspace_whatever_its_file_is_called(isolated_home: Path):
    machine.mark_syncing(["w2:main", "w2.main"], "runner")
    assert machine.syncing() == {"w2:main": "runner", "w2.main": "runner"}
