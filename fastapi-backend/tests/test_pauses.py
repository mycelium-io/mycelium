# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Pausing, resuming and stopping agents, for their owner.

A pause holds the agent's wakes and asks its machine to stop the turn and say
so; a resume hands it one wake with everything that arrived; a stop closes it.
Only the owner may do any of it, and "my agents" is every agent they own.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml

from app.schemas import (
    MachineAgentRead,
    MachineReportRead,
    MachineWorkspaceRead,
    RunnerAgentRead,
    RunnerHello,
)
from app.services import agent_control, interrupts, keeps, pauses, room_channels, wake_digest
from app.services.runners import RunnerRegistry

ROOM = "pause-room"
OTHER = "pause-other"
NOW = datetime(2026, 10, 18, 23, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
def runners(monkeypatch: pytest.MonkeyPatch) -> RunnerRegistry:
    """One connected machine running @coder in a herdr pane."""
    registry = RunnerRegistry()
    registry.hello(
        RunnerHello(
            id="mac",
            label="Julia's computer",
            agents=[
                RunnerAgentRead(
                    handle="coder",
                    room=ROOM,
                    framework="claude",
                    status="running",
                    pane="w1:p2",
                    started_at=NOW,
                )
            ],
        )
    )
    monkeypatch.setattr(interrupts, "registry", registry)
    monkeypatch.setattr(agent_control, "registry", registry)
    return registry


def _jobs(registry: RunnerRegistry) -> list[tuple[str, dict]]:
    return [(j.kind, j.spec) for j in registry.jobs("mac") or []]


async def _room(client, name: str, agents: dict[str, str | None]) -> None:
    resp = await client.post("/api/rooms", json={"name": name, "is_public": True})
    assert resp.status_code in (200, 201), resp.text
    items = [
        {
            "key": f"agents/{handle}",
            "value": yaml.safe_dump(
                {"adapter": "claude_code", "framework": "claude"}
                | ({"owner": owner} if owner else {})
            ),
            "created_by": "julia",
            "embed": False,
        }
        for handle, owner in agents.items()
    ]
    resp = await client.post(f"/api/rooms/{name}/memory", json={"items": items})
    assert resp.status_code in (200, 201), resp.text


@pytest.fixture
async def rooms(client) -> None:
    await _room(client, ROOM, {"coder": "julia", "scout": "sam", "loose": None})
    await _room(client, OTHER, {"reviewer": "julia"})


def _queue(room: str = ROOM) -> list[dict]:
    return room_channels.manager._herdr_wakes.get(room, [])


@pytest.mark.asyncio
async def test_a_pause_holds_wakes_and_asks_the_machine_to_stop_the_turn(client, rooms, runners):
    resp = await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paused"]["by"] == "julia"
    assert body["runner"] == "mac"
    assert _jobs(runners) == [
        ("pause", {"room": ROOM, "handle": "coder", "by": "julia", "pane": "w1:p2"})
    ]

    # Asked while paused, even idle: held, and never dropped for its age.
    manager = room_channels.manager
    manager.set_herdr_presence(ROOM, {"coder": "idle"})
    manager.enqueue_herdr_wake(ROOM, "coder", reason="mention", sender="sam")
    assert manager.drain_herdr_wakes(ROOM) == []
    assert manager.drain_herdr_wakes(ROOM, hold_ttl_s=0) == []
    assert [w["handle"] for w in _queue()] == ["coder"]

    # Pausing it again changes nothing and asks the machine nothing more.
    again = await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    assert again.json()["paused"]["at"] == body["paused"]["at"]
    assert len(_jobs(runners)) == 1

    members = (await client.get(f"/api/rooms/{ROOM}/sessions/members")).json()
    assert [(p["handle"], p["by"]) for p in members["paused"]] == [("coder", "julia")]


@pytest.mark.asyncio
async def test_a_resume_hands_over_one_wake_that_says_so(client, rooms, runners):
    manager = room_channels.manager
    await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    manager.set_herdr_presence(ROOM, {"coder": "idle"})
    manager.enqueue_herdr_wake(ROOM, "coder", reason="interrupt", sender="sam")

    resp = await client.post(f"/api/rooms/{ROOM}/agents/coder/resume", json={"by": "julia"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["paused"] is None
    assert not pauses.is_paused(ROOM, "coder")
    (wake,) = manager.drain_herdr_wakes(ROOM)
    # The resume outranks what was held, so the agent hears it was resumed.
    assert (wake["reason"], wake["from"]) == ("resumed", "julia")
    told = wake_digest.build(ROOM, wake, [])
    assert "@julia resumed you from Mycelium. Carry on where you stopped." in told


@pytest.mark.asyncio
async def test_an_interrupt_doesnt_reach_a_paused_agent(client, rooms, runners):
    manager = room_channels.manager
    await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    manager.set_herdr_presence(ROOM, {"coder": "working"})
    assert manager.ring_asked(ROOM, "coder", "interrupt", sender="sam")
    assert [k for k, _ in _jobs(runners)] == ["pause"]
    assert _queue()[0]["reason"] == "mention"


@pytest.mark.asyncio
async def test_only_the_owner_may_pause_resume_or_stop(client, rooms, runners):
    for verb in ("pause", "resume", "stop"):
        resp = await client.post(f"/api/rooms/{ROOM}/agents/coder/{verb}", json={"by": "sam"})
        assert resp.status_code == 403, resp.text
        assert "Only @julia" in resp.json()["detail"]
    assert _jobs(runners) == []
    missing = await client.post(f"/api/rooms/{ROOM}/agents/ghost/pause", json={"by": "julia"})
    assert missing.status_code == 404
    # One with no owner on record has nobody to protect it.
    loose = await client.post(f"/api/rooms/{ROOM}/agents/loose/pause", json={"by": "sam"})
    assert loose.status_code == 200, loose.text


@pytest.mark.asyncio
async def test_stop_asks_the_machine_and_ends_the_pause(client, rooms, runners):
    await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    resp = await client.post(f"/api/rooms/{ROOM}/agents/coder/stop", json={"by": "julia"})
    assert resp.status_code == 200, resp.text
    assert sorted(k for k, _ in _jobs(runners)) == ["pause", "stop"]
    assert not pauses.is_paused(ROOM, "coder")
    # Nobody owns @loose, so nobody may close its pane from here.
    loose = await client.post(f"/api/rooms/{ROOM}/agents/loose/stop", json={"by": "julia"})
    assert loose.status_code == 403
    assert "no owner on record" in loose.json()["detail"]
    # Nothing runs Julia's @reviewer in the other room, so there's nothing to stop.
    nothing = await client.post(f"/api/rooms/{OTHER}/agents/reviewer/stop", json={"by": "julia"})
    assert nothing.status_code == 409


@pytest.mark.asyncio
async def test_a_stop_keeps_the_pane_unless_told_to_close_it(client, rooms, runners):
    """A stop frees an agent's memory and keeps its pane for a start; ``close``
    is the stop for good."""
    await client.post(f"/api/rooms/{ROOM}/agents/coder/stop", json={"by": "julia"})
    await client.post(f"/api/rooms/{ROOM}/agents/coder/stop", json={"by": "julia", "close": True})
    # Newest first.
    assert [s["close"] for k, s in _jobs(runners) if k == "stop"] == [True, False]


@pytest.mark.asyncio
async def test_a_start_asks_the_machine_to_restart_it_and_only_its_owner_may(
    client, rooms, runners
):
    resp = await client.post(f"/api/rooms/{ROOM}/agents/coder/start", json={"by": "julia"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["runner"] == "mac"
    # The machine's own restart, which asks the person there first.
    assert _jobs(runners) == [
        ("restart", {"all": False, "agents": [{"handle": "coder", "room": ROOM}]})
    ]
    sam = await client.post(f"/api/rooms/{ROOM}/agents/coder/start", json={"by": "sam"})
    assert sam.status_code == 403
    loose = await client.post(f"/api/rooms/{ROOM}/agents/loose/start", json={"by": "julia"})
    assert loose.status_code == 403
    assert "can't be started from here" in loose.json()["detail"]
    nothing = await client.post(f"/api/rooms/{OTHER}/agents/reviewer/start", json={"by": "julia"})
    assert nothing.status_code == 409


@pytest.mark.asyncio
async def test_keep_marks_an_agent_for_its_owner(client, rooms, runners):
    on = await client.post(f"/api/rooms/{ROOM}/agents/coder/keep", json={"by": "julia"})
    assert (on.status_code, on.json()["keep"]) == (200, True)
    assert keeps.is_kept(ROOM, "coder")
    sam = await client.post(
        f"/api/rooms/{ROOM}/agents/coder/keep", json={"by": "sam", "keep": False}
    )
    assert sam.status_code == 403
    off = await client.post(
        f"/api/rooms/{ROOM}/agents/coder/keep", json={"by": "julia", "keep": False}
    )
    assert off.json()["keep"] is False
    assert not keeps.is_kept(ROOM, "coder")
    # Nothing on any machine was asked anything.
    assert _jobs(runners) == []


def _seen(handle: str, room: str, state: str, **more) -> MachineAgentRead:
    return MachineAgentRead.model_validate(
        {"handle": handle, "room": room, "pane": f"w1:{handle}", "state": state, **more}
    )


@pytest.mark.asyncio
async def test_running_lists_each_agent_from_its_machines_report(client, rooms, runners):
    runners.hello(
        RunnerHello(
            id="mac",
            label="Julia's computer",
            machine=MachineReportRead(
                machine="Julia's computer",
                workspaces=[
                    MachineWorkspaceRead(
                        id="w1",
                        label="pause-room",
                        room=ROOM,
                        agents=[
                            _seen("coder", ROOM, "idle"),
                            _seen("scout", ROOM, "working"),
                            _seen("loose", ROOM, "gone"),
                            _seen("reviewer", OTHER, "stopped", restartable=True),
                        ],
                    )
                ],
            ),
        )
    )
    await client.post(f"/api/rooms/{ROOM}/agents/coder/pause", json={"by": "julia"})
    await client.post(f"/api/rooms/{ROOM}/agents/coder/keep", json={"by": "julia"})

    room = (await client.get(f"/api/rooms/{ROOM}/agents/running")).json()
    # A closed pane has nothing to stop or start.
    assert [(a["handle"], a["state"]) for a in room["agents"]] == [
        ("coder", "paused"),
        ("scout", "working"),
    ]
    coder = room["agents"][0]
    assert (coder["owner"], coder["keep"], coder["machine"]) == ("julia", True, "Julia's computer")

    # Julia's own, across rooms: not Sam's @scout, and her stopped @reviewer too.
    mine = (await client.get("/api/agents/running", params={"owner": "julia"})).json()
    assert sorted((a["room"], a["handle"], a["state"]) for a in mine["agents"]) == [
        (OTHER, "reviewer", "stopped"),
        (ROOM, "coder", "paused"),
    ]


def test_what_an_agent_uses_has_nowhere_to_go_on_the_hub():
    """Memory, CPU and processes stay on the agent's machine: a report that
    carried them anyway keeps none of it."""
    seen = _seen("coder", ROOM, "idle", ram_mb=900, cpu=4.0, processes=[{"name": "claude"}])
    kept = seen.model_dump()
    assert not {"ram_mb", "cpu", "processes", "idle_since"} & kept.keys()


def test_a_keep_follows_a_rename_and_goes_with_its_room():
    keeps.keep("r", "old", "julia")
    keeps.rename("r", "old", "new")
    assert keeps.kept_in("r").keys() == {"new"}
    keeps.forget_room("r")
    assert keeps.kept_in("r") == {}


def test_an_owner_of_unknown_is_no_owner(monkeypatch: pytest.MonkeyPatch):
    from app.schemas import AgentRead

    agents = [AgentRead(handle="voice", adapter="claude_code", owner="unknown")]
    monkeypatch.setattr(agent_control, "room_agents", lambda _room: agents)
    assert agent_control.owner_of("r", "voice") == (True, None)
    agent_control.check("r", "voice", "sam")  # anyone may pause it
    with pytest.raises(agent_control.ControlError, match="no owner on record"):
        agent_control.check("r", "voice", "julia", "stop")
    monkeypatch.setattr(agent_control, "list_room_names", lambda: ["r"])
    assert agent_control.owned_by("unknown") == []


@pytest.mark.asyncio
async def test_pause_and_resume_all_of_my_agents(client, rooms, runners):
    resp = await client.post("/api/agents/pause", json={"by": "julia"})
    assert resp.status_code == 200, resp.text
    paused = sorted((a["room"], a["handle"]) for a in resp.json()["agents"])
    # Julia's agents in every room, and nobody else's.
    assert paused == [(OTHER, "reviewer"), (ROOM, "coder")]
    assert not pauses.is_paused(ROOM, "scout")

    listed = (await client.get("/api/agents/paused", params={"owner": "julia"})).json()
    assert sorted(p["handle"] for p in listed) == ["coder", "reviewer"]

    resumed = await client.post("/api/agents/resume", json={"by": "julia", "room": ROOM})
    assert [a["handle"] for a in resumed.json()["agents"]] == ["coder"]
    assert pauses.is_paused(OTHER, "reviewer")
    assert not pauses.is_paused(ROOM, "coder")


def test_a_pause_survives_a_restart_and_follows_a_rename():
    pauses.pause("r", "coder", "julia")
    # Read back from the file, as a restarted hub would.
    assert pauses.get("r", "coder")["by"] == "julia"  # type: ignore[index]
    pauses.rename("r", "coder", "builder")
    assert pauses.get("r", "coder") is None
    assert pauses.is_paused("r", "builder")
    pauses.forget_room("r")
    assert pauses.paused_in("r") == {}
