# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium runner``: this machine, dialed in, starting agents in herdr.

No hub and no herdr: the hub is an ``httpx.MockTransport`` and herdr a scripted
runner. These hold what the scan reports (herdr decides what is startable),
what a launch does in herdr and says to the agent, the folders a job may use,
a stop, a swarm the hub set up, and that every job is reported back.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from mycelium import machine
from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrRegistry, HerdrUnavailableError
from mycelium.integrations.herdr.bridge import CALL_TIMEOUT_S, call_timeout
from mycelium.runner import approvals, daemon, frameworks
from mycelium.runner.log import open_log
from tests.herdr_layout import HerdrLayout

HELP = """Start a supported interactive agent in an existing pane

Options:
      --kind <KIND>
          Supported agent kind and canonical executable

          [possible values: pi, claude, codex, opencode]
"""


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["herdr"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _ok(result: dict) -> str:
    return json.dumps({"id": "cli:test", "result": result})


class Herdr:
    """A herdr stand-in: workspaces, panes, agents that come up idle, and its help."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.live: dict[str, str] = {}
        #: Open panes, with an agent in them or not.
        self.panes: list[str] = []
        self._panes = 0
        self.fail_start = False
        self.layout = HerdrLayout(self._pane)

    def _pane(self, workspace: str = "w9") -> str:
        self._panes += 1
        self.panes.append(f"{workspace}:p{self._panes}")
        return self.panes[-1]

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        head = " ".join(args[:2])
        if args[:3] == ["agent", "start", "--help"]:
            return _proc(HELP)
        if head == "pane list":
            panes = [
                {"pane_id": p, "workspace_id": p.split(":")[0], "tab_id": self.layout.tab_of(p)}
                for p in self.panes
            ]
            return _proc(_ok({"panes": panes}))
        if (result := self.layout.answer(args)) is not None:
            return _proc(_ok(result))
        if head == "agent start":
            if self.fail_start:
                return _proc(stderr=json.dumps({"error": "agent never became ready"}), returncode=1)
            self.live[args[args.index("--pane") + 1]] = "idle"
            return _proc(_ok({}))
        if head == "agent prompt":
            return _proc(_ok({}))
        if head == "agent list":
            agents = [
                {"pane_id": p, "agent_status": s, "workspace_id": "w9", "agent": "claude"}
                for p, s in self.live.items()
            ]
            return _proc(_ok({"agents": agents}))
        if head == "pane run":
            return _proc("")
        if head == "agent get":
            status = self.live.get(args[2])
            return _proc(
                _ok({"agent": {"pane_id": args[2], "agent_status": status}} if status else {})
            )
        if head == "pane close":
            self.live.pop(args[2], None)
            if args[2] in self.panes:
                self.panes.remove(args[2])
            self.layout.panes.pop(args[2], None)
            return _proc(_ok({}))
        return _proc(stderr=_ok({}), returncode=2)

    def of(self, head: str) -> list[list[str]]:
        return [c for c in self.calls if " ".join(c[:2]) == head and "--help" not in c]


class Hub:
    """The hub's side of a runner: what it was sent, and a notes memory for one handle."""

    def __init__(self, notes_for: str | None = None) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.notes_for = notes_for

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path.endswith("/notes"):
            if self.notes_for and f"/agents/{self.notes_for}/" in request.url.path:
                return httpx.Response(200, json={"key": "n", "value": "Be terse."})
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json={})

    def of(self, method: str, suffix: str) -> list[Any]:
        return [b for m, p, b in self.seen if m == method and p.endswith(suffix)]


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Hub:
    hub = Hub()

    @contextmanager
    def client(_config: Any = None, **_kw: Any):
        with httpx.Client(base_url="http://hub", transport=httpx.MockTransport(hub.handler)) as c:
            yield c

    monkeypatch.setattr(daemon, "hub_client", client)
    monkeypatch.setattr("mycelium.commands.swarm.START_RETRY_S", 0)
    return hub


@pytest.fixture
def herdr(monkeypatch: pytest.MonkeyPatch) -> Herdr:
    real_which = frameworks.shutil.which

    def which(name: str) -> str | None:
        if name in ("herdr", "claude", "opencode", "aider"):
            return f"/usr/bin/{name}"
        return None if name != "git" else real_which(name)

    monkeypatch.setattr("shutil.which", which)
    monkeypatch.setattr(frameworks, "_version", lambda path: f"{Path(path).name} 1.0")
    return Herdr()


@pytest.fixture
def make_runner(tmp_path: Path, herdr: Herdr, isolated_home: Path):
    def make(
        roots: list[Path] | None = None, *, trust_hub: bool = True, on_request: Any = None
    ) -> daemon.Runner:
        config = MyceliumConfig()
        config.server.api_url = "http://hub:8000"
        bridge = HerdrBridge(runner=herdr, registry=HerdrRegistry(tmp_path / "herdr.json"))
        r = daemon.Runner(
            config,
            roots=roots or [tmp_path],
            bridge=bridge,
            rid="julias-mbp-ab12",
            state_path=tmp_path / "state.json",
            trust_hub=trust_hub,
            on_request=on_request,
            requests_base=tmp_path,
        )
        r.scan()
        return r

    return make


# ── the scan ──────────────────────────────────────────────────────────────────


def test_herdr_decides_what_can_be_started(herdr: Herdr):
    bridge = HerdrBridge(runner=herdr)
    assert bridge.supported_kinds() == {"pi", "claude", "codex", "opencode"}

    found = {f.id: f for f in frameworks.scan(bridge.supported_kinds())}
    assert found["claude"].installed and found["claude"].launchable
    assert found["claude"].version == "claude 1.0"
    # Installed, but herdr has no kind for it.
    assert found["aider"].installed and not found["aider"].launchable
    assert "no aider kind" in (found["aider"].note or "")
    # herdr could start it, but it is not here.
    assert not found["codex"].installed and not found["codex"].launchable
    # Installed ones lead the list.
    assert [f.installed for f in frameworks.scan(None)][:3] == [True, True, True]


def test_without_herdr_nothing_is_startable(herdr: Herdr):
    found = frameworks.scan(None)
    assert not any(f.launchable for f in found)
    assert next(f for f in found if f.id == "claude").note == "herdr isn't running here"


def test_the_hello_says_what_this_machine_has(make_runner):
    body = make_runner().hello_body()
    assert body["id"] == "julias-mbp-ab12"
    assert body["herdr"] is True
    assert [f["id"] for f in body["frameworks"] if f["launchable"]] == ["claude", "opencode"]
    assert body["agents"] == []


def test_the_owner_is_a_handle_a_person_reads(make_runner, monkeypatch: pytest.MonkeyPatch):
    r = make_runner()
    monkeypatch.setattr("getpass.getuser", lambda: "Julia.Valenti")
    monkeypatch.setattr(MyceliumConfig, "get_current_identity", lambda _self: "julia")
    assert r.owner() == "julia"
    monkeypatch.setattr(
        MyceliumConfig,
        "get_current_identity",
        lambda _self: "9907770b-3781-49ad-a242-fce7c28e5008",
    )
    assert r.owner() == "julia-valenti"


def test_a_runner_id_is_made_once_and_kept(tmp_path: Path):
    first = daemon.runner_id(tmp_path / "id")
    assert first == daemon.runner_id(tmp_path / "id")
    assert first.rsplit("-", 1)[1].isalnum()


# ── launch ────────────────────────────────────────────────────────────────────


def test_a_launch_opens_a_pane_starts_the_agent_and_tells_it_who_it_is(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path
):
    hub.notes_for = "scout"
    r = make_runner()
    (tmp_path / "api").mkdir()

    result = r.launch(
        {"room": "eng", "handle": "scout", "framework": "claude", "cwd": str(tmp_path / "api")}
    )

    assert result["pane"] == "w9:p1"
    create = herdr.of("workspace create")[0]
    assert create[create.index("--cwd") + 1] == str((tmp_path / "api").resolve())
    assert "MYCELIUM_AGENT_HANDLE=scout" in create
    assert "MYCELIUM_ROOM_ID=eng" in create
    assert "MYCELIUM_API_URL=http://hub:8000" in create
    start = herdr.of("agent start")[0]
    assert start[2:6] == ["scout", "--kind", "claude", "--pane"]
    assert start[-3:] == ["--", "--allowedTools", "Bash(mycelium:*)"]
    prompt = herdr.of("agent prompt")[0][3]
    assert "You are @scout" in prompt
    assert "mycelium memory get agents/scout/notes" in prompt
    # A closed pane stops the agent; it does not remove it from the room.
    mapping = r.bridge.registry.get("eng", "scout")
    assert mapping is not None
    assert (mapping.pane, mapping.managed) == ("w9:p1", False)
    assert r.bridge.registry.bindings() == {"w9": "eng"}
    assert r.hello_body()["agents"][0]["status"] == "running"
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "idle"


def test_the_next_agent_in_a_room_shares_its_workspace(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "one", "framework": "claude"})
    r.launch({"room": "eng", "handle": "two", "framework": "opencode"})
    assert len(herdr.of("workspace create")) == 1
    assert herdr.of("pane split")[0][2] == "w9:p1"
    assert herdr.of("agent start")[1][2:4] == ["two", "--kind"]
    assert "--allowedTools" not in herdr.of("agent start")[1]
    # Without notes it is pointed at the board instead.
    assert "mycelium board --room eng" in herdr.of("agent prompt")[1][3]


def test_launching_a_running_agent_again_opens_nothing(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    again = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert again == {"pane": "w9:p1", "already": True}
    assert len(herdr.of("agent start")) == 1


@pytest.mark.parametrize(
    ("spec", "said"),
    [
        ({"framework": "codex"}, "not installed"),
        ({"framework": "aider"}, "herdr can't start Aider"),
        ({"framework": "claude", "cwd": "/etc"}, "outside the folders"),
        ({"framework": "claude", "cwd": "{root}/../elsewhere"}, "outside the folders"),
        ({"framework": "claude", "cwd": "{root}/missing"}, "not a folder"),
    ],
)
def test_a_launch_this_machine_should_not_do_is_refused(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, spec: dict, said: str
):
    r = make_runner()
    if "cwd" in spec:
        spec = {**spec, "cwd": spec["cwd"].format(root=tmp_path)}
    with pytest.raises(daemon.JobError, match=said):
        r.launch({"room": "eng", "handle": "scout", **spec})
    assert herdr.of("agent start") == []


def test_an_agent_herdr_could_not_start_leaves_no_pane(make_runner, herdr: Herdr, hub: Hub):
    herdr.fail_start = True
    r = make_runner()
    with pytest.raises(daemon.JobError, match="could not start Claude Code"):
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert [c[2] for c in herdr.of("pane close")] == ["w9:p1"]
    assert r.hello_body()["agents"] == []


# ── after it is running ──────────────────────────────────────────────────────


def test_a_closed_pane_is_a_stopped_agent(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    herdr.live["w9:p1"] = "working"
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "working"

    herdr.live.clear()
    r.refresh()
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "stopped"
    assert r.bridge.registry.get("eng", "scout") is None


def test_stop_closes_the_pane_and_keeps_the_agent_listed(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    r.stop_agent({"room": "eng", "handle": "scout"})
    assert [c[2] for c in herdr.of("pane close")] == ["w9:p1"]
    assert r.hello_body()["agents"][0]["status"] == "stopped"
    # Nothing of the finished workspace is left synced or bound.
    assert r.state.owned == {}
    assert r.bridge.registry.bindings() == {}
    # And it can be started again.
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert r.hello_body()["agents"][0]["status"] == "running"


def test_the_runner_remembers_its_agents_across_a_restart(make_runner, herdr: Herdr, hub: Hub):
    make_runner().launch({"room": "eng", "handle": "scout", "framework": "claude"})
    again = make_runner()
    assert [a["handle"] for a in again.hello_body()["agents"]] == ["scout"]


# ── jobs ──────────────────────────────────────────────────────────────────────


def test_every_job_is_reported_done_or_failed(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.take(
        {
            "id": "j1",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "a", "framework": "claude"},
        }
    )
    r.take(
        {"id": "j2", "kind": "launch", "spec": {"room": "eng", "handle": "b", "framework": "codex"}}
    )
    r.take({"id": "j3", "kind": "reboot", "spec": {}})

    reports = {p.rsplit("/", 1)[1]: b for m, p, b in hub.seen if m == "PATCH"}
    assert reports["j1"]["status"] == "done"
    assert reports["j1"]["result"]["pane"] == "w9:p1"
    assert reports["j2"] == {
        "status": "failed",
        "result": None,
        "error": "codex is not installed on " + r.label + ".",
    }
    assert "doesn't know how to do 'reboot'" in reports["j3"]["error"]
    # Each job is followed by a heartbeat, so the app sees the new state at once.
    assert len(hub.of("POST", "/api/runners")) == 3


def test_no_sync_pass_runs_while_a_job_opens_panes(make_runner, herdr: Herdr, hub: Hub):
    # A sync pass that saw a new pane before the launch mapped it would enroll
    # it as a second member (seen live as `@1`), so jobs and passes take turns.
    r = make_runner()
    during: list[bool] = []
    real_launch = r.launch

    def launch(spec: dict) -> dict:
        during.append(r._panes.locked())
        return real_launch(spec)

    r.launch = launch
    r.take(
        {
            "id": "j1",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "a", "framework": "claude"},
        }
    )
    assert during == [True]
    assert not r._panes.locked()
    assert r.state.owned == {"w9": "eng"}


def test_a_swarm_job_starts_the_team_briefs_it_and_kicks_it_off(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path
):
    r = make_runner()
    r.take(
        {
            "id": "s1",
            "kind": "swarm",
            "created_by": "julia",
            "spec": {
                "room": "eng",
                "key": "work/fix",
                "episode": "urn:ep:eng:t1",
                "task": "Fix the flaky tests",
                "team": ["agent-1", "agent-2"],
                "framework": "claude",
                "cwd": str(tmp_path),
                "worktree": False,
                "kickoff": True,
            },
        }
    )

    assert [c[2] for c in herdr.of("agent start")] == ["agent-1", "agent-2"]
    # The hub already wrote the members; the runner writes only their briefs.
    memory = hub.of("POST", "/api/rooms/eng/memory")
    assert [i["key"] for i in memory[0]["items"]] == [
        "agents/agent-1/notes",
        "agents/agent-2/notes",
    ]
    kickoff = hub.of("POST", "/api/rooms/eng/messages")[0]
    assert kickoff["content"] == "@conductor swarm @agent-1 @agent-2: Fix the flaky tests"
    assert kickoff["episode"] == "urn:ep:eng:t1"
    report = next(b for m, p, b in hub.seen if m == "PATCH")
    assert report["status"] == "done"
    assert [a["handle"] for a in r.hello_body()["agents"]] == ["agent-1", "agent-2"]
    env = herdr.of("workspace create")[0]
    assert "MYCELIUM_API_URL=http://hub:8000" in env


# ── asking the person at this machine ─────────────────────────────────────────


def _until(check: Any, timeout: float = 5.0) -> Any:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.01)
    raise AssertionError("timed out")


def _report(hub: Hub, job_id: str, status: str) -> dict | None:
    return next(
        (
            b
            for m, p, b in hub.seen
            if m == "PATCH" and p.endswith(job_id) and b["status"] == status
        ),
        None,
    )


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(approvals, "CHECK_S", 0.01)


LAUNCH = {"room": "eng", "handle": "a", "framework": "claude"}


def test_a_launch_from_a_hub_the_runner_does_not_own_waits_for_a_yes(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, quick: None
):
    asked: list[dict] = []
    r = make_runner(trust_hub=False, on_request=asked.append)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": LAUNCH, "created_by": "bob"})

    _until(lambda: _report(hub, "a1b2c3d4", "waiting"))
    assert herdr.of("agent start") == []
    [waiting] = approvals.pending(base=tmp_path)
    assert waiting["title"] == f"Start @a on {r.label}?"
    assert "Asked for by @bob" in waiting["message"]
    assert asked == [waiting]

    approvals.answer("a1b2c3d4", yes=True, base=tmp_path)
    _until(lambda: _report(hub, "a1b2c3d4", "done"))
    assert [c[2] for c in herdr.of("agent start")] == ["a"]
    assert approvals.pending(base=tmp_path) == []


def test_a_declined_launch_starts_nothing_and_says_so(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": LAUNCH})
    _until(lambda: approvals.pending(base=tmp_path))
    approvals.answer("a1b2c3d4", yes=False, base=tmp_path)

    failed = _until(lambda: _report(hub, "a1b2c3d4", "failed"))
    assert failed["error"] == f"Declined on {r.label}."
    assert herdr.of("agent start") == []
    assert herdr.of("workspace create") == []


def test_the_runner_syncs_every_bound_workspace_not_only_its_own(
    make_runner, monkeypatch: pytest.MonkeyPatch
):
    # A workspace a person bound by hand hears its mentions as soon as the
    # runner is running: binding it is the choice to sync it.
    r = make_runner()
    r.state.owned = {"w9": "eng"}
    r.bridge.registry.bind("w5", "tome")
    synced: list[list[tuple[str, str]]] = []
    monkeypatch.setattr(
        "mycelium.commands.herdr.sync_pass",
        lambda _config, _bridge, targets, **_kw: synced.append(sorted(targets)),
    )
    r.host.sync(r.config, r.state, r.log)
    assert synced == [[("w5", "tome"), ("w9", "eng")]]


def test_the_heartbeat_carries_every_agent_on_the_machine(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch(LAUNCH)
    report = r.hello_body()["machine"]
    assert report["runner"] is True
    [agent] = [a for w in report["workspaces"] for a in w["agents"]]
    assert (agent["handle"], agent["room"], agent["state"]) == ("a", "eng", "idle")


def test_a_restart_from_the_hub_asks_first_then_starts_the_agent_in_its_pane(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner()
    r.launch(LAUNCH)
    herdr.live.clear()  # herdr's server restarted: the pane is back, the agent isn't
    r.trust_hub = False

    r.take(
        {"id": "c0ffee01", "kind": "restart", "spec": {"agents": [{"handle": "a", "room": "eng"}]}}
    )
    [waiting] = _until(lambda: approvals.pending(base=tmp_path))
    assert waiting["title"] == f"Restart 1 agent on {r.label}?"
    assert "as @a in eng" in waiting["message"]
    starts = len(herdr.of("agent start"))

    approvals.answer("c0ffee01", yes=True, base=tmp_path)
    done = _until(lambda: _report(hub, "c0ffee01", "done"))
    assert done["result"]["restarted"] == {"a": "w9:p1"}
    assert len(herdr.of("agent start")) == starts + 1
    assert "You were restarted" in herdr.of("agent prompt")[-1][3]


def test_the_question_shows_the_agents_instructions_and_folder(
    make_runner, hub: Hub, tmp_path: Path, quick: None
):
    hub.notes_for = "a"
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": {**LAUNCH, "cwd": str(tmp_path)}})
    [waiting] = _until(lambda: approvals.pending(base=tmp_path))
    assert "Claude Code would start as @a" in waiting["message"]
    assert str(tmp_path) in waiting["message"]
    assert "Its instructions:\nBe terse." in waiting["message"]
    assert "someone on that hub" in waiting["message"]
    r.stop()
    _until(lambda: _report(hub, "a1b2c3d4", "failed"))


def test_a_launch_this_machine_could_not_do_fails_without_asking(
    make_runner, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": {**LAUNCH, "framework": "codex"}})
    failed = _until(lambda: _report(hub, "a1b2c3d4", "failed"))
    assert "codex is not installed" in failed["error"]
    assert approvals.pending(base=tmp_path) == []


def test_a_job_id_that_isnt_one_never_becomes_a_file(
    make_runner, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    r.take({"id": "../../evil", "kind": "launch", "spec": LAUNCH})
    _until(
        lambda: any(
            m == "PATCH" and "isn't a job id" in (b.get("error") or "") for m, _p, b in hub.seen
        )
    )
    assert not (tmp_path.parent / "evil.json").exists()


def test_a_scan_and_a_stop_do_not_ask(make_runner, hub: Hub, tmp_path: Path):
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "scan", "spec": {}})
    assert _report(hub, "a1b2c3d4", "done")
    assert approvals.pending(base=tmp_path) == []


def test_a_stopped_runner_gives_up_on_its_question(
    make_runner, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": LAUNCH})
    _until(lambda: approvals.pending(base=tmp_path))
    r.stop()
    failed = _until(lambda: _report(hub, "a1b2c3d4", "failed"))
    assert "stopped before anyone answered" in failed["error"]


def test_answering_what_isnt_waiting_says_so(tmp_path: Path):
    with pytest.raises(approvals.ApprovalError, match="Nothing is waiting"):
        approvals.answer("a1b2c3d4", yes=True, base=tmp_path)


# ── what the runner leaves in runner.log ──────────────────────────────────────


def _log() -> str:
    return (daemon.runner_dir() / "runner.log").read_text()


@pytest.fixture
def quiet_hub(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The hub's side of a sync pass: presence taken, and ``wakes`` handed out once."""
    wakes: list[dict] = []

    def fetch(_config: Any, room: str) -> list[dict]:
        taken = [w for w in wakes if w.get("room") == room]
        for w in taken:
            wakes.remove(w)
        return taken

    monkeypatch.setattr("mycelium.commands.herdr.fetch_wakes", fetch)
    monkeypatch.setattr("mycelium.commands.herdr._push_presence", lambda *_a, **_kw: True)
    monkeypatch.setattr("mycelium.commands.agent._write_manifest", lambda *_a, **_kw: None)
    return wakes


def test_each_wake_is_a_line_with_its_pane_outcome_and_time(
    make_runner, hub: Hub, quiet_hub: list[dict]
):
    r = make_runner()
    r.launch(LAUNCH)
    quiet_hub += [
        {"room": "eng", "handle": "a", "reason": "mention"},
        {"room": "eng", "handle": "ghost", "reason": "turn"},
    ]
    r.sync_pass()
    log = _log()
    assert re.search(r"INFO .* wake @a \(mention\) -> w9:p1 ok \d+ms", log)
    assert "wake @ghost (turn) in eng: no pane here is bound to it" in log
    assert r.sync_health()["last_pass_at"] is not None
    assert r.sync_health()["running_s"] is None


def test_each_job_is_a_line_with_its_outcome_and_time(make_runner, hub: Hub):
    r = make_runner()
    r.take({"id": "j1", "kind": "launch", "spec": LAUNCH})
    r.take({"id": "j2", "kind": "launch", "spec": {**LAUNCH, "framework": "nope"}})
    log = _log()
    assert re.search(r"job j1 launch done \d+ms", log)
    assert re.search(r"job j2 launch failed \d+ms: nope is not installed", log)


def test_a_question_asked_and_answered_is_in_the_log(
    make_runner, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": LAUNCH})
    _until(lambda: approvals.pending(base=tmp_path))
    approvals.answer("a1b2c3d4", yes=False, base=tmp_path)
    _until(lambda: _report(hub, "a1b2c3d4", "failed"))
    log = _log()
    assert "job a1b2c3d4: asked here: Start @a" in log
    assert "job a1b2c3d4: answered no" in log


def test_a_stuck_sync_pass_is_logged_with_every_stack_and_reported(
    make_runner, hub: Hub, quiet_hub: list[dict], monkeypatch: pytest.MonkeyPatch
):
    # The pass waits on a job's panes lock that is never let go: from outside
    # it looks like a runner that is connected and does nothing.
    monkeypatch.setattr(daemon, "SYNC_STALL_S", 0.05)
    r = make_runner()
    r.launch(LAUNCH)
    r._panes.acquire()
    stuck = threading.Thread(target=r.sync_pass, name="runner-sync", daemon=True)
    stuck.start()
    _until(lambda: (r.sync_health()["running_s"] or 0) >= 0.05)
    r.watch()
    r.watch()  # once per pass, not once per look

    log = _log()
    assert log.count("sync pass stuck") == 1
    assert "--- runner-sync" in log
    assert "in sync_pass" in log
    body = r.hello_body()
    assert body["sync"]["running_s"] >= 0.05
    [stalled] = [p for p in body["machine"]["problems"] if p["kind"] == "wakes_stalled"]
    assert stalled["handles"] == ["a"]

    r._panes.release()
    stuck.join(timeout=5)
    assert "sync pass finished after" in _log()
    assert r.sync_health()["running_s"] is None


def test_mycelium_machine_reads_a_stall_from_the_runner_it_did_not_start(
    tmp_path: Path, isolated_home: Path
):
    import os

    path = tmp_path / "sync.json"
    body = {"pid": os.getpid(), "at": daemon._now(), "running_s": 95.0, "stall_s": 30.0}
    path.write_text(json.dumps(body))
    assert daemon.read_sync(path) == body
    path.write_text(json.dumps({**body, "at": "2020-01-01T00:00:00+00:00"}))
    assert daemon.read_sync(path) is None  # written long ago: says nothing about now

    problems = machine._problems([], [], True, None, None, "mbp", [], True, body)
    assert [p.kind for p in problems] == ["wakes_stalled"]
    assert "for 1 minute" in problems[0].text


def test_a_herdr_call_that_never_answers_is_given_up_on(tmp_path: Path, isolated_home: Path):
    open_log(tmp_path / "runner.log")

    def hangs(args: list[str]) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(["herdr", *args], timeout=30)

    bridge = HerdrBridge(runner=hangs, registry=HerdrRegistry(tmp_path / "herdr.json"))
    with pytest.MonkeyPatch.context() as m:
        m.setattr("shutil.which", lambda _: "/usr/bin/herdr")
        with pytest.raises(HerdrUnavailableError, match="gave no answer in 30s"):
            bridge.list_agents()
        assert bridge.available() is False
    assert "herdr agent list gave no answer" in (tmp_path / "runner.log").read_text()
    assert call_timeout(["agent", "list"]) == CALL_TIMEOUT_S
    assert call_timeout(["agent", "prompt", "p", "hi", "--wait", "--timeout", "120000"]) == (
        120 + CALL_TIMEOUT_S
    )


# ── devices paired with this machine ──────────────────────────────────────────


def _device() -> tuple[Any, str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec

    from mycelium.runner.pairing import b64url

    key = ec.generate_private_key(ec.SECP256R1())
    n = key.public_key().public_numbers()
    return key, b64url(n.x.to_bytes(32, "big")), b64url(n.y.to_bytes(32, "big"))


def _sign(
    key: Any, kind: str, fields: dict, *, runner: str = "julias-mbp-ab12", ts: float | None = None
) -> dict:
    """A signature as the app makes one: ECDSA P-256 over the body's bytes, ``r||s``."""
    import secrets
    import time

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    from mycelium.runner.pairing import b64url, key_id

    n = key.public_key().public_numbers()
    kid = key_id(b64url(n.x.to_bytes(32, "big")), b64url(n.y.to_bytes(32, "big")))
    body = json.dumps(
        {
            "v": 1,
            "runner": runner,
            "kind": kind,
            "ts": time.time() if ts is None else ts,
            "nonce": secrets.token_hex(8),
            "job": fields,
        }
    )
    r, s = decode_dss_signature(key.sign(body.encode(), ec.ECDSA(hashes.SHA256())))
    return {"key": kid, "body": body, "sig": b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}


def _pair(r: daemon.Runner, x: str, y: str, limits: Any = None, name: str = "work laptop") -> Any:
    from mycelium.runner import pairing

    code = pairing.offer(limits or pairing.Limits.make())
    spec = {"offer": code[:4], "name": name, "key": {"x": x, "y": y}}
    r.take(
        {"id": "a0a0a0", "kind": "pair", "spec": {**spec, "proof": pairing.proof(code, name, x, y)}}
    )
    return pairing.landed(code)


def test_a_code_from_this_machine_pairs_a_device(make_runner, hub: Hub):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    code = pairing.offer(pairing.Limits.make(clis=["opencode"]))
    assert r.hello_body()["pairing_offers"] == [code[:4]]
    _, x, y = _device()
    spec = {"offer": code[:4].lower(), "name": "work laptop", "key": {"x": x, "y": y}}
    r.take(
        {
            "id": "a0a0a0",
            "kind": "pair",
            "spec": {**spec, "proof": pairing.proof(code, "work laptop", x, y)},
        }
    )

    done = _until(lambda: _report(hub, "a0a0a0", "done"))
    assert done["result"]["name"] == "work laptop"
    assert done["result"]["key"] == pairing.key_id(x, y)
    assert done["result"]["clis"] == ["opencode"]
    hello = r.hello_body()
    assert hello["pairing_offers"] == []
    assert [p["name"] for p in hello["pairings"]] == ["work laptop"]


def test_a_wrong_proof_pairs_nothing_and_burns_the_code(make_runner, hub: Hub):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    code = pairing.offer(pairing.Limits.make())
    _, x, y = _device()
    for n in range(pairing.MAX_ATTEMPTS):
        wrong = pairing.proof("ZZZZ-ZZZZ-ZZZZ", "work laptop", x, y)
        spec = {"offer": code[:4], "name": "work laptop", "key": {"x": x, "y": y}, "proof": wrong}
        r.take({"id": f"b{n}b0b0", "kind": "pair", "spec": spec})
    assert "wrong" in _until(lambda: _report(hub, "b0b0b0", "failed"))["error"]
    assert (
        "too often"
        in _until(lambda: _report(hub, f"b{pairing.MAX_ATTEMPTS - 1}b0b0", "failed"))["error"]
    )
    assert pairing.load() == []
    assert pairing.live_offers() == []


def test_a_code_is_read_back_the_way_a_person_types_it():
    from mycelium.runner import pairing

    assert pairing.normalize_code("abcd-efgh-jkmo ") == "ABCDEFGHJKM0"
    assert pairing.normalize_code("i1l1 0000 0000") == "111100000000"
    with pytest.raises(pairing.PairingError):
        pairing.normalize_code("ABCD-EFGH")


def test_a_launch_a_paired_device_signed_starts_without_asking(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, quick: None
):
    r = make_runner(trust_hub=False)
    key, x, y = _device()
    _pair(r, x, y)
    fields = {**LAUNCH, "cwd": None}
    r.take(
        {
            "id": "c1c1c1",
            "kind": "launch",
            "spec": LAUNCH,
            "signature": _sign(key, "launch", fields),
        }
    )

    done = _until(lambda: _report(hub, "c1c1c1", "done"))
    assert done["pairing"] == {"name": "work laptop", "accepted": True}
    assert [c[2] for c in herdr.of("agent start")] == ["a"]
    assert approvals.pending(base=tmp_path) == []
    assert "signed by 'work laptop'" in (daemon.runner_dir() / "runner.log").read_text()


@pytest.mark.parametrize(
    ("limits", "kind", "fields", "spec", "why"),
    [
        pytest.param(
            {"clis": ["opencode"]},
            "launch",
            {**LAUNCH, "cwd": None},
            LAUNCH,
            "agent CLI is outside",
            id="a-cli-it-doesnt-cover",
        ),
        pytest.param(
            {"folders": [Path("/elsewhere")]},
            "launch",
            {**LAUNCH, "cwd": None},
            LAUNCH,
            "outside the folders this pairing allows",
            id="a-folder-it-doesnt-cover",
        ),
        pytest.param(
            {},
            "launch",
            {**LAUNCH, "cwd": None},
            {**LAUNCH, "handle": "b"},
            "doesn't match the job",
            id="a-job-the-hub-changed",
        ),
        pytest.param(
            {},
            "swarm",
            {
                "room": "eng",
                "task": "t",
                "framework": "claude",
                "cwd": None,
                "size": 2,
                "worktree": False,
            },
            {
                "room": "eng",
                "task": "t",
                "framework": "claude",
                "team": ["a-1", "a-2"],
                "key": "k",
                "episode": "e",
            },
            "doesn't allow swarms",
            id="a-team-without-teams",
        ),
    ],
)
def test_a_signed_job_the_pairing_doesnt_cover_asks_and_says_why(
    make_runner, hub: Hub, tmp_path: Path, quick: None, limits, kind, fields, spec, why
):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    key, x, y = _device()
    _pair(r, x, y, pairing.Limits.make(**limits))
    r.take({"id": "d1d1d1", "kind": kind, "spec": spec, "signature": _sign(key, kind, fields)})

    waiting = _until(lambda: _report(hub, "d1d1d1", "waiting"))
    assert waiting["pairing"]["accepted"] is False
    assert why in waiting["pairing"]["reason"]
    [asked] = approvals.pending(base=tmp_path)
    assert why in asked["message"]


def test_a_signature_is_good_once_and_only_while_fresh(make_runner, hub: Hub, quick: None):
    import time

    r = make_runner(trust_hub=False)
    key, x, y = _device()
    _pair(r, x, y)
    sig = _sign(key, "launch", {**LAUNCH, "cwd": None})
    r.take({"id": "e1e1e1", "kind": "launch", "spec": LAUNCH, "signature": sig})
    _until(lambda: _report(hub, "e1e1e1", "done"))
    r.take({"id": "e2e2e2", "kind": "launch", "spec": LAUNCH, "signature": sig})
    assert "already used" in _until(lambda: _report(hub, "e2e2e2", "waiting"))["pairing"]["reason"]

    old = _sign(key, "launch", {**LAUNCH, "cwd": None}, ts=time.time() - 3600)
    r.take({"id": "e3e3e3", "kind": "launch", "spec": LAUNCH, "signature": old})
    assert "has expired" in _until(lambda: _report(hub, "e3e3e3", "waiting"))["pairing"]["reason"]


def test_an_unpaired_or_ended_device_asks_like_anyone(make_runner, hub: Hub, quick: None):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    key, x, y = _device()
    stranger, _, _ = _device()
    _pair(r, x, y, pairing.Limits.make(days=0))
    r.take(
        {
            "id": "f1f1f1",
            "kind": "launch",
            "spec": LAUNCH,
            "signature": _sign(stranger, "launch", {**LAUNCH, "cwd": None}),
        }
    )
    assert "isn't paired" in _until(lambda: _report(hub, "f1f1f1", "waiting"))["pairing"]["reason"]

    other = _sign(key, "launch", {**LAUNCH, "cwd": None}, runner="someone-elses")
    r.take({"id": "f2f2f2", "kind": "launch", "spec": LAUNCH, "signature": other})
    assert (
        "doesn't match the job"
        in _until(lambda: _report(hub, "f2f2f2", "waiting"))["pairing"]["reason"]
    )

    pairing.remove("work laptop")
    r.take(
        {
            "id": "f3f3f3",
            "kind": "launch",
            "spec": LAUNCH,
            "signature": _sign(key, "launch", {**LAUNCH, "cwd": None}),
        }
    )
    assert "isn't paired" in _until(lambda: _report(hub, "f3f3f3", "waiting"))["pairing"]["reason"]


def test_a_pairing_ends_when_it_says(make_runner, hub: Hub, quick: None):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    key, x, y = _device()
    made = _pair(r, x, y)
    pairings = pairing.load()
    pairings[0].limits.expires_at = "2020-01-01T00:00:00+00:00"
    pairing._save(pairings, None)  # noqa: SLF001 - ending it without waiting 90 days
    r.take(
        {
            "id": "a9a9a9",
            "kind": "launch",
            "spec": LAUNCH,
            "signature": _sign(key, "launch", {**LAUNCH, "cwd": None}),
        }
    )
    assert "expired" in _until(lambda: _report(hub, "a9a9a9", "waiting"))["pairing"]["reason"]
    assert made.name not in [p["name"] for p in r.hello_body()["pairings"]]


def test_a_signature_webcrypto_made_verifies_here():
    """A vector the browser made (``crypto.subtle``, P-256, ``r||s``), checked as the runner does."""
    from mycelium.runner import pairing

    x, y = (
        "kGLaxTmOR24jd44ln-NWsHpIvRVwmbKQpjAhdVVbNng",
        "4NdlYCR4WCc4s-0SXpeuNflUTHFt2ppIRnbcR5NYDVo",
    )
    body = '{"v":1,"runner":"studio-mini-ab12","kind":"launch","ts":1790000000,"nonce":"0011223344556677","job":{"room":"eng","handle":"a","framework":"opencode","cwd":null}}'
    sig = "xTTMH3znUs_nJ0rvcWMnNPMgUcj3GGt9i4btstfkr1OV1EZrRjnXqVBSedycz6idfS8RXwp8NsSF5uP92qg0pA"
    assert pairing.key_id(x, y) == "10e112267b23b604"
    assert pairing.verify_signature(x, y, body.encode(), sig)
    assert not pairing.verify_signature(x, y, body.replace('"a"', '"b"').encode(), sig)


def test_a_pairing_proof_is_the_one_the_browser_makes():
    """``device-key.test.ts`` pins the same value from WebCrypto."""
    from mycelium.runner import pairing

    proof = pairing.proof("K7QM-4XHD-9RWA", "work laptop", "A" * 43, "B" * 43)
    assert proof == "zakRBGwNeLR_W1E702hnTIRWyo1daHS8tqBe3QmCZOc"
