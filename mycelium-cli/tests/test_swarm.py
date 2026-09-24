# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium swarm``: a team on one task, from one argument.

No hub and no herdr: the hub is an ``httpx.MockTransport`` and herdr a scripted
runner, so these hold what the command asks of each — the room, the conductor
and the task it sets up and the kickoff it posts; the panes it opens, each set
up as its own handle; the brief each local member gets — and how the live view
reads the room's stream.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from mycelium.commands import swarm
from mycelium.commands.herdr import wake_prompt_for
from mycelium.config import SwarmConfig
from mycelium.integrations.herdr import HerdrBridge, HerdrError

if TYPE_CHECKING:
    from pathlib import Path

    from mycelium.config import MyceliumConfig


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["herdr"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _ok(result: dict) -> str:
    return json.dumps({"id": "cli:test", "result": result})


class Herdr:
    """A herdr CLI stand-in that opens workspaces and splits panes, numbering them."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._panes = 0

    def _pane(self) -> str:
        self._panes += 1
        return f"w9:p{self._panes}"

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        head = " ".join(args[:2])
        if head == "workspace create":
            return _proc(
                _ok(
                    {
                        "type": "workspace_created",
                        "workspace": {"workspace_id": "w9"},
                        "root_pane": {"pane_id": self._pane()},
                    }
                )
            )
        if head == "pane split":
            return _proc(_ok({"type": "pane_info", "pane": {"pane_id": self._pane()}}))
        if head in {"agent start", "agent prompt"}:
            return _proc(_ok({"type": "ok"}))
        return _proc(stderr=_ok({}), returncode=2)

    def of(self, head: str) -> list[list[str]]:
        return [c for c in self.calls if " ".join(c[:2]) == head]


# ── defaults ──────────────────────────────────────────────────────────────────


def test_the_sender_is_the_identity_else_the_login_name(monkeypatch: pytest.MonkeyPatch):
    class _Cfg:
        def __init__(self, me: str) -> None:
            self._me = me

        def get_current_identity(self) -> str:
            return self._me

    assert swarm.sender_of(cast("MyceliumConfig", _Cfg("julia"))) == "julia"
    monkeypatch.setattr("getpass.getuser", lambda: "Julia.Valenti")
    assert swarm.sender_of(cast("MyceliumConfig", _Cfg("unknown"))) == "julia-valenti"


def test_the_team_is_numbered():
    assert swarm.team_handles(3) == ["agent-1", "agent-2", "agent-3"]


class _SavedConfig:
    """The slice of config pick_kind reads and writes."""

    def __init__(self, agent: str | None = None) -> None:
        self.swarm = SwarmConfig(agent=agent)
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


def test_the_agent_cli_is_the_one_named_else_the_configured_one():
    cfg = _SavedConfig("agent-x")
    assert swarm.pick_kind("agent-y", cast("MyceliumConfig", cfg), ask=False) == "agent-y"
    assert swarm.pick_kind(None, cast("MyceliumConfig", cfg), ask=False) == "agent-x"


def test_nothing_is_guessed_from_what_is_installed(monkeypatch: pytest.MonkeyPatch):
    # Every CLI on the PATH, and still no pick without being told.
    monkeypatch.setattr(swarm.shutil, "which", lambda exe: exe)
    cfg = _SavedConfig()
    assert swarm.pick_kind(None, cast("MyceliumConfig", cfg), ask=False) is None
    assert cfg.saves == 0


def test_the_agent_cli_is_asked_once_and_saved(monkeypatch: pytest.MonkeyPatch):
    answers = iter(["not-installed", "agent-x"])
    monkeypatch.setattr(swarm.typer, "prompt", lambda *_a, **_k: next(answers))
    monkeypatch.setattr(swarm.shutil, "which", lambda exe: exe if exe == "agent-x" else None)
    cfg = _SavedConfig()

    assert swarm.pick_kind(None, cast("MyceliumConfig", cfg), ask=True) == "agent-x"
    assert cfg.swarm.agent == "agent-x"
    assert cfg.saves == 1


def test_the_brief_says_who_you_are_and_how_the_team_works():
    brief = swarm.kickoff_brief(
        "fix-tests", "agent-2", ["agent-1", "agent-2", "agent-3"], "work/fix", "Fix the tests"
    )
    assert brief.startswith("# You are @agent-2")
    assert "with @agent-1, @agent-3" in brief
    assert "> Fix the tests" in brief
    assert "MYCELIUM_AGENT_HANDLE=agent-2" in brief
    assert "mycelium await --handle agent-2" in brief
    assert "--parent work/fix --assign @<member>" in brief
    assert "asks @agent-1 to split the work" in brief


# ── the hub ───────────────────────────────────────────────────────────────────


def _hub(existing_room: bool = False) -> tuple[httpx.Client, list[tuple[str, str, Any]]]:
    seen: list[tuple[str, str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        path = request.url.path
        if request.method == "GET" and path == "/api/rooms/fix-tests":
            return httpx.Response(200 if existing_room else 404, json={})
        if path == "/api/rooms":
            return httpx.Response(201, json={"name": "fix-tests"})
        if path.endswith("/engines"):
            code = 409 if body and body["handle"] == "conductor" else 201
            return httpx.Response(code, json={})
        if path.endswith("/tasks"):
            return httpx.Response(
                201, json={"key": "work/fix-the-tests", "episode": "urn:ep:fix-tests:t1"}
            )
        if path.endswith(("/messages", "/memory")):
            return httpx.Response(201, json={})
        return httpx.Response(500, text="unexpected")

    client = httpx.Client(base_url="http://hub", transport=httpx.MockTransport(handle))
    return client, seen


def test_a_swarm_joins_a_room_and_never_makes_one():
    client, seen = _hub(existing_room=True)
    swarm.require_room(client, "fix-tests")
    swarm.ensure_engine(client, "fix-tests", "conductor", "conductor", "julia")
    assert not any(path == "/api/rooms" for _m, path, _b in seen)
    assert seen[-1][2] == {"handle": "conductor", "kind": "conductor", "created_by": "julia"}

    client, seen = _hub()
    with pytest.raises(swarm.SwarmError, match="no room named fix-tests"):
        swarm.require_room(client, "fix-tests")
    assert [m for m, _p, _b in seen] == ["GET"]


def test_the_kickoff_summons_the_conductor_in_the_tasks_thread():
    client, seen = _hub()
    key, episode = swarm.file_task(client, "fix-tests", "Fix the tests", "julia")
    assert (key, episode) == ("work/fix-the-tests", "urn:ep:fix-tests:t1")

    swarm.kick_off(client, "fix-tests", episode, ["agent-1", "agent-2"], "Fix the tests", "julia")

    _m, path, body = seen[-1]
    assert path == "/api/rooms/fix-tests/messages"
    assert body["episode"] == episode
    assert body["content"] == "@conductor swarm @agent-1 @agent-2: Fix the tests"


def test_a_refusal_from_the_hub_is_a_swarm_error():
    client = httpx.Client(
        base_url="http://hub",
        transport=httpx.MockTransport(lambda _r: httpx.Response(403, text="not yours")),
    )
    with pytest.raises(swarm.SwarmError, match="not yours"):
        swarm.file_task(client, "r", "t", "julia")


# ── local members, in herdr ───────────────────────────────────────────────────


def test_the_bridge_reads_back_what_herdr_made(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    herdr = Herdr()
    bridge = HerdrBridge(runner=herdr)

    assert bridge.create_workspace("room", cwd="/repo", env={"A": "1"}) == ("w9", "w9:p1")
    assert bridge.split_pane("w9:p1", direction="down", env={"B": "2"}) == "w9:p2"
    assert herdr.calls[0] == [
        "workspace",
        "create",
        "--label",
        "room",
        "--no-focus",
        "--cwd",
        "/repo",
        "--env",
        "A=1",
    ]
    assert herdr.calls[1][:5] == ["pane", "split", "w9:p1", "--direction", "down"]
    assert herdr.calls[1][-2:] == ["--env", "B=2"]

    bridge = HerdrBridge(runner=lambda _a: _proc(_ok({"workspace": {}})))
    with pytest.raises(HerdrError):
        bridge.create_workspace("room")


def test_each_member_gets_a_pane_an_agent_and_its_own_identity(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    written: list[str] = []

    class _Manifest:
        def __init__(self, handle: str) -> None:
            self.handle = handle

    class _Impl:
        def build_manifest(self, *, handle: str, **_: object) -> _Manifest:
            return _Manifest(handle)

    monkeypatch.setattr("mycelium.integrations.get_integration", lambda *_a, **_k: _Impl())
    monkeypatch.setattr(
        "mycelium.commands.agent._write_manifest",
        lambda config, room, manifest, created_by: written.append(manifest.handle),
    )
    monkeypatch.setenv("MYCELIUM_API_URL", "http://127.0.0.1:8000")
    herdr = Herdr()
    bridge = HerdrBridge(runner=herdr)

    local = swarm.start_local(
        cast("MyceliumConfig", object()),
        bridge,
        "fix-tests",
        ["agent-1", "agent-2", "agent-3"],
        kind="claude",
        cwd=isolated_home,
        worktree=False,
        me="julia",
    )

    assert local.workspace == "w9"
    assert local.panes == {"agent-1": "w9:p1", "agent-2": "w9:p2", "agent-3": "w9:p3"}
    # Every pane's shell is the member it plays, in the room it plays it in,
    # against the hub swarm itself was pointed at.
    envs = [c for call in herdr.calls for c in call if c.startswith("MYCELIUM_")]
    assert envs == [
        f"{var}={value}"
        for h in ("agent-1", "agent-2", "agent-3")
        for var, value in (
            ("MYCELIUM_API_URL", "http://127.0.0.1:8000"),
            ("MYCELIUM_AGENT_HANDLE", h),
            ("MYCELIUM_ROOM_ID", "fix-tests"),
        )
    ]
    assert [c[2:6] for c in herdr.of("agent start")] == [
        ["agent-1", "--kind", "claude", "--pane"],
        ["agent-2", "--kind", "claude", "--pane"],
        ["agent-3", "--kind", "claude", "--pane"],
    ]
    # Each Claude session may run mycelium without a prompt, and only this one:
    # the grant rides the command line, not the user's settings.
    assert all(
        c[-3:] == ["--", "--allowedTools", "Bash(mycelium:*)"] for c in herdr.of("agent start")
    )
    assert written == ["agent-1", "agent-2", "agent-3"]
    mapping = bridge.registry.get("fix-tests", "agent-2")
    assert mapping is not None
    assert (mapping.pane, mapping.managed) == ("w9:p2", True)
    assert bridge.registry.bindings() == {"w9": "fix-tests"}


def test_each_local_member_is_handed_its_brief_through_the_room(
    monkeypatch: pytest.MonkeyPatch,
):
    # The brief is a room memory, read with the one command a member may run
    # without asking; a file outside its checkout would stop it at a prompt.
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    herdr = Herdr()
    client, seen = _hub()
    local = swarm.LocalTeam(workspace="w9", panes={"agent-1": "w9:p1", "agent-2": "w9:p2"})

    swarm.brief_local(
        client, HerdrBridge(runner=herdr), "fix-tests", local, "work/fix", "Fix it", "julia"
    )

    _m, path, body = seen[-1]
    assert path == "/api/rooms/fix-tests/memory"
    assert [i["key"] for i in body["items"]] == ["agents/agent-1/notes", "agents/agent-2/notes"]
    assert body["items"][1]["value"].startswith("# You are @agent-2")
    prompts = herdr.of("agent prompt")
    assert [p[2] for p in prompts] == ["w9:p1", "w9:p2"]
    assert "You are @agent-2 on a team of 2" in prompts[1][3]
    assert "`mycelium memory get agents/agent-2/notes`" in prompts[1][3]


def test_a_wake_is_worded_by_why_it_was_queued():
    turn = wake_prompt_for("r", {"handle": "agent-1", "reason": "turn"})
    assert "mycelium await --room r --handle agent-1" in turn
    assigned = wake_prompt_for(
        "r", {"handle": "agent-2", "reason": "assigned", "key": "work/x", "title": "Do X"}
    )
    assert "'Do X' (work/x)" in assigned
    assert "board claim work/x --room r --to @agent-2" in assigned
    mention = wake_prompt_for("r", {"handle": "agent-3"})
    assert "room messages --room r" in mention


# ── the live view ─────────────────────────────────────────────────────────────


def _frame(sender: str, *, text: str = "", episode: str | None = None, payload=None) -> dict:
    content: dict[str, Any] = {"l9": {"payload": payload or {"type": "reply", "data": {}}}}
    if text:
        content["content"] = text
    return {
        "message_type": "l9_exchange",
        "sender_handle": sender,
        "episode": episode,
        "content": json.dumps(content),
    }


def _notice(**data: str) -> dict:
    return _frame("system", payload={"type": "notice", "data": data})


def test_the_view_shows_the_conversation_across_the_task_and_its_children():
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix the tests")

    turn = {
        "event": "turn",
        "protocol": "swarm",
        "step": "check-in",
        "to": "agent-1",
        "turn": 1,
        "cap": 4,
    }
    step = view.render(
        _frame(
            "conductor",
            text="swarm · check-in · turn 1 of 4 · agent-1\n\nThe team is…",
            episode="ep-root",
            payload={"type": "message", "data": {"conductor": turn}},
        )
    )
    assert step is not None
    # Drawn from the post's line, not its prose: the prompt stays out of view.
    assert "check-in → agent-1 · turn 1 of 4" in step
    assert "The team is" not in step
    said = view.render(_frame("agent-1", text="Here. I'll take the repro.", episode="ep-root"))
    assert said is not None
    assert "agent-1" in said and "Fix the tests" in said and "I'll take the repro." in said

    filed = view.render(
        _notice(
            subkind="filed",
            key="work/repro",
            title="Reproduce it",
            by="agent-1",
            episode="ep-child",
            **{"for": "agent-2"},
        )
    )
    assert filed is not None
    assert "filed" in filed and "Reproduce it" in filed and "agent-2" in filed
    child = view.render(_frame("agent-2", text="Seed 4412 fails.", episode="ep-child"))
    assert child is not None and "Reproduce it" in child

    claimed = view.render(
        _notice(subkind="claimed", key="work/repro", title="Reproduce it", by="agent-2")
    )
    assert claimed is not None and "took" in claimed


def test_the_view_hides_pings_and_ends_when_the_task_resolves():
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    assert view.render(_frame("agent-1", payload={"type": "ping", "data": {}})) is None
    assert view.render({"message_type": "coordination_join", "content": "{}"}) is None
    assert view.render(_notice(subkind="resolved", key="work/repro", title="Repro")) is not None
    assert not view.done.is_set()
    assert view.render(_notice(subkind="resolved", key="work/fix", title="Fix")) is not None
    assert view.done.is_set()


def test_what_an_agent_writes_is_never_read_as_markup():
    from rich.console import Console

    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix [it]")
    line = view.render(
        _frame(
            "agent-1", text="Fill in [Agent-2: build command] and [/bold] here", episode="ep-root"
        )
    )
    assert line is not None
    out = Console(width=200, record=True)
    out.print(line)
    printed = out.export_text()
    assert "[Agent-2: build command]" in printed
    assert "[/bold]" in printed
    assert "Fix [it]" in printed


def test_a_long_message_is_cut_short_with_where_to_read_the_rest():
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    view.render(
        _notice(subkind="filed", key="work/draft", title="Draft", by="agent-1", episode="ep-d")
    )
    long = "\n".join(f"line {i}" for i in range(1, 11))
    line = view.render(_frame("agent-1", text=long, episode="ep-d"))
    assert line is not None
    assert "line 6" in line and "line 7" not in line
    assert "4 more lines · board messages work/draft" in line


def test_the_kickoff_is_one_line_and_the_last_word_in_the_task_is_kept():
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    kick = view.render(
        _frame("julia", text="@conductor swarm @agent-1 @agent-2: fix it", episode="ep-root")
    )
    assert kick is not None and "kicked off the team" in kick
    view.render(_frame("agent-2", text="a child's message", episode="ep-child"))
    view.render(_frame("agent-1", text="# The result\n\nAll of it.", episode="ep-root"))
    assert view.last_root == ("agent-1", "# The result\n\nAll of it.")


def test_an_agent_is_started_again_while_its_pane_comes_up(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(swarm, "START_RETRY_S", 0)
    attempts: list[str] = []

    class _Bridge:
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            if len(attempts) < 2:
                raise HerdrError("pane is not at a shell prompt")
            return {}

    swarm._start_when_ready(_Bridge(), "agent-1", "claude", "w9:p1")
    assert attempts == ["w9:p1", "w9:p1"]

    attempts.clear()

    class _Never(_Bridge):
        def start_agent(self, handle: str, kind: str, pane: str, **_: object) -> dict:
            attempts.append(pane)
            raise HerdrError("still not ready")

    with pytest.raises(HerdrError):
        swarm._start_when_ready(_Never(), "agent-1", "claude", "w9:p1")
    assert len(attempts) == swarm.START_ATTEMPTS


def test_an_older_hub_without_the_conductor_says_what_to_do():
    client = httpx.Client(
        base_url="http://hub",
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(422, text="Unknown engine kind 'conductor'; known: [...]")
        ),
    )
    with pytest.raises(swarm.SwarmError, match="mycelium upgrade"):
        swarm.ensure_engine(client, "r", "conductor", "conductor", "julia")


def _swarms_hub(response: httpx.Response) -> tuple[httpx.Client, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/api/rooms/r"
            return httpx.Response(200, json={"name": "r"})
        assert (request.method, request.url.path) == ("POST", "/api/rooms/r/swarms")
        sent.append(json.loads(request.content))
        return response

    return httpx.Client(base_url="http://hub", transport=httpx.MockTransport(handle)), sent


def test_a_hub_team_is_set_up_by_the_hub_and_kicked_off_by_the_view():
    client, sent = _swarms_hub(
        httpx.Response(201, json={"room": "r", "key": "work/x", "episode": "urn:ep:r:t1"})
    )

    got = swarm.start_on_hub(client, "Add a health check", 3, "r", "julia", "git@host:org/api")

    assert got == ("work/x", "urn:ep:r:t1")
    assert sent == [
        {
            "task": "Add a health check",
            "size": 3,
            "created_by": "julia",
            "kickoff": False,
            "repo": "git@host:org/api",
        }
    ]


def test_a_repository_the_hub_cannot_clone_is_said_plainly():
    client, _sent = _swarms_hub(
        httpx.Response(422, json={"detail": "git clone failed: repository not found"})
    )
    with pytest.raises(swarm.SwarmError, match="^git clone failed: repository not found$"):
        swarm.start_on_hub(client, "t", 3, "r", "julia", "https://x/y")


def test_an_older_hub_without_the_swarm_route_says_what_to_do():
    client, _sent = _swarms_hub(httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(swarm.SwarmError, match="drop --server"):
        swarm.start_on_hub(client, "t", 3, "r", "julia")


def test_the_view_knows_how_long_the_room_has_been_quiet(monkeypatch: pytest.MonkeyPatch):
    clock = [1000.0]
    monkeypatch.setattr(swarm.time, "monotonic", lambda: clock[0])
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    clock[0] += 200
    assert view.quiet_for() == 200
    # A ping is not something the view shows, so it does not count as movement.
    view.render(_frame("agent-1", payload={"type": "ping", "data": {}}))
    assert view.quiet_for() == 200
    view.render(_frame("agent-1", text="Still on it.", episode="ep-root"))
    assert view.quiet_for() == 0


def test_a_dropped_stream_ends_the_watch_quietly(monkeypatch: pytest.MonkeyPatch):
    import threading

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("hub went away")

    monkeypatch.setattr(
        swarm,
        "hub_client",
        lambda *_a, **_k: httpx.Client(
            base_url="http://hub", transport=httpx.MockTransport(refuse)
        ),
    )
    view = swarm.LiveView(root_key="work/fix", root_episode="ep-root", root_title="Fix")
    connected = threading.Event()

    swarm.watch(cast("MyceliumConfig", object()), "r", view, connected)

    assert connected.is_set()
    assert not view.done.is_set()


def test_the_result_is_written_into_the_tasks_row():
    client, seen = _hub()
    swarm.record_result(
        client, "fix-tests", "work/fix", "Fix the tests", "# Result\n\nAll green.\n", "agent-1"
    )
    _m, path, body = seen[-1]
    assert path == "/api/rooms/fix-tests/memory"
    assert body["items"] == [
        {
            "key": "work/fix",
            "value": "Fix the tests\n\n# Result\n\nAll green.",
            "created_by": "agent-1",
        }
    ]


def test_each_conductor_line_is_said_in_a_few_words():
    assert (
        swarm.describe_line(
            {
                "event": "open",
                "protocol": "swarm",
                "roles": {"lead": "agent-1"},
                "members": ["agent-2", "agent-3"],
                "steps": [],
            }
        )
        == "Running swarm · agent-1 as lead · agent-2, agent-3"
    )
    assert (
        swarm.describe_line(
            {"event": "edge", "step": "review", "who": "sec", "stance": "reject", "next": "propose"}
        )
        == "review: sec blocked, on to propose"
    )
    assert (
        swarm.describe_line(
            {"event": "close", "protocol": "swarm", "outcome": "resolved", "steps": 2, "reason": ""}
        )
        == "swarm done · 2 steps"
    )
