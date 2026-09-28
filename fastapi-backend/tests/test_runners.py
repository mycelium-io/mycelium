# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/runners: a machine dials in, the app queues work for it, the runner reports back.

Through the app, node-free: hello and heartbeat, the long-poll handing out jobs
in order, starting an agent (manifest and notes land before the job is queued),
the checks that refuse a launch before anything is written, and a swarm whose
members run on a machine.
"""

from __future__ import annotations

import asyncio

import pytest
import yaml

from app.services import runners
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file

ROOM = "general-engineering"
RUNNER = "julias-mbp"


@pytest.fixture(autouse=True)
def _fresh_registry():
    runners.registry.clear()
    yield
    runners.registry.clear()


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
async def room(client) -> str:
    resp = await client.post("/api/rooms", json={"name": ROOM, "is_public": True})
    assert resp.status_code in (200, 201), resp.text
    return ROOM


def hello(**over) -> dict:
    body = {
        "id": RUNNER,
        "label": "Julia's MacBook",
        "owner": "julia",
        "platform": "darwin-arm64",
        "version": "1.0.0",
        "herdr": True,
        "roots": ["/Users/julia/code"],
        "frameworks": [
            {
                "id": "claude",
                "name": "Claude Code",
                "command": "claude",
                "path": "/usr/local/bin/claude",
                "version": "2.1.0",
                "installed": True,
                "launchable": True,
            },
            {
                "id": "codex",
                "name": "Codex",
                "command": "codex",
                "installed": False,
                "launchable": True,
            },
        ],
        "agents": [],
    }
    body.update(over)
    return body


@pytest.fixture
async def runner(client) -> str:
    resp = await client.post("/api/runners", json=hello())
    assert resp.status_code == 200, resp.text
    return RUNNER


def _manifest(room: str, handle: str) -> dict:
    """The agent's manifest, or ``{}`` when the room has no such agent."""
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    return {} if found is None else yaml.safe_load(found[1])


@pytest.mark.asyncio
async def test_a_runner_says_hello_and_is_listed_connected(client, runner):
    listed = (await client.get("/api/runners")).json()
    assert [r["id"] for r in listed] == [RUNNER]
    assert listed[0]["connected"] is True
    assert listed[0]["frameworks"][0]["version"] == "2.1.0"

    # A heartbeat replaces what it said, keeping it one runner.
    await client.post("/api/runners", json=hello(herdr=False))
    assert (await client.get(f"/api/runners/{RUNNER}")).json()["herdr"] is False
    assert len((await client.get("/api/runners")).json()) == 1


@pytest.mark.asyncio
async def test_a_stale_runner_reads_as_disconnected_and_refuses_work(client, room, runner):
    entry = runners.registry._runners[RUNNER]
    entry.last_seen -= runners.STALE_AFTER * 2

    assert (await client.get(f"/api/runners/{RUNNER}")).json()["connected"] is False
    resp = await client.post(
        f"/api/runners/{RUNNER}/agents",
        json={"room": room, "handle": "scout", "framework": "claude"},
    )
    assert resp.status_code == 422
    assert "not connected" in resp.json()["detail"]
    assert _manifest(room, "scout") == {}


@pytest.mark.asyncio
async def test_launch_writes_the_agent_then_queues_the_job(client, room, runner):
    resp = await client.post(
        f"/api/runners/{RUNNER}/agents",
        json={
            "room": room,
            "handle": "@Scout",
            "framework": "claude",
            "instructions": "Read the board and take the oldest open task.",
            "cwd": "/Users/julia/code/api",
            "created_by": "julia",
        },
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["kind"] == "launch"
    assert job["status"] == "queued"
    assert job["spec"] == {
        "room": room,
        "handle": "scout",
        "framework": "claude",
        "cwd": "/Users/julia/code/api",
    }

    manifest = _manifest(room, "scout")
    assert manifest["adapter"] == "claude_code"
    assert manifest["runner"] == RUNNER
    assert manifest["framework"] == "claude"
    notes = read_memory_file(get_room_dir(room), "agents/scout/notes")
    assert notes is not None
    assert "oldest open task" in notes[1]

    agents = (await client.get(f"/api/rooms/{room}/agents")).json()
    scout = next(a for a in agents if a["handle"] == "scout")
    assert scout["runner"] == RUNNER
    assert scout["framework"] == "claude"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"framework": "codex"}, "not installed"),
        ({"framework": "claude", "cwd": "/etc"}, "outside the folders"),
        ({"framework": "claude", "cwd": "/Users/julia/code/../../etc"}, "'..'"),
        ({"framework": "claude", "handle": "Not A Slug"}, "lowercase slug"),
    ],
)
async def test_a_launch_the_runner_cannot_do_is_refused_before_anything_is_written(
    client, room, runner, body, said
):
    payload = {"room": room, "handle": "scout", **body}
    resp = await client.post(f"/api/runners/{RUNNER}/agents", json=payload)
    assert resp.status_code == 422
    assert said in resp.json()["detail"]
    assert _manifest(room, "scout") == {}
    assert (await client.get(f"/api/runners/{RUNNER}/jobs")).json() == []


@pytest.mark.asyncio
async def test_a_machine_without_herdr_starts_nothing(client, room):
    await client.post("/api/runners", json=hello(herdr=False))
    resp = await client.post(
        f"/api/runners/{RUNNER}/agents",
        json={"room": room, "handle": "scout", "framework": "claude"},
    )
    assert resp.status_code == 422
    assert "herdr" in resp.json()["detail"]
    assert _manifest(room, "scout") == {}

    swarm = await client.post(
        f"/api/rooms/{room}/swarms", json={"task": "x", "size": 2, "runner": RUNNER}
    )
    assert swarm.status_code == 422
    assert "herdr" in swarm.json()["detail"]


@pytest.mark.asyncio
async def test_a_framework_herdr_cannot_start_is_refused(client, room):
    aider = {
        "id": "aider",
        "name": "Aider",
        "command": "aider",
        "installed": True,
        "launchable": False,
        "note": "herdr has no aider kind",
    }
    await client.post("/api/runners", json=hello(frameworks=[aider]))
    resp = await client.post(
        f"/api/runners/{RUNNER}/agents",
        json={"room": room, "handle": "scout", "framework": "aider"},
    )
    assert resp.status_code == 422
    assert "herdr has no aider kind" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_handle_that_names_another_agent_is_refused(client, room, runner):
    await client.post(f"/api/rooms/{room}/engines", json={"handle": "aligner", "kind": "aligner"})
    resp = await client.post(
        f"/api/runners/{RUNNER}/agents",
        json={"room": room, "handle": "aligner", "framework": "claude"},
    )
    assert resp.status_code == 409
    assert _manifest(room, "aligner")["adapter"] == "engine"


@pytest.mark.asyncio
async def test_starting_an_agent_again_keeps_it_one_agent(client, room, runner):
    body = {"room": room, "handle": "scout", "framework": "claude"}
    assert (await client.post(f"/api/runners/{RUNNER}/agents", json=body)).status_code == 201
    assert (await client.post(f"/api/runners/{RUNNER}/agents", json=body)).status_code == 201
    keys = [k for k, _m, _c in list_memory_files(get_room_dir(room), prefix="agents/")]
    assert keys == ["agents/scout"]


@pytest.mark.asyncio
async def test_the_runner_takes_jobs_in_order_and_reports_them(client, room, runner):
    for handle in ("one", "two"):
        await client.post(
            f"/api/runners/{RUNNER}/agents",
            json={"room": room, "handle": handle, "framework": "claude"},
        )

    first = (await client.get(f"/api/runners/{RUNNER}/jobs/next?timeout=0")).json()
    second = (await client.get(f"/api/runners/{RUNNER}/jobs/next?timeout=0")).json()
    assert [first["spec"]["handle"], second["spec"]["handle"]] == ["one", "two"]
    assert first["status"] == "running"
    assert (await client.get(f"/api/runners/{RUNNER}/jobs/next?timeout=0")).status_code == 204

    done = await client.patch(
        f"/api/runners/{RUNNER}/jobs/{first['id']}",
        json={"status": "done", "result": {"pane": "w1-p1"}},
    )
    assert done.json()["status"] == "done"
    failed = await client.patch(
        f"/api/runners/{RUNNER}/jobs/{second['id']}",
        json={"status": "failed", "error": "claude exited at once"},
    )
    assert failed.json()["error"] == "claude exited at once"
    history = (await client.get(f"/api/runners/{RUNNER}/jobs")).json()
    assert [j["status"] for j in history] == ["failed", "done"]


@pytest.mark.asyncio
async def test_the_long_poll_wakes_when_a_job_is_queued(client, runner):
    waiting = asyncio.create_task(client.get(f"/api/runners/{RUNNER}/jobs/next?timeout=5"))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    queued = (await client.post(f"/api/runners/{RUNNER}/scan")).json()
    got = await asyncio.wait_for(waiting, timeout=2)
    assert got.json()["id"] == queued["id"]


@pytest.mark.asyncio
async def test_an_unknown_runner_polling_is_told_to_say_hello(client):
    resp = await client.get("/api/runners/nobody/jobs/next?timeout=0")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stop_names_an_agent_the_runner_runs(client, room, runner):
    missing = await client.post(f"/api/runners/{RUNNER}/agents/{room}/scout/stop")
    assert missing.status_code == 404

    running = {
        "handle": "scout",
        "room": room,
        "framework": "claude",
        "status": "idle",
        "pane": "w1-p2",
        "started_at": "2026-09-28T10:00:00Z",
    }
    await client.post("/api/runners", json=hello(agents=[running]))
    resp = await client.post(f"/api/runners/{RUNNER}/agents/{room}/scout/stop")
    assert resp.status_code == 201
    assert resp.json()["spec"] == {"room": room, "handle": "scout"}


@pytest.mark.asyncio
async def test_a_swarm_on_a_runner_queues_one_job_and_posts_no_kickoff(client, room, runner):
    from app.services import persister

    resp = await client.post(
        f"/api/rooms/{room}/swarms",
        json={
            "task": "Fix the flaky auth tests",
            "size": 2,
            "runner": RUNNER,
            "cwd": "/Users/julia/code/api",
            "worktree": True,
            "created_by": "julia",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["members"] == ["agent-1", "agent-2"]
    assert body["job"]

    assert _manifest(room, "conductor")["kind"] == "conductor"
    for handle in body["members"]:
        m = _manifest(room, handle)
        assert (m["runner"], m["framework"]) == (RUNNER, "claude")

    job = (await client.get(f"/api/runners/{RUNNER}/jobs/{body['job']}")).json()
    assert job["kind"] == "swarm"
    assert job["spec"]["team"] == ["agent-1", "agent-2"]
    assert job["spec"]["key"] == body["key"]
    assert job["spec"]["worktree"] is True
    # The runner posts the kickoff once its members are listening.
    said = [m for m in persister.prose_messages(room) if m.episode == body["episode"]]
    assert not any("@conductor" in (m.content or "") for m in said)


@pytest.mark.asyncio
async def test_a_swarm_on_a_runner_refuses_a_repository(client, room, runner):
    resp = await client.post(
        f"/api/rooms/{room}/swarms",
        json={"task": "x", "runner": RUNNER, "repo": "https://github.com/o/r"},
    )
    assert resp.status_code == 422
    assert "folder" in resp.json()["detail"]
