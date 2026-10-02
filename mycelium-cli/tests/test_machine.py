# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: their state, what's wrong, restarting them, and herdr's integrations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mycelium import machine
from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping


class FakeHerdr:
    """herdr's CLI as the bridge calls it: agents, panes and workspaces, and what it was told."""

    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.panes: list[dict] = []
        self.server = self.client = "0.9.3"
        #: Each integration herdr has, and whether it's current.
        self.integrations: dict[str, bool] = {"claude": False, "codex": False, "pi": False}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        head = " ".join(args[:2])
        if head == "status server":
            return self._text(args, f"status: running\nversion: {self.server}\n")
        if args == ["--version"]:
            return self._text(args, f"herdr {self.client}\n")
        if head == "integration status":
            return self._text(
                args,
                "".join(
                    f"{name}: {'current (v1)' if ok else 'not installed'} (/h/{name})\n"
                    for name, ok in self.integrations.items()
                ),
            )
        if head == "integration install":
            self.integrations[args[2]] = True
            return self._text(args, "")
        if head in ("pane run", "agent rename"):
            return self._text(args, "")
        result: object = {}
        if head == "agent list":
            result = {"agents": self.agents}
        elif head == "pane list":
            result = {"panes": self.panes}
        elif head == "workspace list":
            result = {"workspaces": [{"workspace_id": "w2", "label": "tome-dev"}]}
        elif head == "pane split":
            workspace = args[2].split(":")[0]
            pane = f"{workspace}:pNEW{len(self.of('pane split'))}"
            self.panes.append({"pane_id": pane, "workspace_id": workspace})
            result = {"pane": {"pane_id": pane}}
        elif head == "workspace create":
            self.panes.append({"pane_id": "w7:p1", "workspace_id": "w7"})
            result = {"workspace": {"workspace_id": "w7"}, "root_pane": {"pane_id": "w7:p1"}}
        elif head == "agent start":
            result = {"agent": {"pane_id": args[args.index("--pane") + 1]}}
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": result}), "")

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


def _config() -> MyceliumConfig:
    config = MyceliumConfig()
    config.server.api_url = "http://hub:8000"
    return config


def _report(bridge: HerdrBridge, *, runner: bool = True) -> machine.Report:
    return machine.report(bridge=bridge, machine="mac", runner=runner)


def _setup(fake: FakeHerdr) -> HerdrBridge:
    """Workspace w2, bound to checkout: @builder working, @reviewer's pane open but
    empty (herdr restarted), and @old's pane gone with no folder on record."""
    bridge = HerdrBridge(runner=fake)
    reg = bridge.registry
    reg.bind("w2", "checkout")
    for handle, pane in (("builder", "w2:p1"), ("reviewer", "w2:p2")):
        reg.set(
            HerdrPaneMapping(
                room="checkout", handle=handle, pane=pane, kind="claude", managed=True, cwd="/shop"
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
    return bridge


# ── the report ───────────────────────────────────────────────────────────────


def test_each_agent_says_whether_it_runs_stopped_with_its_pane_or_lost_its_pane(herdr: FakeHerdr):
    r = _report(_setup(herdr))

    by = {a.handle: a for a in r.agents}
    assert [by[h].state for h in ("builder", "reviewer", "old")] == ["working", "stopped", "gone"]
    assert by["reviewer"].restartable
    assert not by["builder"].restartable  # running
    assert not by["old"].restartable  # nothing says which folder
    tome = next(w for w in r.workspaces if w.id == "w2")
    assert (tome.label, tome.room, [a.handle for a in tome.agents]) == (
        "tome-dev",
        "checkout",
        ["builder", "reviewer"],
    )
    assert [a.handle for a in r.workspaces[-1].agents] == ["old"]  # "Panes that are gone"


def test_the_problems_each_come_with_the_command_that_fixes_them(herdr: FakeHerdr):
    herdr.server = "0.8.0"
    r = _report(_setup(herdr), runner=False)

    fixes = {p.kind: p.fix for p in r.problems}
    assert fixes == {
        "stopped": "mycelium machine restart --all",
        "lost": "mycelium machine unbind --gone",
        "runner_down": "mycelium runner --detach",
        "no_restore": "mycelium machine integrations --install",
        "herdr_update": "herdr server stop",
    }
    by = {p.kind: p for p in r.problems}
    assert by["stopped"].handles == ["reviewer"]
    assert by["runner_down"].handles == ["builder"]  # the one running: it won't hear mentions
    assert by["no_restore"].handles == ["builder", "reviewer"]  # not the gone one
    assert "Mycelium needs 0.9.3 or newer" in by["herdr_update"].text


def test_a_healthy_machine_has_nothing_to_fix(herdr: FakeHerdr):
    herdr.integrations["claude"] = True
    bridge = _setup(herdr)
    bridge.registry.remove("checkout", "old")
    herdr.agents.append(
        {"pane_id": "w2:p2", "workspace_id": "w2", "agent_status": "idle", "agent": "claude"}
    )
    r = _report(bridge)
    assert r.problems == []
    assert {a.restores for a in r.agents} == {True}


def test_an_old_herdr_command_is_updated_not_restarted(herdr: FakeHerdr):
    herdr.server = herdr.client = "0.9.1"
    update = next(p for p in _report(_setup(herdr)).problems if p.kind == "herdr_update")
    assert update.text.startswith("herdr 0.9.1 is out of date. Mycelium needs 0.9.3 or newer.")
    assert update.fix == "herdr update"


# ── restarting ───────────────────────────────────────────────────────────────


def test_restarting_into_the_open_pane_sets_who_it_is_and_tells_it_to_catch_up(herdr: FakeHerdr):
    bridge = _setup(herdr)

    pane = machine.restart(_config(), _report(bridge).find("reviewer"), bridge=bridge)

    assert pane == "w2:p2"
    command = herdr.of("pane run")[0][3]
    assert command.startswith("cd /shop && export MYCELIUM_API_URL=http://hub:8000")
    assert "MYCELIUM_AGENT_HANDLE=reviewer" in command and "MYCELIUM_ROOM_ID=checkout" in command
    start = herdr.of("agent start")[0]
    assert start[2:5] == ["reviewer", "--kind", "claude"]
    prompt = herdr.of("agent prompt")[0][3]
    assert "You were restarted" in prompt
    assert "mycelium await --room checkout --handle reviewer" in prompt
    kept = bridge.registry.get("checkout", "reviewer")
    assert kept is not None and (kept.pane, kept.cwd, kept.managed) == ("w2:p2", "/shop", True)


def test_restarting_binds_its_workspace_again_so_the_runner_syncs_it(herdr: FakeHerdr):
    # The runner lets go of a workspace once none of its agents is live, which
    # is just what a herdr restart leaves behind.
    bridge = _setup(herdr)
    bridge.registry.unbind("w2")
    reviewer = _report(bridge).find("reviewer")
    machine.restart(_config(), reviewer, bridge=bridge)
    assert bridge.registry.bindings() == {"w2": "checkout"}


def test_restarting_gone_agents_of_one_room_opens_one_workspace_for_them_all(herdr: FakeHerdr):
    bridge = HerdrBridge(runner=herdr)
    for handle in ("a", "b"):
        bridge.registry.set(
            HerdrPaneMapping(
                room="checkout", handle=handle, pane=f"w9:{handle}", kind="codex", cwd="/w"
            )
        )
    r = _report(bridge)
    assert {a.state for a in r.agents} == {"gone"} and all(a.restartable for a in r.agents)

    machine.restart(_config(), r.find("a"), bridge=bridge)
    second = machine.restart(_config(), r.find("b"), bridge=bridge)

    assert len(herdr.of("workspace create")) == 1
    assert second.startswith("w7:")  # beside the first, in the workspace it opened
    assert bridge.registry.bindings() == {"w7": "checkout"}
    assert herdr.of("agent start")[1][2:5] == ["b", "--kind", "codex"]


def test_a_running_agent_isnt_restarted(herdr: FakeHerdr):
    bridge = _setup(herdr)
    with pytest.raises(machine.MachineError, match="running"):
        machine.restart(_config(), _report(bridge).find("builder"), bridge=bridge)


# ── rename and unbind ────────────────────────────────────────────────────────


def test_renaming_changes_herdrs_name_and_unbinding_forgets_the_pane(herdr: FakeHerdr):
    bridge = _setup(herdr)
    r = _report(bridge)
    machine.rename(r.find("builder"), "Builder", bridge=bridge)
    assert herdr.of("agent rename")[0] == ["agent", "rename", "w2:p1", "Builder"]

    machine.unbind(r.find("old"), bridge=bridge)
    assert bridge.registry.get("checkout", "old") is None
    assert bridge.registry.get("checkout", "builder") is not None


# ── herdr's integrations ─────────────────────────────────────────────────────


def test_integrations_are_named_only_for_agent_clis_installed_here(herdr: FakeHerdr):
    state = machine.integrations(bridge=HerdrBridge(runner=herdr))
    assert state.current == {"claude": False, "codex": False}  # Pi isn't on PATH
    assert (state.missing, state.answer) == (["claude", "codex"], None)


def test_installing_them_installs_each_missing_one_and_remembers_the_yes(herdr: FakeHerdr):
    bridge = HerdrBridge(runner=herdr)
    herdr.integrations["codex"] = True

    assert machine.install_integrations(bridge=bridge) == ["claude"]
    state = machine.integrations(bridge=bridge)
    assert (state.missing, state.answer) == ([], "yes")


def test_declining_is_remembered_and_installs_nothing(herdr: FakeHerdr):
    machine.decline_integrations()
    assert machine.integrations(bridge=HerdrBridge(runner=herdr)).answer == "no"
    assert herdr.of("integration install") == []


def test_the_state_says_whether_the_server_or_the_command_is_out_of_date(herdr: FakeHerdr):
    herdr.server = "0.8.0"
    state = machine.integrations(bridge=HerdrBridge(runner=herdr))
    assert (state.server_out_of_date, state.client_out_of_date) == (True, False)
    assert state.wire()["minimum"] == "0.9.3"
