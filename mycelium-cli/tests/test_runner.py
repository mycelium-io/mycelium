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
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from mycelium.config import MyceliumConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrRegistry
from mycelium.runner import approvals, daemon, frameworks

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
        self._panes = 0
        self.fail_start = False

    def _pane(self) -> str:
        self._panes += 1
        return f"w9:p{self._panes}"

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        head = " ".join(args[:2])
        if args[:3] == ["agent", "start", "--help"]:
            return _proc(HELP)
        if head == "workspace create":
            pane = self._pane()
            return _proc(_ok({"workspace": {"workspace_id": "w9"}, "root_pane": {"pane_id": pane}}))
        if head == "pane split":
            return _proc(_ok({"pane": {"pane_id": self._pane()}}))
        if head == "agent start":
            if self.fail_start:
                return _proc(stderr=json.dumps({"error": "agent never became ready"}), returncode=1)
            self.live[args[args.index("--pane") + 1]] = "idle"
            return _proc(_ok({}))
        if head == "agent prompt":
            return _proc(_ok({}))
        if head == "agent list":
            agents = [{"pane_id": p, "agent_status": s} for p, s in self.live.items()]
            return _proc(_ok({"agents": agents}))
        if head == "agent get":
            status = self.live.get(args[2])
            return _proc(
                _ok({"agent": {"pane_id": args[2], "agent_status": status}} if status else {})
            )
        if head == "pane close":
            self.live.pop(args[2], None)
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
    # Started in a session chosen here, so it can be resumed after a restart.
    agent_args = start[start.index("--") + 1 :]
    assert agent_args[0] == "--session-id"
    session = agent_args[1]
    assert agent_args[2:] == ["--allowedTools", "Bash(mycelium:*)"]
    prompt = herdr.of("agent prompt")[0][3]
    assert "You are @scout" in prompt
    assert "mycelium memory get agents/scout/notes" in prompt
    # A closed pane stops the agent; it does not remove it from the room.
    mapping = r.bridge.registry.get("eng", "scout")
    assert mapping is not None
    assert (mapping.pane, mapping.managed) == ("w9:p1", False)
    # Its session and folder are kept with the pane, for resuming.
    assert mapping.session == session
    assert mapping.cwd == str((tmp_path / "api").resolve())
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
