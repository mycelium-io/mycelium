# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The runner with ``runner.host = omnigent``: agents as Omnigent sessions.

No hub and no Omnigent: both are ``httpx.MockTransport``s. These hold what the
scan reads from Omnigent (a kind is startable when its native agent's harness is
ready on this machine's host), that a launch asks the hub for a join code and
puts it first in what the session is told, that a session gets its own worktree
in a repository, and that presence and wakes flow through the same hub queues
herdr's do.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console

from mycelium.config import MyceliumConfig
from mycelium.runner import daemon, frameworks
from mycelium.runner.hosts import OmnigentHost, branch_for

MACHINE = "julias-mbp.local"


class Omnigent:
    """The parts of Omnigent's API the runner uses, with one host and a few agents."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.host_online = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if path == "/v1/hosts":
            return httpx.Response(
                200,
                json={
                    "hosts": [
                        {
                            "host_id": "h1",
                            "name": MACHINE,
                            "status": "online" if self.host_online else "offline",
                            "configured_harnesses": {
                                "claude-native": True,
                                "codex-native": "version-too-low",
                                "opencode-native": True,
                            },
                        },
                        {"host_id": "h2", "name": "someone-else", "status": "online"},
                    ]
                },
            )
        if path == "/v1/agents":
            rows = [
                {"id": "ag-claude", "name": "claude-native-ui"},
                {"id": "ag-codex", "name": "codex-native-ui"},
                {"id": "ag-opencode", "name": "opencode-native-ui"},
                {"id": "ag-polly", "name": "polly"},
            ]
            return httpx.Response(200, json={"data": rows})
        if path == "/v1/sessions" and request.method == "POST":
            sid = f"conv_{len(self.created) + 1}"
            self.created.append(body)
            workspace = body["workspace"] + ("/.worktrees/x" if body.get("git") else "")
            self.sessions[sid] = {
                "id": sid,
                "status": "idle",
                "title": body["title"],
                "labels": body["labels"],
                "runner_online": True,
                "workspace": workspace,
            }
            return httpx.Response(201, json=self.sessions[sid])
        if path == "/v1/sessions" and request.method == "GET":
            return httpx.Response(200, json={"data": list(self.sessions.values())})
        if path.endswith("/events"):
            sid = path.split("/")[3]
            self.events.append((sid, body))
            if body.get("type") == "stop_session":
                self.sessions[sid]["runner_online"] = False
            return httpx.Response(202, json={"queued": True})
        if path.startswith("/v1/sessions/"):
            sid = path.split("/")[3]
            if sid in self.sessions:
                return httpx.Response(200, json=self.sessions[sid])
            return httpx.Response(404, json={"detail": "no such session"})
        return httpx.Response(404, json={"detail": path})

    def said_to(self, sid: str) -> list[str]:
        return [
            e["data"]["content"][0]["text"]
            for s, e in self.events
            if s == sid and e.get("type") == "message"
        ]


class Hub:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.wakes: dict[str, list[dict[str, Any]]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.seen.append((request.method, path, body))
        if path.endswith("/joins"):
            return httpx.Response(
                201, json={"code": "abcd-efgh-jkmn", "room": "eng", "handle": body["handle"]}
            )
        if path.endswith("/notes"):
            return httpx.Response(404, json={"detail": "not found"})
        if path.endswith("/sessions/herdr-wakes"):
            room = path.split("/")[3]
            return httpx.Response(200, json={"wakes": self.wakes.pop(room, [])})
        return httpx.Response(200, json={})

    def of(self, method: str, suffix: str) -> list[Any]:
        return [b for m, p, b in self.seen if m == method and p.endswith(suffix)]


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Hub:
    hub = Hub()
    transport = httpx.MockTransport(hub.handler)

    @contextmanager
    def client(_config: Any = None, **_kw: Any):
        with httpx.Client(base_url="http://hub:8000", transport=transport) as c:
            yield c

    monkeypatch.setattr(daemon, "hub_client", client)
    real_get, real_post = httpx.get, httpx.post

    def get(url: str, **kw: Any) -> httpx.Response:
        if url.startswith("http://hub:8000"):
            with httpx.Client(transport=transport) as c:
                return c.get(url, headers=kw.get("headers"))
        return real_get(url, **kw)

    def post(url: str, **kw: Any) -> httpx.Response:
        if url.startswith("http://hub:8000"):
            with httpx.Client(transport=transport) as c:
                return c.post(url, json=kw.get("json"), headers=kw.get("headers"))
        return real_post(url, **kw)

    # The presence and wake calls go straight through httpx (commands/herdr.py).
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    return hub


@pytest.fixture
def omnigent(monkeypatch: pytest.MonkeyPatch) -> Omnigent:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in ("claude", "codex", "opencode") else None

    monkeypatch.setattr("shutil.which", which)
    monkeypatch.setattr(frameworks, "_version", lambda path: f"{Path(path).name} 1.0")
    return Omnigent()


@pytest.fixture
def make_runner(tmp_path: Path, omnigent: Omnigent, hub: Hub, isolated_home: Path):
    def make() -> daemon.Runner:
        config = MyceliumConfig()
        config.server.api_url = "http://hub:8000"
        config.runner.host = "omnigent"
        host = OmnigentHost(
            "http://omnigent.test",
            transport=httpx.MockTransport(omnigent.handler),
            machine=MACHINE,
        )
        r = daemon.Runner(
            config,
            roots=[tmp_path],
            host=host,
            rid="julias-mbp-ab12",
            state_path=tmp_path / "state.json",
            trust_hub=True,
            requests_base=tmp_path,
            log=Console(quiet=True),
        )
        r.scan()
        return r

    return make


def test_the_config_picks_the_host(isolated_home: Path):
    config = MyceliumConfig()
    assert daemon.Runner(config, roots=[]).host.name == "herdr"
    config.runner.host = "omnigent"
    assert daemon.Runner(config, roots=[]).host.name == "omnigent"


def test_a_kind_is_startable_when_its_harness_is_ready_on_this_host(make_runner):
    r = make_runner()
    body = r.hello_body()
    assert body["herdr"] is True
    assert body["host"] == "omnigent"
    launchable = {f["id"] for f in body["frameworks"] if f["launchable"]}
    assert launchable == {"claude", "opencode"}
    codex = next(f for f in body["frameworks"] if f["id"] == "codex")
    assert codex["note"] == "this omnigent can't start codex; it may need updating"


def test_without_this_machines_host_nothing_is_startable(make_runner, omnigent: Omnigent):
    omnigent.host_online = False
    r = make_runner()
    assert r.herdr is False
    claude = next(f for f in r.hello_body()["frameworks"] if f["id"] == "claude")
    assert (claude["launchable"], claude["note"]) == (False, "omnigent isn't running here")


def test_a_launch_joins_first_then_says_who_it_is(
    make_runner, omnigent: Omnigent, hub: Hub, tmp_path: Path
):
    r = make_runner()
    result = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})

    assert hub.of("POST", "/api/rooms/eng/joins") == [{"handle": "scout"}]
    created = omnigent.created[0]
    assert created["agent_id"] == "ag-claude"
    assert created["host_id"] == "h1"
    assert created["workspace"] == str(tmp_path.resolve())
    assert created["labels"] == {"mycelium_room": "eng", "mycelium_handle": "scout"}
    assert created["terminal_launch_args"] == ["--allowedTools", "Bash(mycelium:*)"]
    assert "git" not in created

    intro = omnigent.said_to(result["pane"])[0]
    assert intro.index("mycelium join abcd-efgh-jkmn --hub http://hub:8000") < intro.index(
        "mycelium board --room eng"
    )
    agent = r.hello_body()["agents"][0]
    assert (agent["handle"], agent["pane"], agent["status"]) == ("scout", "conv_1", "running")


def test_in_a_repository_each_agent_gets_its_own_worktree(
    make_runner, omnigent: Omnigent, tmp_path: Path
):
    (tmp_path / ".git").mkdir()
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert omnigent.created[0]["git"] == {"branch_name": "mycelium/eng/scout"}
    assert r.hello_body()["agents"][0]["cwd"].endswith("/.worktrees/x")


def test_a_branch_name_is_always_a_valid_git_ref():
    assert branch_for("Q4 plans!", "@scout") == "mycelium/Q4-plans/scout"


def test_launching_a_running_agent_again_starts_nothing(make_runner, omnigent: Omnigent):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    again = r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    assert again == {"pane": "conv_1", "already": True}
    assert len(omnigent.created) == 1


def test_status_follows_the_session_and_stop_ends_it(make_runner, omnigent: Omnigent):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    omnigent.sessions["conv_1"]["status"] = "running"
    r.refresh()
    assert r.hello_body()["agents"][0]["status"] == "working"

    r.stop_agent({"room": "eng", "handle": "scout"})
    assert omnigent.events[-1] == ("conv_1", {"type": "stop_session", "data": {}})
    assert r.hello_body()["agents"][0]["status"] == "stopped"


def test_a_session_whose_runner_is_gone_is_a_stopped_agent(make_runner, omnigent: Omnigent):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    omnigent.sessions["conv_1"]["runner_online"] = False
    r.refresh()
    agent = r.hello_body()["agents"][0]
    assert (agent["status"], agent["detail"]) == ("stopped", "its Omnigent session ended")


def test_sync_pushes_presence_and_hands_each_wake_to_its_session(
    make_runner, omnigent: Omnigent, hub: Hub
):
    r = make_runner()
    r.launch({"room": "eng", "handle": "scout", "framework": "claude"})
    hub.wakes["eng"] = [
        {"handle": "scout", "reason": "turn"},
        {"handle": "not-ours", "reason": "mention"},
    ]
    r._sync_once()

    presence = hub.of("POST", "/api/rooms/eng/sessions/herdr-presence")[0]
    assert presence["statuses"] == {"scout": {"status": "running", "title": None}}
    said = omnigent.said_to("conv_1")
    assert len(said) == 2
    assert "mycelium await --room eng --handle scout" in said[1]


def test_a_swarm_is_refused_rather_than_started_somewhere_else(make_runner):
    r = make_runner()
    with pytest.raises(daemon.JobError, match="a swarm starts in herdr for now"):
        r.swarm({"room": "eng", "key": "k", "episode": "e", "task": "t", "team": []}, None)
