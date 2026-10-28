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

#: The real install folders, which every test but the one about them has stubbed out.
REAL_INSTALL_DIRS = frameworks.install_dirs

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
        #: The agent CLI session herdr reports for a live pane, by pane.
        self.sessions: dict[str, str] = {}
        #: Open panes, with an agent in them or not.
        self.panes: list[str] = []
        self._panes = 0
        self.fail_start = False
        #: ``agent start`` runs the agent CLI, which exits before it comes up.
        self.exits_on_start = False
        #: ``agent start`` fails, but leaves an agent on the pane in this state,
        #: the way one stopped at a first-run prompt never reads as ready.
        self.start_leaves: str | None = None
        #: How many ``agent start`` calls find the pane's shell still starting.
        self.shell_starting = 0
        #: Called on every ``agent start``, to look at the runner while herdr waits.
        self.on_start: Any = None
        #: A working agent sent a key settles to idle, the way an interrupted one does.
        self.keys_settle = False
        #: What ``pane read`` shows.
        self.screen = "Allow this command?\n  make deploy\n\n  1. Yes\n  2. No, exit\n"
        #: What the screen shows after each key pressed, in turn.
        self.screens_after_keys: list[str] = []
        #: The folder herdr says an agent's process runs in.
        self.agent_cwd: str | None = None
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
            pane = args[args.index("--pane") + 1]
            if self.on_start:
                self.on_start()
            if self.shell_starting:
                self.shell_starting -= 1
                not_a_shell = f"agent target pane {pane} is not an available shell"
                return _proc(stderr=json.dumps({"error": not_a_shell}), returncode=1)
            if pane in self.live:
                taken = f"agent name {args[2]} is already used; candidates: pane_id={pane}"
                return _proc(stderr=json.dumps({"error": taken}), returncode=1)
            if self.start_leaves:
                self.live[pane] = self.start_leaves
                return _proc(stderr=json.dumps({"error": "agent never became ready"}), returncode=1)
            if self.fail_start:
                return _proc(stderr=json.dumps({"error": "agent never became ready"}), returncode=1)
            if self.exits_on_start:
                exited = "agent process exited before becoming interactive"
                return _proc(stderr=json.dumps({"error": exited}), returncode=1)
            self.live[args[args.index("--pane") + 1]] = "idle"
            return _proc(_ok({}))
        if head == "agent prompt":
            return _proc(_ok({}))
        if head == "agent list":
            agents = [
                {"pane_id": p, "agent_status": s, "workspace_id": "w9", "agent": "claude"}
                | (
                    {"agent_session": {"kind": "id", "value": self.sessions[p]}}
                    if p in self.sessions
                    else {}
                )
                for p, s in self.live.items()
            ]
            return _proc(_ok({"agents": agents}))
        if head == "pane read":
            return _proc(_ok({"text": self.screen}))
        if head in ("pane run", "pane send-keys"):
            if head == "pane send-keys" and self.keys_settle and args[2] in self.live:
                self.live[args[2]] = "idle"
            if head == "pane send-keys" and self.screens_after_keys:
                self.screen = self.screens_after_keys.pop(0)
            return _proc("")
        if head == "agent get":
            status = self.live.get(args[2])
            agent = {"pane_id": args[2], "agent_status": status}
            if self.agent_cwd:
                agent["foreground_cwd"] = self.agent_cwd
            return _proc(_ok({"agent": agent} if status else {}))
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
        #: A hub with sign-in on that this machine isn't signed in to.
        self.signed_out = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, request.url.path, body))
        if self.signed_out:
            return httpx.Response(401, json={"detail": "missing bearer token"})
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

    def which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        if name in ("herdr", "claude", "opencode", "aider"):
            return f"/usr/bin/{name}"
        return None if name != "git" else real_which(name)

    monkeypatch.setattr("shutil.which", which)
    monkeypatch.setattr(frameworks, "_version", lambda path, *_a: f"{Path(path).name} 1.0")
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
    # Not found here, and still offered: herdr starts it from the person's own
    # shell, which may have it, and the start says if it doesn't.
    assert not found["codex"].installed and found["codex"].launchable
    assert found["codex"].note == "not found on this machine"
    # What can be started leads the list, found ones first.
    assert [(f.launchable, f.installed) for f in found.values()][:3] == [
        (True, True),
        (True, True),
        (True, False),
    ]


def test_a_startable_cli_carries_no_note(herdr: Herdr, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(frameworks.shutil, "which", lambda name, path=None: f"/usr/bin/{name}")
    found = {f.id: f for f in frameworks.scan({"codex", "claude"})}
    assert found["codex"].launchable
    assert found["codex"].note is None
    assert found["claude"].note is None


def _program(path: Path, text: str = "#!/bin/sh\necho 1.0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def test_a_cli_under_nvm_is_found_in_the_newest_node_and_run_with_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """codex under nvm: not on the PATH the desktop app hands the runner. The
    scan finds it in nvm's folders, newest Node first, and its --version runs
    with that folder first on PATH, where its ``node`` is."""
    monkeypatch.setattr(frameworks, "install_dirs", REAL_INSTALL_DIRS)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("NVM_DIR", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    nodes = tmp_path / ".nvm" / "versions" / "node"
    # Newest by number, not by spelling: v24.10 is newer than v24.2.
    _program(nodes / "v9.11.0" / "bin" / "codex")
    _program(nodes / "v24.2.0" / "bin" / "codex")
    _program(nodes / "v24.10.1" / "bin" / "node")
    real = _program(nodes / "v24.10.1" / "bin" / "codex")

    ran: list[tuple] = []
    monkeypatch.setattr(
        frameworks, "_version", lambda path, search=None: ran.append((path, search)) or "1.0"
    )
    found = {f.id: f for f in frameworks.scan({"codex"})}

    assert found["codex"].installed and found["codex"].launchable
    assert found["codex"].path == str(real)
    # (Homebrew's folders are real on this machine, so only codex is checked.)
    assert [r for r in ran if r[0].endswith("/codex")] == [
        (str(real), f"{real.parent}:/usr/bin:/bin")
    ]


def test_the_scan_runs_nothing_of_the_persons_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Not their shell, not its rc files: what an rc file prints, how slow it
    is, or what it starts can't reach the runner."""
    shell = _program(tmp_path / "shell", "#!/bin/sh\ntouch " + str(tmp_path / "ran") + "\n")
    monkeypatch.setenv("SHELL", str(shell))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(frameworks, "install_dirs", lambda: [tmp_path / "bin"])
    _program(tmp_path / "bin" / "codex", "#!/bin/sh\necho 'codex --approve-for-me'\n")
    real_run = subprocess.run
    argv: list[list[str]] = []

    def run(cmd: Any, *a: Any, **kw: Any) -> Any:
        argv.append([str(c) for c in cmd])
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    from mycelium.integrations import agents

    frameworks.scan({"codex"})
    assert agents.of_kind("codex").offers("--approve-for-me")

    assert not (tmp_path / "ran").exists()
    assert argv
    assert all(str(shell) not in cmd and "-ilc" not in cmd for cmd in argv)
    assert not hasattr(frameworks, "terminal_path")


def test_without_herdr_nothing_is_startable(herdr: Herdr):
    found = frameworks.scan(None)
    assert not any(f.launchable for f in found)
    assert next(f for f in found if f.id == "claude").note == "herdr isn't running here"


def test_the_hello_says_what_this_machine_has(make_runner):
    body = make_runner().hello_body()
    assert body["id"] == "julias-mbp-ab12"
    assert body["herdr"] is True
    startable = [(f["id"], f["installed"]) for f in body["frameworks"] if f["launchable"]]
    assert startable == [("claude", True), ("opencode", True), ("codex", False), ("pi", False)]
    assert body["agents"] == []


def test_a_hub_that_refuses_this_machine_is_said_as_a_sign_in_and_clears_on_one(
    make_runner, hub: Hub
):
    r = make_runner()
    hub.signed_out = True
    assert r.hello() is False
    assert (r.connected, r.signed_out) == (False, True)
    hub.signed_out = False
    assert r.hello() is True
    assert (r.connected, r.signed_out) == (True, False)


def test_a_sign_in_that_cant_be_renewed_for_now_is_said_as_connecting_not_signed_out(
    make_runner, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """The issuer unreachable as the laptop wakes: nothing to sign in again for."""
    from mycelium.client import RenewalUnreachable

    r = make_runner()

    def unreachable(*_a: Any, **_k: Any) -> Any:
        # What building a client does when the sign-in needs renewing and can't be.
        raise RenewalUnreachable("couldn't renew this computer's sign-in: timed out")

    monkeypatch.setattr(daemon, "hub_client", unreachable)
    assert r.hello() is False
    assert (r.connected, r.signed_out) == (False, False)
    assert r.poll_once() is False


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


# ── registration: one way, however the runner was started ─────────────────────


def test_a_runner_registers_while_it_runs_and_says_who_started_it(make_runner, tmp_path: Path):
    import os

    r = make_runner()
    r.started_by = daemon.APP
    seen: list[object] = []
    r._run = lambda: seen.append(daemon.registered(tmp_path))  # type: ignore[method-assign]
    r.run()
    assert seen == [(os.getpid(), daemon.APP)]
    assert daemon.registered(tmp_path) is None  # taken back when it stops


def test_a_registration_is_only_taken_back_by_its_own_process(tmp_path: Path):
    import os

    (tmp_path / "runner.pid").write_text(f"{os.getppid()}\n")  # another process, alive
    daemon.unregister(tmp_path)
    assert daemon.registered(tmp_path) == (os.getppid(), daemon.TERMINAL)
    (tmp_path / "runner.pid").write_text("999999999\n")  # gone
    assert daemon.registered(tmp_path) is None


def test_the_apps_runner_counts_as_running_and_isnt_stopped_from_a_terminal(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """#1140: `mycelium machine`, `runner pair` and `herdr sync` read the same
    registration, and `runner stop` won't signal the app's supervisor."""
    import os

    from typer.testing import CliRunner

    from mycelium.commands import runner as cmd

    # The app's supervisor: a live process that isn't this one.
    folder = daemon.runner_dir()
    (folder / "runner.started-by").write_text(f"{daemon.APP}\n")
    (folder / "runner.pid").write_text(f"{os.getppid()}\n")
    assert cmd.running_pid() == os.getppid()
    assert cmd.runs_in_app()
    assert machine.report(bridge=HerdrBridge(runner=Herdr()), machine="mac").runner

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cmd.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    result = CliRunner().invoke(cmd.app, ["stop"])
    assert result.exit_code == 1
    assert "Mycelium app's" in result.output
    assert [sig for _pid, sig in killed if sig != 0] == []  # only liveness checks, no SIGTERM

    started = CliRunner().invoke(cmd.app, [])
    assert started.exit_code == 1
    assert "already running" in started.output


def test_a_runner_id_is_made_once_and_kept(tmp_path: Path):
    first = daemon.runner_id(tmp_path / "id")
    assert first == daemon.runner_id(tmp_path / "id")
    assert first.rsplit("-", 1)[1].isalnum()


# ── launch ────────────────────────────────────────────────────────────────────


def test_a_launched_agent_is_given_its_own_token_file_on_a_hub_with_auth_on(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from mycelium import agent_credentials

    issued: list[tuple[str, str]] = []

    def issue(_config: Any, room: str, handle: str) -> Path:
        issued.append((room, handle))
        return tmp_path / "scout.token"

    monkeypatch.setattr(agent_credentials, "issue_member_token", issue)
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    assert issued == [("eng", "scout")]
    create = herdr.of("workspace create")[0]
    # The path, never the token: a pane's environment is easy to print.
    assert f"MYCELIUM_AGENT_AUTH_TOKEN_FILE={tmp_path / 'scout.token'}" in create
    assert not any(arg.startswith("MYCELIUM_AGENT_AUTH_TOKEN=") for arg in create)


def test_a_machine_signed_out_of_a_gated_hub_starts_nothing_and_says_why(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    from mycelium import agent_credentials

    def refuse(_config: Any, _room: str, handle: str) -> Path:
        raise agent_credentials.MemberTokenRefused(handle, "https://hub.example", 401, "")

    monkeypatch.setattr(agent_credentials, "issue_member_token", refuse)
    r = make_runner()
    with pytest.raises(daemon.JobError, match="isn't signed in to https://hub.example") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    # The app shows the sign-in reason, and nothing was opened on the machine.
    assert failed.value.result is not None
    assert failed.value.result["why"] == "signin"
    assert herdr.of("workspace create") == []
    assert herdr.of("agent start") == []


def _token_until(exp: float) -> str:
    import base64

    claims = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"e30.{claims}.sig"


def test_running_agents_are_given_a_token_and_it_is_renewed_before_it_ends(
    make_runner, herdr: Herdr, monkeypatch: pytest.MonkeyPatch
):
    """An agent started before panes got a token file has one after a round, with no restart."""
    from mycelium import agent_credentials
    from mycelium.integrations.herdr import HerdrPaneMapping

    now = 2_000_000_000.0
    issued: list[tuple[str, str]] = []

    def issue(_config: Any, room: str, handle: str) -> Path:
        issued.append((room, handle))
        path = agent_credentials.member_token_path(room, handle)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_token_until(now + 30 * 86400))
        return path

    monkeypatch.setattr(agent_credentials, "issue_member_token", issue)
    r = make_runner()
    herdr.live["w9:p1"] = "idle"
    r.bridge.registry.set(HerdrPaneMapping(room="eng", handle="scout", pane="w9:p1", kind="claude"))
    # Its pane closed: nothing reads a token there.
    r.bridge.registry.set(HerdrPaneMapping(room="eng", handle="gone", pane="w9:p7", kind="claude"))

    r.keep_credentials(now=now)
    assert issued == [("eng", "scout")]
    r.keep_credentials(now=now + 60)
    assert issued == [("eng", "scout")], "a fresh token isn't asked for again"
    r.keep_credentials(now=now + 24 * 86400)
    assert issued == [("eng", "scout")] * 2, "under a week left, it's renewed"


def test_an_agent_the_hub_wont_give_a_token_is_asked_about_hourly_not_every_round(
    make_runner, herdr: Herdr, monkeypatch: pytest.MonkeyPatch
):
    from mycelium import agent_credentials
    from mycelium.integrations.herdr import HerdrPaneMapping

    asked: list[str] = []

    def refuse(_config: Any, _room: str, handle: str) -> Path:
        asked.append(handle)
        raise agent_credentials.MemberTokenRefused(handle, "https://hub.example", 403, "not yours")

    monkeypatch.setattr(agent_credentials, "issue_member_token", refuse)
    r = make_runner()
    herdr.live["w9:p1"] = "idle"
    r.bridge.registry.set(
        HerdrPaneMapping(room="eng", handle="theirs", pane="w9:p1", kind="claude")
    )

    r.keep_credentials(now=1000.0)
    r.keep_credentials(now=1060.0)
    assert asked == ["theirs"]
    r.keep_credentials(now=1000.0 + daemon.NO_TOKEN_RETRY_S + 1)
    assert asked == ["theirs", "theirs"]


def test_a_computer_not_signed_in_is_asked_about_every_round(
    make_runner, herdr: Herdr, monkeypatch: pytest.MonkeyPatch
):
    """Signing in is all it takes: the next round gives its agents their tokens."""
    from mycelium import agent_credentials
    from mycelium.integrations.herdr import HerdrPaneMapping

    asked: list[str] = []

    def signed_out(_config: Any, _room: str, handle: str) -> Path:
        asked.append(handle)
        raise agent_credentials.MemberTokenRefused(handle, "https://hub.example", 401, "")

    monkeypatch.setattr(agent_credentials, "issue_member_token", signed_out)
    r = make_runner()
    herdr.live["w9:p1"] = "idle"
    r.bridge.registry.set(HerdrPaneMapping(room="eng", handle="mine", pane="w9:p1", kind="claude"))

    r.keep_credentials(now=1000.0)
    r.keep_credentials(now=1060.0)
    assert asked == ["mine", "mine"]


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
    assert start[2:6] == ["scout_eng", "--kind", "claude", "--pane"]
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


def test_a_launch_with_a_worktree_starts_the_agent_on_its_own_branch(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path
):
    repo = tmp_path / "api"
    repo.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(  # noqa: S603
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args],  # noqa: S607
            check=True,
        )
    r = make_runner()

    r.launch(
        {
            "room": "eng",
            "handle": "scout",
            "framework": "claude",
            "cwd": str(repo),
            "worktree": True,
        }
    )

    tree = tmp_path / "api-eng-scout"
    create = herdr.of("workspace create")[0]
    assert create[create.index("--cwd") + 1] == str(tree.resolve())
    branch = subprocess.run(  # noqa: S603
        ["git", "-C", str(tree), "branch", "--show-current"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch.stdout.strip() == "swarm/eng/scout"
    assert r.hello_body()["agents"][0]["cwd"] == str(tree.resolve())


def test_a_worktree_outside_a_repository_is_refused(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path
):
    (tmp_path / "plain").mkdir()
    r = make_runner()
    with pytest.raises(daemon.JobError, match="could not create a worktree"):
        r.launch(
            {
                "room": "eng",
                "handle": "scout",
                "framework": "claude",
                "cwd": str(tmp_path / "plain"),
                "worktree": True,
            }
        )
    assert herdr.of("agent start") == []


def test_the_next_agent_in_a_room_shares_its_workspace(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "one", "framework": "claude"})
    r.launch({"room": "eng", "handle": "two", "framework": "opencode"})
    assert len(herdr.of("workspace create")) == 1
    assert herdr.of("pane split")[0][2] == "w9:p1"
    assert herdr.of("agent start")[1][2:4] == ["two_eng", "--kind"]
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
        ({"framework": "nope"}, "not an agent CLI"),
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


def test_a_start_herdr_refused_keeps_its_pane_and_tries_there_again(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.fail_start = True
    r = make_runner()
    with pytest.raises(daemon.JobError, match="herdr couldn't start Claude Code") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    # Left open, so starting again doesn't open one more terminal each time.
    assert herdr.of("pane close") == []
    assert failed.value.result is not None
    assert failed.value.result["why"] == "host"
    assert failed.value.result["pane"] == "w9:p1"
    assert r.hello_body()["agents"] == []

    herdr.fail_start = False
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert result["pane"] == "w9:p1"
    assert herdr.panes == ["w9:p1"]


def test_a_shell_slow_to_start_is_waited_for(make_runner, herdr: Herdr, hub: Hub):
    herdr.shell_starting = 5
    r = make_runner()
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert result["pane"] == "w9:p1"
    assert len(herdr.of("agent start")) == 6
    assert r.hello_body()["agents"][0]["status"] == "running"


def test_a_shell_that_never_comes_up_says_so_and_keeps_its_terminal(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("mycelium.commands.swarm.SHELL_WAIT_S", 0)
    herdr.shell_starting = 1
    r = make_runner()
    with pytest.raises(daemon.JobError, match="didn't reach a shell prompt") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert "start @scout again" in str(failed.value)
    assert failed.value.result is not None
    assert failed.value.result["step"] == "shell"
    assert failed.value.result["why"] == "shell"
    assert "not an available shell" in failed.value.result["detail"]
    assert herdr.of("pane close") == []

    # Its shell came up: starting again goes back to that terminal.
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert herdr.panes == ["w9:p1"]
    assert r.hello_body()["agents"][0]["status"] == "running"


def test_an_agent_cli_that_exits_at_start_says_so_and_is_not_started_again(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.exits_on_start = True
    r = make_runner()
    with pytest.raises(daemon.JobError, match="exited before it started") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert "start @scout again" in str(failed.value)
    assert failed.value.result is not None
    assert failed.value.result["why"] == "exited"
    # Where to look, never what it printed: that stays on this machine.
    assert failed.value.result["pane"] == "w9:p1"
    assert "make deploy" not in json.dumps(failed.value.result)
    # Once: starting it the same way again would only exit again.
    assert len(herdr.of("agent start")) == 1


def test_a_cli_that_needs_setting_up_is_told_before_anything_starts(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """Like a Codex that isn't signed in: no pane opened, nothing typed into one."""
    from mycelium.integrations import agents

    kind = type(agents.of_kind("claude"))
    monkeypatch.setattr(kind, "not_ready", lambda _self: "Sign in first. Then try again.")
    r = make_runner()
    with pytest.raises(daemon.JobError, match="can't start on .* yet. Sign in first") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert failed.value.result == {"why": "setup", "detail": "Sign in first. Then try again."}
    assert herdr.of("agent start") == []
    assert herdr.panes == []


#: Codex's screens, with something private on them that must never leave the machine.
SIGNED_IN = "sk-live-4f2a9c\n✓ Signed in with your ChatGPT account\n\n  Press enter to continue\n"
SIGN_IN = (
    "sk-live-4f2a9c\n> 1. Sign in with ChatGPT\n  2. Sign in with Device Code\n"
    "  Press enter to continue\n"
)
PROMPT = "› Ask Codex to do anything\n"


@pytest.fixture
def first_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude standing in for a CLI with first-run screens: Codex's own."""
    from mycelium.integrations import agents
    from mycelium.integrations.agents.codex import Codex

    monkeypatch.setattr(type(agents.of_kind("claude")), "first_run", Codex.first_run)
    monkeypatch.setattr("mycelium.integrations.herdr.bridge.FIRST_RUN_SETTLE_S", 0)


def test_a_welcome_screen_enter_gets_past_is_got_past_before_the_introduction(
    make_runner, herdr: Herdr, hub: Hub, first_runs: None
):
    """A signed-in Codex on its welcome, which herdr reads as ready: Enter, then the introduction."""
    herdr.screen = SIGNED_IN
    herdr.screens_after_keys = [PROMPT]
    r = make_runner()
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert "waiting" not in result
    assert [c[3:] for c in herdr.of("pane send-keys")] == [["enter"]]
    prompts = herdr.of("agent prompt")
    assert len(prompts) == 1
    assert "You are @scout" in prompts[0][3]


def test_a_sign_in_screen_holds_the_introduction_until_it_is_answered(
    make_runner, herdr: Herdr, hub: Hub, first_runs: None
):
    herdr.screen = SIGN_IN
    r = make_runner()
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    # Nothing pressed or typed into a screen only the person can answer.
    assert herdr.of("pane send-keys") == []
    assert herdr.of("agent prompt") == []
    assert result["waiting"].startswith("waiting for input on ")
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "blocked"
    assert "Codex is asking you to sign in" in agent["detail"]
    assert "herdr agent focus w9:p1" in agent["detail"]

    # herdr still reads it as idle; it stays waiting, its introduction held.
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "blocked"
    assert herdr.of("agent prompt") == []

    # Signed in: the welcome after it is got past, then the introduction goes in, once.
    herdr.screen = SIGNED_IN
    herdr.screens_after_keys = [PROMPT]
    r.refresh()
    r.refresh()
    prompts = herdr.of("agent prompt")
    assert len(prompts) == 1
    assert "You are @scout" in prompts[0][3]
    assert r.hello_body()["agents"][0]["status"] == "idle"

    # What reached the hub is the kind's words, never the screen.
    r.hello()
    sent = json.dumps([body for _m, _p, body in hub.seen])
    assert "sk-live-4f2a9c" not in sent
    assert "Sign in with Device Code" not in sent


def test_an_agent_past_its_first_run_never_has_its_screen_read_again(
    make_runner, herdr: Herdr, hub: Hub, first_runs: None
):
    herdr.screen = PROMPT
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert len(herdr.of("agent prompt")) == 1
    reads = len(herdr.of("pane read"))
    # Its introduction went in; whatever its screen shows from now on is its own.
    herdr.screen = SIGNED_IN
    r.refresh()
    r.refresh()
    assert len(herdr.of("pane read")) == reads
    assert herdr.of("pane send-keys") == []
    assert r.hello_body()["agents"][0]["status"] == "idle"


def test_a_cli_with_no_first_run_screens_never_has_its_screen_read(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.screen = SIGN_IN
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "opencode"})
    r.refresh()
    assert herdr.of("pane read") == []
    assert len(herdr.of("agent prompt")) == 1


def test_a_cli_the_scan_didnt_find_is_started_and_said_to_be_missing_when_it_isnt_there(
    make_runner, herdr: Herdr, hub: Hub
):
    # Its shell says "command not found", so no agent ever appears on the pane.
    herdr.exits_on_start = True
    r = make_runner()
    with pytest.raises(daemon.JobError, match="Codex isn't installed on") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "codex"})
    assert "Install Codex there, then start @scout again" in str(failed.value)
    assert failed.value.result is not None
    assert failed.value.result["why"] == "missing"
    assert failed.value.result["pane"] == "w9:p1"
    # It was tried: the person's own shell may have had it.
    assert len(herdr.of("agent start")) == 1


def test_an_agent_cli_that_never_comes_up_says_what_it_may_be_waiting_on(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    # Every start counts as one that ran the CLI and waited on it.
    monkeypatch.setattr("mycelium.commands.swarm.SLOW_START_S", 0)
    herdr.fail_start = True
    r = make_runner()
    with pytest.raises(daemon.JobError, match="didn't finish starting") as failed:
        r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert "update, a sign-in or a first-run question" in str(failed.value)
    assert failed.value.result is not None
    assert failed.value.result["why"] == "cli"
    # Where to look, never what it shows: that stays on this machine.
    assert failed.value.result["pane"] == "w9:p1"
    assert "No, exit" not in json.dumps(failed.value.result)
    # Started once, not again into a CLI that is waiting on the person.
    assert len(herdr.of("agent start")) == 1
    assert herdr.of("pane close") == []


def test_a_start_reports_its_steps_and_lets_the_sync_pass_run_while_herdr_waits(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("mycelium.commands.swarm.SHELL_WAIT_S", 0)
    herdr.shell_starting = 1
    r = make_runner()
    locked_during_start: list[bool] = []
    herdr.on_start = lambda: locked_during_start.append(r._panes.locked())  # noqa: SLF001
    r.take(
        {
            "id": "a1a1a1",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "scout", "framework": "claude"},
        }
    )

    failed = _until(lambda: _report(hub, "a1a1a1", "failed"))
    assert locked_during_start == [False]
    steps = [b["result"]["step"] for b in hub.of("PATCH", "a1a1a1") if b["status"] == "running"]
    assert steps == ["terminal", "shell"]
    assert failed["result"]["step"] == "shell"
    assert failed["result"]["pane"] == "w9:p1"
    assert "didn't reach a shell prompt" in failed["error"]
    # The lock is the runner's again once the job is over.
    assert not r._panes.locked()  # noqa: SLF001


def test_a_start_names_its_terminal_from_the_moment_it_opens_then_introduces_it(
    make_runner, herdr: Herdr, hub: Hub
):
    """The app streams the terminal and offers to open it from the first step that has one."""
    r = make_runner()
    r.take(
        {
            "id": "a2a2a2",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "scout", "framework": "claude"},
        }
    )
    _until(lambda: _report(hub, "a2a2a2", "done"))
    running = [b["result"] for b in hub.of("PATCH", "a2a2a2") if b["status"] == "running"]
    assert running == [
        {"step": "terminal"},
        {"step": "shell", "pane": "w9:p1"},
        {"step": "intro", "pane": "w9:p1"},
    ]
    assert len(herdr.of("agent prompt")) == 1


def test_a_claude_start_trusts_the_folder_it_was_started_in_then_introduces_it(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """The person chose the folder and approved the start; its trust question is theirs, answered."""
    from tests.test_agent_kinds import CLAUDE_TRUST, CLAUDE_TRUST_FOLDER, CLAUDE_TRUST_ON_YES

    monkeypatch.setattr("mycelium.integrations.herdr.bridge.FIRST_RUN_SETTLE_S", 0)
    herdr.start_leaves = "blocked"
    herdr.agent_cwd = CLAUDE_TRUST_FOLDER
    herdr.screen = CLAUDE_TRUST
    # One key refused as too soon after the question opened, then Down, then Enter.
    herdr.screens_after_keys = [CLAUDE_TRUST, CLAUDE_TRUST_ON_YES, "> "]
    herdr.keys_settle = True
    r = make_runner()

    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    assert [c[3:] for c in herdr.of("pane send-keys")] == [["down"], ["down"], ["enter"]]
    assert result["passed"] == ["Trusted the folder for Claude Code"]
    assert "waiting" not in result
    # Once it's idle, its introduction goes in.
    r.refresh()
    prompts = herdr.of("agent prompt")
    assert len(prompts) == 1
    assert "You are @scout" in prompts[0][3]
    assert r.hello_body()["agents"][0]["status"] == "idle"


def test_a_folder_whose_settings_grant_themselves_more_is_left_for_the_person(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    from tests.test_agent_kinds import CLAUDE_TRUST

    monkeypatch.setattr("mycelium.integrations.herdr.bridge.FIRST_RUN_SETTLE_S", 0)
    herdr.start_leaves = "blocked"
    herdr.screen = CLAUDE_TRUST.replace(" Security guide", " These will apply without asking.")
    r = make_runner()

    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    r.refresh()

    assert herdr.of("pane send-keys") == []
    assert herdr.of("agent prompt") == []
    assert "passed" not in result
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "blocked"
    assert "asking whether to trust this folder" in agent["detail"]


def test_a_launch_stopped_at_a_prompt_keeps_its_pane_and_waits_for_the_person(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.start_leaves = "blocked"
    r = make_runner()

    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    # Started once, not again into a name it already holds, and the pane is left open.
    assert len(herdr.of("agent start")) == 1
    assert herdr.of("pane close") == []
    assert result["pane"] == "w9:p1"
    assert result["waiting"].startswith("waiting for input on ")
    # Nothing is typed into the prompt it is stopped at.
    assert herdr.of("agent prompt") == []
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "blocked"
    assert "No, exit" not in agent["detail"]
    assert "Claude Code asks before" in agent["detail"]
    assert "herdr agent focus w9:p1" in agent["detail"]
    assert r.bridge.registry.get("eng", "scout") is not None

    # Still waiting: it says so again, and still hands nothing over.
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "blocked"
    assert herdr.of("agent prompt") == []

    # Answered: it gets its introduction once, as soon as it is idle.
    herdr.live["w9:p1"] = "idle"
    r.refresh()
    r.refresh()
    prompts = herdr.of("agent prompt")
    assert len(prompts) == 1
    assert "You are @scout" in prompts[0][3]
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "idle"
    assert "waiting for input" not in (agent["detail"] or "")


def test_an_agent_waiting_a_long_time_says_how_long_and_stays_open(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    herdr.start_leaves = "blocked"
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    monkeypatch.setattr(daemon, "WAITING_LONG", daemon.timedelta(0))
    r.refresh()
    assert r.hello_body()["agents"][0]["detail"].startswith("waiting for input on ")
    assert " for 0 min" in r.hello_body()["agents"][0]["detail"].splitlines()[0]
    assert herdr.of("pane close") == []


def test_a_waiting_agent_of_another_kind_is_told_nothing_about_claude(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.start_leaves = "blocked"
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "opencode"})
    detail = r.hello_body()["agents"][0]["detail"]
    assert "herdr agent focus w9:p1" in detail
    assert "Claude" not in detail


def test_a_start_herdr_calls_failed_with_its_agent_up_is_a_start(
    make_runner, herdr: Herdr, hub: Hub
):
    herdr.start_leaves = "idle"
    r = make_runner()
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert "waiting" not in result
    assert herdr.of("pane close") == []
    assert len(herdr.of("agent start")) == 1
    r.refresh()
    assert "You are @scout" in herdr.of("agent prompt")[0][3]


# ── after it is running ──────────────────────────────────────────────────────


def test_a_closed_pane_is_a_stopped_agent(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    herdr.live["w9:p1"] = "working"
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "working"

    herdr.live.clear()
    herdr.panes.clear()
    r.refresh()
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "stopped"
    assert agent["detail"] == "its herdr pane closed"
    assert r.bridge.registry.get("eng", "scout") is None


def test_an_agent_quit_and_started_again_in_its_pane_stays_itself(
    make_runner, herdr: Herdr, hub: Hub
):
    """A person quits the agent (to load an MCP, say) and starts it again in the
    same pane. The pane's mapping stays, so the sync pass never enrolls it as a
    new member named from its tab."""
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    herdr.live.clear()  # quit; the pane is still open
    r.refresh()
    agent = r.hello_body()["agents"][0]
    assert agent["status"] == "stopped"
    assert agent["detail"] == "it exited, and its herdr pane is still open"
    mapping = r.bridge.registry.get("eng", "scout")
    assert mapping is not None
    assert mapping.pane == "w9:p1"
    # Its workspace stays bound, so the agent started again there is synced.
    assert r.bridge.registry.bindings()

    herdr.live["w9:p1"] = "idle"  # started again by hand
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "idle"
    assert r.bridge.registry.get("eng", "scout") is not None

    # Quit again and then close the pane: now it has gone.
    herdr.live.clear()
    r.refresh()
    herdr.panes.clear()
    r.refresh()
    assert r.hello_body()["agents"][0]["detail"] == "its herdr pane closed"
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


def test_interrupt_sends_the_key_only_to_a_working_agent(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    # Idle: the key could clear what a person was typing, so nothing is pressed.
    herdr.live["w9:p1"] = "idle"
    assert r.do({"kind": "interrupt", "spec": {"room": "eng", "handle": "scout"}}) == {
        "pane": "w9:p1",
        "interrupted": False,
    }
    assert herdr.of("pane send-keys") == []
    # Working: its CLI's own key, and the session stays open.
    herdr.live["w9:p1"] = "working"
    result = r.do({"kind": "interrupt", "spec": {"room": "eng", "handle": "scout"}})
    assert result == {"pane": "w9:p1", "interrupted": True}
    assert herdr.of("pane send-keys") == [["pane", "send-keys", "w9:p1", "esc"]]
    assert herdr.of("pane close") == []


def test_interrupt_reaches_an_agent_the_runner_did_not_start(make_runner, herdr: Herdr, hub: Hub):
    from mycelium.integrations.herdr import HerdrPaneMapping

    r = make_runner()
    r.bridge.registry.set(
        HerdrPaneMapping(room="eng", handle="julia-claude", pane="w3:p1", kind="claude")
    )
    herdr.live["w3:p1"] = "working"
    result = r.do({"kind": "interrupt", "spec": {"room": "eng", "handle": "julia-claude"}})
    assert result == {"pane": "w3:p1", "interrupted": True}
    with pytest.raises(daemon.JobError, match="Nothing on"):
        r.do({"kind": "interrupt", "spec": {"room": "eng", "handle": "nobody"}})


def test_a_pause_stops_the_turn_then_says_it_is_a_pause(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    prompts_before = len(herdr.of("agent prompt"))
    herdr.live["w9:p1"] = "working"
    herdr.keys_settle = True
    spec = {"room": "eng", "handle": "scout", "by": "julia"}
    result = r.do({"kind": "pause", "spec": spec})
    assert result == {"pane": "w9:p1", "interrupted": True, "told": True}
    assert herdr.of("pane send-keys") == [["pane", "send-keys", "w9:p1", "esc"]]
    told = herdr.of("agent prompt")[prompts_before:]
    assert len(told) == 1
    assert "Paused by @julia from Mycelium" in told[0][3]
    assert "isn't a correction" in told[0][3]
    assert herdr.of("pane close") == []


def test_a_pause_leaves_an_idle_agent_untouched(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    herdr.live["w9:p1"] = "idle"
    prompts_before = len(herdr.of("agent prompt"))
    result = r.do({"kind": "pause", "spec": {"room": "eng", "handle": "scout", "by": "julia"}})
    # Nothing to stop, and nothing typed into a pane a person may be writing in.
    assert result == {"pane": "w9:p1", "interrupted": False, "told": False}
    assert herdr.of("pane send-keys") == []
    assert len(herdr.of("agent prompt")) == prompts_before


def test_stop_reaches_an_agent_the_runner_did_not_start(make_runner, herdr: Herdr, hub: Hub):
    from mycelium.integrations.herdr import HerdrPaneMapping

    r = make_runner()
    pane = herdr._pane("w3")
    r.bridge.registry.set(
        HerdrPaneMapping(room="eng", handle="planner", pane=pane, kind="claude", managed=True)
    )
    herdr.live[pane] = "working"
    assert r.do({"kind": "stop", "spec": {"room": "eng", "handle": "planner"}}) == {"pane": pane}
    assert herdr.of("pane close") == [["pane", "close", pane]]
    # Still a member, so it can be started again; the sync pass won't retire it.
    mapping = r.bridge.registry.get("eng", "planner")
    assert mapping is not None
    assert mapping.managed is False


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
        {"id": "j2", "kind": "launch", "spec": {"room": "eng", "handle": "b", "framework": "nope"}}
    )
    r.take({"id": "j3", "kind": "reboot", "spec": {}})

    reports = {p.rsplit("/", 1)[1]: b for m, p, b in hub.seen if m == "PATCH"}
    assert reports["j1"]["status"] == "done"
    assert reports["j1"]["result"]["pane"] == "w9:p1"
    assert reports["j2"] == {
        "status": "failed",
        "result": None,
        "error": "nope is not an agent CLI " + r.label + " knows.",
    }
    assert "doesn't know how to do 'reboot'" in reports["j3"]["error"]
    # Each job is followed by a heartbeat, so the app sees the new state at once.
    assert len(hub.of("POST", "/api/runners")) == 3


def test_no_sync_pass_runs_while_a_job_opens_panes(make_runner, herdr: Herdr, hub: Hub):
    # A sync pass that saw a new pane before the launch mapped it would enroll
    # it as a second member (seen live as `@1`), so a job opens and maps its
    # panes under the lock. Only the wait on herdr after that runs without it.
    r = make_runner()
    during: list[bool] = []
    real_launch = r.launch

    def launch(spec: dict, job_id: str | None = None) -> dict:
        during.append(r._panes.locked())
        return real_launch(spec, job_id=job_id)

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

    assert [c[2] for c in herdr.of("agent start")] == ["agent-1_eng", "agent-2_eng"]
    # The hub already wrote the members; the runner writes only their briefs.
    memory = hub.of("POST", "/api/rooms/eng/memory")
    assert [i["key"] for i in memory[0]["items"]] == [
        "agents/agent-1/notes",
        "agents/agent-2/notes",
    ]
    kickoff = hub.of("POST", "/api/rooms/eng/messages")[0]
    assert kickoff["content"] == "@conductor swarm @~agent-1 @~agent-2: Fix the flaky tests"
    assert kickoff["episode"] == "urn:ep:eng:t1"
    report = next(b for m, p, b in hub.seen if m == "PATCH")
    assert report["status"] == "done"
    assert [a["handle"] for a in r.hello_body()["agents"]] == ["agent-1", "agent-2"]
    env = herdr.of("workspace create")[0]
    assert "MYCELIUM_API_URL=http://hub:8000" in env


def test_a_swarm_of_a_cli_that_needs_setting_up_opens_no_panes(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from mycelium.integrations import agents

    kind = type(agents.of_kind("claude"))
    monkeypatch.setattr(kind, "not_ready", lambda _self: "Sign in first. Then try again.")
    r = make_runner()
    spec = {
        "room": "eng",
        "key": "work/fix",
        "episode": "urn:ep:eng:t1",
        "task": "Fix the flaky tests",
        "team": ["agent-1", "agent-2"],
        "framework": "claude",
        "cwd": str(tmp_path),
    }
    with pytest.raises(daemon.JobError, match="can't start on .* yet. Sign in first") as failed:
        r.swarm(spec, "julia")
    assert failed.value.result == {"why": "setup", "detail": "Sign in first. Then try again."}
    assert herdr.of("workspace create") == []
    assert herdr.of("agent start") == []


def test_a_swarm_member_left_at_a_sign_in_is_said_to_be_waiting_there(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, first_runs: None
):
    herdr.screen = SIGN_IN
    r = make_runner()
    spec = {
        "room": "eng",
        "key": "work/fix",
        "episode": "urn:ep:eng:t1",
        "task": "Fix the flaky tests",
        "team": ["agent-1"],
        "framework": "claude",
        "cwd": str(tmp_path),
    }
    with pytest.raises(daemon.JobError, match="waiting there: Codex is asking you to sign in"):
        r.swarm(spec, "julia")
    # Nothing typed into it, and its pane is left for the person.
    assert herdr.of("pane send-keys") == []
    assert herdr.of("pane close") == []


def test_a_swarm_trusts_the_folder_its_claude_members_start_in(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from tests.test_agent_kinds import CLAUDE_TRUST, CLAUDE_TRUST_FOLDER, CLAUDE_TRUST_ON_YES

    monkeypatch.setattr("mycelium.integrations.herdr.bridge.FIRST_RUN_SETTLE_S", 0)
    monkeypatch.setattr("mycelium.commands.swarm.SLOW_START_S", 0)
    herdr.start_leaves = "blocked"
    herdr.agent_cwd = CLAUDE_TRUST_FOLDER
    herdr.screen = CLAUDE_TRUST
    herdr.screens_after_keys = [CLAUDE_TRUST_ON_YES, "> "]
    herdr.keys_settle = True
    r = make_runner()
    spec = {
        "room": "eng",
        "key": "work/fix",
        "episode": "urn:ep:eng:t1",
        "task": "Fix the flaky tests",
        "team": ["agent-1"],
        "framework": "claude",
        "cwd": str(tmp_path),
        "kickoff": False,
    }
    r.swarm(spec, "julia")
    assert [c[3:] for c in herdr.of("pane send-keys")] == [["down"], ["enter"]]
    # Briefed once it's past the question.
    assert hub.of("POST", "/api/rooms/eng/memory")


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
    assert [c[2] for c in herdr.of("agent start")] == ["a_eng"]
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
    from mycelium.commands.herdr import SyncResult

    synced: list[list[tuple[str, str]]] = []

    def sync_pass(_config: Any, _bridge: Any, targets: list, **_kw: Any) -> SyncResult:
        synced.append(sorted(targets))
        return SyncResult(0, 0, 0, {})

    monkeypatch.setattr("mycelium.commands.herdr.sync_pass", sync_pass)
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

    # No session on record for it, and the question says what that costs.
    assert waiting["message"].startswith(
        "It comes back in a new session, so its conversation won't be kept. "
        "It catches up from the room:\n"
    )

    approvals.answer("c0ffee01", yes=True, base=tmp_path)
    done = _until(lambda: _report(hub, "c0ffee01", "done"))
    assert done["result"]["restarted"] == {"a": "w9:p1"}
    assert done["result"]["sessions"] == {"a": None}
    assert len(herdr.of("agent start")) == starts + 1
    assert "You were restarted" in herdr.of("agent prompt")[-1][3]


def test_a_restart_names_the_agents_that_wont_keep_their_conversations(
    make_runner, herdr: Herdr, hub: Hub, quick: None
):
    r = make_runner()
    for handle in ("a", "b", "c"):
        r.launch({**LAUNCH, "handle": handle})
    # Only @a has worked in a session on record.
    herdr.live["w9:p1"] = "working"
    herdr.sessions["w9:p1"] = "sess-a"
    r.sync_pass()
    herdr.live.clear()
    herdr.sessions.clear()

    agents = [{"handle": h, "room": "eng"} for h in ("a", "b", "c")]
    question = r.question({"kind": "restart", "spec": {"agents": agents}})
    assert question["message"].startswith(
        "@b and @c come back in new sessions and won't keep their conversations; "
        "the rest keep theirs:\n"
    )


def test_a_restart_resumes_the_session_the_agent_worked_in_and_lets_the_sync_pass_run(
    make_runner, herdr: Herdr, hub: Hub, quick: None
):
    r = make_runner()
    r.launch(LAUNCH)
    # It worked in its session, which a sync pass records.
    herdr.live["w9:p1"] = "working"
    herdr.sessions["w9:p1"] = "sess-1"
    r.sync_pass()
    # herdr's server restarted: the pane came back running a fresh session, idle.
    herdr.live["w9:p1"] = "idle"
    herdr.sessions["w9:p1"] = "sess-fresh"
    r.sync_pass()
    herdr.live.clear()
    herdr.sessions.clear()

    question = r.question({"kind": "restart", "spec": {"agents": [{"handle": "a", "room": "eng"}]}})
    assert question["message"].startswith(
        "It comes back in its own session and keeps its conversation:\n"
    )

    locked_during_start: list[bool] = []
    herdr.on_start = lambda: locked_during_start.append(r._panes.locked())  # noqa: SLF001
    with r._panes:  # noqa: SLF001 - a job runs holding the panes
        result = r.restart_agents({"agents": [{"handle": "a", "room": "eng"}]})

    assert result["sessions"] == {"a": "sess-1"}
    assert herdr.of("agent start")[-1][-2:] == ["--resume", "sess-1"]
    # The sync pass, and the wakes it delivers, didn't wait on the start.
    assert locked_during_start == [False]


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
    r.take({"id": "a1b2c3d4", "kind": "launch", "spec": {**LAUNCH, "framework": "aider"}})
    failed = _until(lambda: _report(hub, "a1b2c3d4", "failed"))
    assert "herdr can't start Aider" in failed["error"]
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

    def fetch(_config: Any, room: str, **_kw: Any) -> list[dict]:
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


def test_the_hub_is_told_what_became_of_each_wake(
    make_runner, hub: Hub, quiet_hub: list[dict], monkeypatch: pytest.MonkeyPatch
):
    told: list[tuple[str, list]] = []
    monkeypatch.setattr(
        "mycelium.commands.herdr.report_wakes",
        lambda _config, room, outcomes, **_kw: told.append((room, outcomes)),
    )
    r = make_runner()
    r.launch(LAUNCH)
    quiet_hub += [
        {"room": "eng", "id": "w1", "handle": "a", "reason": "mention"},
        {"room": "eng", "id": "w2", "handle": "ghost", "reason": "turn"},
        # From a hub that keeps no wake log: nothing to say about it.
        {"room": "eng", "handle": "a", "reason": "mention"},
    ]
    r.sync_pass()
    ((room, outcomes),) = [t for t in told if any(t[1])]
    assert room == "eng"
    assert [o for o in outcomes if o] == [
        {"id": "w1", "delivered": True},
        {"id": "w2", "delivered": False, "why": "no herdr pane here is bound to it"},
    ]


def test_each_job_is_a_line_with_its_outcome_and_time(make_runner, hub: Hub):
    r = make_runner()
    r.take({"id": "j1", "kind": "launch", "spec": LAUNCH})
    r.take({"id": "j2", "kind": "launch", "spec": {**LAUNCH, "framework": "nope"}})
    log = _log()
    assert re.search(r"job j1 launch done \d+ms", log)
    assert re.search(r"job j2 launch failed \d+ms: nope is not an agent CLI", log)


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
    assert [c[2] for c in herdr.of("agent start")] == ["a_eng"]
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


def test_a_binding_that_fails_leaves_the_others_and_the_wakes_going(
    make_runner, hub: Hub, quiet_hub: list[dict], monkeypatch: pytest.MonkeyPatch
):
    from mycelium.commands import herdr as herdr_cmd
    from mycelium_backend_client.errors import UnexpectedStatus

    r = make_runner()
    r.launch(LAUNCH)
    # Bound first, so a pass that stopped at it would never reach the runner's own.
    r.bridge.registry.bind("w0", "broken")
    reconcile = herdr_cmd._reconcile_workspace

    def flaky(config: Any, bridge: Any, ws: str, room: str, **kw: Any):
        if ws == "w0":
            raise UnexpectedStatus(404, b'{"detail":"Memory not found"}')
        return reconcile(config, bridge, ws, room, **kw)

    monkeypatch.setattr(herdr_cmd, "_reconcile_workspace", flaky)
    quiet_hub.append({"room": "eng", "handle": "a", "reason": "mention"})
    r.sync_pass()

    log = _log()
    assert "binding w0 -> broken failed" in log
    assert re.search(r"wake @a \(mention\) -> w9:p1 ok", log)
    health = r.sync_health()
    assert health["bindings"] == [
        {"workspace": "w0", "room": "broken", "error": "the hub answered 404: Memory not found"}
    ]
    assert "w0 → broken" in health["error"]
    [bad] = [p for p in r.hello_body()["machine"]["problems"] if p["kind"] == "binding_failing"]
    assert bad["fix"] == "mycelium herdr unbind w0"
    assert "can't sync with broken: the hub answered 404" in bad["text"]

    monkeypatch.setattr(herdr_cmd, "_reconcile_workspace", reconcile)
    r.bridge.registry.unbind("w0")
    r.sync_pass()
    assert r.sync_health()["bindings"] == []
    assert r.sync_health()["error"] is None


# ── adopt: an agent already running here joins a room ────────────────────────


def _already_running(herdr: Herdr, status: str = "idle") -> str:
    """A claude someone started themselves in a herdr pane, in no room."""
    pane = herdr._pane("w5")  # noqa: SLF001 - the fake's own pane maker
    herdr.live[pane] = status
    return pane


def test_adopt_asks_on_the_machine_first(make_runner, herdr: Herdr, hub: Hub):
    assert "adopt" in daemon.ASK_FIRST
    pane = _already_running(herdr)
    question = make_runner().question(
        {
            "kind": "adopt",
            "spec": {"room": "eng", "handle": "shop", "pane": pane, "framework": "claude"},
            "created_by": "julia",
        }
    )
    assert question["title"] == f"Bring the Claude Code in pane {pane} into eng as @shop?"
    assert "type a short introduction into it once it's idle" in question["message"]
    assert "@julia" in question["message"]


def test_a_signed_adopt_still_asks(
    make_runner, herdr: Herdr, hub: Hub, tmp_path: Path, quick: None
):
    from mycelium.runner import pairing

    r = make_runner(trust_hub=False)
    key, x, y = _device()
    _pair(r, x, y, pairing.Limits.make(swarms=True))
    spec = {"room": "eng", "handle": "shop", "pane": _already_running(herdr), "framework": "claude"}
    r.take({"id": "f1f1f1", "kind": "adopt", "spec": spec, "signature": _sign(key, "adopt", spec)})

    waiting = _until(lambda: _report(hub, "f1f1f1", "waiting"))
    assert waiting["pairing"] == {
        "accepted": False,
        "reason": "bringing in a running agent is always asked",
    }
    assert len(approvals.pending(base=tmp_path)) == 1


def test_adopt_maps_the_pane_and_introduces_an_idle_agent(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    pane = _already_running(herdr)
    result = r.adopt({"room": "eng", "handle": "shop", "pane": pane, "framework": "claude"})
    assert result == {"pane": pane, "introduced": True}
    mapping = r.bridge.registry.get("eng", "shop")
    assert (mapping.pane, mapping.managed) == (pane, False)
    [prompt] = herdr.of("agent prompt")
    assert prompt[2] == pane
    intro = prompt[3]
    assert "You are @shop, a member of the Mycelium room 'eng'" in intro
    assert "mycelium skill print" in intro
    assert "mycelium board --room eng" in intro
    # Its workspace isn't bound: that would enroll every other agent in it.
    assert r.bridge.registry.bindings() == {}
    # The runner lists it, so the app can stop it.
    assert [a["handle"] for a in r.hello_body()["agents"]] == ["shop"]


def test_adopt_waits_for_a_working_agent_to_be_idle(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    pane = _already_running(herdr, "working")
    assert r.adopt({"room": "eng", "handle": "shop", "pane": pane})["introduced"] is False
    assert herdr.of("agent prompt") == []
    herdr.live[pane] = "idle"
    r.refresh()
    assert [p[2] for p in herdr.of("agent prompt")] == [pane]


def test_adopt_refuses_a_pane_another_member_has(make_runner, herdr: Herdr, hub: Hub):
    from mycelium.integrations.herdr import HerdrPaneMapping

    r = make_runner()
    pane = _already_running(herdr)
    r.bridge.registry.set(HerdrPaneMapping(room="ops", handle="taken", pane=pane, kind="claude"))
    with pytest.raises(daemon.JobError, match=f"Pane {pane} is already @taken in ops"):
        r.adopt({"room": "eng", "handle": "shop", "pane": pane})


def test_adopt_refuses_a_pane_with_no_agent_left(make_runner, herdr: Herdr, hub: Hub):
    with pytest.raises(daemon.JobError, match="No agent is running in pane w5:p7"):
        make_runner().adopt({"room": "eng", "handle": "shop", "pane": "w5:p7"})


def test_an_adopt_that_fails_after_mapping_lets_go_of_the_pane(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    r = make_runner()
    pane = _already_running(herdr)

    def broken(*_a: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(r.state, "save", broken)
    with pytest.raises(daemon.JobError, match=f"pane {pane}: disk full"):
        r.adopt({"room": "eng", "handle": "shop", "pane": pane})
    assert r.bridge.registry.get("eng", "shop") is None
    assert "eng/shop" not in r.state.agents


def test_stopping_an_adopted_agent_never_closes_its_pane(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    pane = _already_running(herdr)
    r.adopt({"room": "eng", "handle": "shop", "pane": pane})
    r.stop_agent({"room": "eng", "handle": "shop"})
    assert herdr.of("pane close") == []
    assert pane in herdr.live
    assert r.bridge.registry.get("eng", "shop") is None
    assert r.hello_body()["agents"][0]["status"] == "stopped"


def test_the_machine_reports_agents_no_room_has(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    pane = _already_running(herdr)
    [unenrolled] = r.hello_body()["machine"]["unenrolled"]
    assert (unenrolled["pane"], unenrolled["kind"], unenrolled["state"]) == (pane, "claude", "idle")
    assert unenrolled["suggested_handle"] == "claude"


# ── rename ────────────────────────────────────────────────────────────────────


def test_a_renamed_agent_starts_again_under_its_new_handle(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    old_pane = r.state.agents["eng/scout"].pane

    question = r.question(
        {"kind": "rename", "spec": {"room": "eng", "handle": "scout", "to": "lookout"}}
    )
    assert question["title"] == f"Restart @scout as @lookout on {r.label}?"
    assert "Its pane closes, ending what it's doing" in question["message"]

    done = r.rename_agent({"room": "eng", "handle": "scout", "to": "lookout"})
    # Its old process can't take a new name, so its pane closed and a new one opened.
    assert old_pane not in herdr.panes
    assert done == {"handle": "lookout", "pane": done["pane"]}
    assert done["pane"] in herdr.panes
    assert herdr.of("agent start")[-1][2] == "lookout_eng"
    assert any("MYCELIUM_AGENT_HANDLE=lookout" in " ".join(c) for c in herdr.calls)
    # herdr reported no session for it, so it starts a new one, and says so.
    assert "--resume" not in herdr.of("agent start")[-1]
    assert "in a new session, so it doesn't keep its conversation" in question["message"]
    told = herdr.of("agent prompt")[-1][3]
    assert told.startswith("[mycelium] You are @lookout") and "You were @scout" in told

    assert r.bridge.registry.get("eng", "scout") is None
    moved = r.bridge.registry.get("eng", "lookout")
    assert moved is not None and moved.pane == done["pane"]
    assert list(r.state.agents) == ["eng/lookout"]
    assert daemon.State.load(r._state_path).agents["eng/lookout"].pane == done["pane"]


def test_a_renamed_agent_comes_back_in_its_own_session(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    herdr.sessions[r.state.agents["eng/scout"].pane] = "sess-1"

    question = r.question(
        {"kind": "rename", "spec": {"room": "eng", "handle": "scout", "to": "lookout"}}
    )
    assert "in its own session, keeping its conversation" in question["message"]

    done = r.rename_agent({"room": "eng", "handle": "scout", "to": "lookout"})
    start = herdr.of("agent start")[-1]
    assert start[2] == "lookout_eng"
    assert start[-2:] == ["--resume", "sess-1"]
    told = herdr.of("agent prompt")[-1][3]
    assert told.startswith("[mycelium] Your conversation was restored. You were @scout")
    assert "Use --handle lookout from now on" in told
    moved = r.bridge.registry.get("eng", "lookout")
    assert moved is not None and (moved.pane, moved.session) == (done["pane"], "sess-1")


def test_a_rename_for_an_agent_this_machine_doesnt_have_fails(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    with pytest.raises(daemon.JobError, match="No agent @nobody"):
        r.rename_agent({"room": "eng", "handle": "nobody", "to": "lookout"})


def test_the_hub_renames_before_the_agent_is_touched(make_runner, herdr: Herdr, hub: Hub):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    pane = r.state.agents["eng/scout"].pane
    starts = len(herdr.of("agent start"))

    r.rename_agent({"room": "eng", "handle": "scout", "to": "lookout"}, job_id="j1")
    # The go-ahead (the job reported running) went to the hub before the pane closed.
    reports = [(p, b) for m, p, b in hub.seen if m == "PATCH" and p.endswith("/jobs/j1")]
    assert reports[0][1]["status"] == "running"
    assert pane not in herdr.panes
    assert len(herdr.of("agent start")) == starts + 1


def test_a_rename_the_hub_refuses_leaves_the_agent_running(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    pane = r.state.agents["eng/scout"].pane

    def refused(_job_id: str) -> None:
        raise daemon.JobError("Not renamed: @lookout is already a member of eng.")

    monkeypatch.setattr(r, "_go_ahead", refused)
    with pytest.raises(daemon.JobError, match="already a member"):
        r.rename_agent({"room": "eng", "handle": "scout", "to": "lookout"}, job_id="j1")
    assert pane in herdr.panes


def test_nothing_a_pane_shows_ever_reaches_the_hub(
    make_runner, herdr: Herdr, hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    # A terminal can show keys and private code. The app shows it live on this
    # machine; the hub gets where to look and what state it's in, never what's
    # on the screen. This fails if any path to the hub starts carrying it.
    secret = "sk-live-4f2a9c Do you trust the files in this folder?"
    herdr.screen = secret
    monkeypatch.setattr("mycelium.commands.swarm.SLOW_START_S", 0)
    r = make_runner()

    herdr.start_leaves = "blocked"
    r.take(
        {
            "id": "b1b1b1",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "scout", "framework": "claude"},
        }
    )
    _until(lambda: _report(hub, "b1b1b1", "done"))
    herdr.start_leaves = None
    herdr.fail_start = True
    r.take(
        {
            "id": "c2c2c2",
            "kind": "launch",
            "spec": {"room": "eng", "handle": "lookout", "framework": "claude"},
        }
    )
    _until(lambda: _report(hub, "c2c2c2", "failed"))
    r.hello()

    sent = json.dumps([body for _m, _p, body in hub.seen])
    assert "sk-live-4f2a9c" not in sent
    assert "trust the files" not in sent
    # Read only on this machine, for a question it may answer, and only while
    # the introduction is held; this one is none it knows, so nothing is pressed.
    assert herdr.of("pane send-keys") == []
    assert list(r.state.agents) == ["eng/scout"]
    assert r.bridge.registry.get("eng", "scout") is not None
