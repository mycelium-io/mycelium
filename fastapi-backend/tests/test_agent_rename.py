# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Renaming an agent: its manifest, notes, tasks, presence and read position
move to the new handle, and the room is told."""

from __future__ import annotations

import pytest
import yaml

from app.services import room_channels
from app.services.filesystem import get_room_dir, read_memory_file
from app.services.persister import load_cursors, write_cursors

ROOM = "rename-room"


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
async def room(client) -> str:
    resp = await client.post("/api/rooms", json={"name": ROOM, "is_public": True})
    assert resp.status_code in (200, 201), resp.text
    manifest = yaml.safe_dump({"adapter": "claude_code", "framework": "claude", "owner": "julia"})
    items = [
        {"key": "agents/voice-model", "value": manifest, "created_by": "julia", "embed": False},
        {
            "key": "agents/voice-model/notes",
            "value": "Own the voice work.",
            "created_by": "julia",
            "embed": False,
        },
    ]
    resp = await client.post(f"/api/rooms/{ROOM}/memory", json={"items": items})
    assert resp.status_code in (200, 201), resp.text
    return ROOM


def _memory(key: str) -> tuple[dict, str] | None:
    return read_memory_file(get_room_dir(ROOM), key)


def _held(key: str) -> tuple[dict, str]:
    """The memory at ``key``, which the test expects to be there."""
    found = _memory(key)
    assert found is not None, key
    return found


async def _rename(client, to: str, old: str = "voice-model", by: str | None = "julia"):
    return await client.post(f"/api/rooms/{ROOM}/agents/{old}/rename", json={"to": to, "by": by})


@pytest.mark.asyncio
async def test_a_rename_moves_the_agent_and_its_notes(client, room):
    resp = await _rename(client, "docs-writer")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["handle"] == "docs-writer"
    assert body["was"] == "voice-model"
    assert sorted(body["memories"]) == ["agents/docs-writer", "agents/docs-writer/notes"]

    assert _memory("agents/voice-model") is None
    assert _memory("agents/voice-model/notes") is None
    manifest = yaml.safe_load(_held("agents/docs-writer")[1])
    assert manifest == {"adapter": "claude_code", "framework": "claude", "owner": "julia"}
    assert _held("agents/docs-writer/notes")[1].strip() == "Own the voice work."

    listed = {a["handle"] for a in (await client.get(f"/api/rooms/{ROOM}/agents")).json()}
    assert listed == {"docs-writer"}
    # No machine has it, so nothing is restarted.
    assert body["restart_runner"] is None
    assert body["restart_job"] is None


@pytest.mark.asyncio
async def test_the_tasks_it_is_meant_for_or_holding_name_it_now(client, room):
    keys = []
    for title, assignee in (("Ship the voice demo", "voice-model"), ("Someone else's", "hay")):
        resp = await client.post(
            f"/api/rooms/{ROOM}/tasks",
            json={"title": title, "handle": "julia", "assignee": assignee},
        )
        assert resp.status_code == 201, resp.text
        keys.append(resp.json()["key"])
    mine, theirs = keys
    resp = await client.post(
        f"/api/rooms/{ROOM}/assignments/claim", json={"key": mine, "handle": "voice-model"}
    )
    assert resp.status_code == 200, resp.text

    resp = await _rename(client, "docs-writer")
    assert resp.json()["rows"] == [mine]
    meta, _ = _held(mine)
    assert meta["assignee"].lstrip("@") == "docs-writer"
    assert meta["owner"] == "@docs-writer"
    assert _held(theirs)[0]["assignee"] == "hay"


@pytest.mark.asyncio
async def test_the_room_is_told_by_whoever_renamed_it(client, room):
    await _rename(client, "docs-writer")
    messages = (await client.get(f"/api/rooms/{ROOM}/messages")).json()
    said = messages["messages"] if isinstance(messages, dict) else messages
    told = [m for m in said if "you're @docs-writer now" in (m.get("content") or "")]
    assert told, said
    assert told[0]["sender_handle"] == "julia"
    assert told[0]["content"] == (
        "@docs-writer: you're @docs-writer now, renamed from voice-model. "
        "Your notes are at `agents/docs-writer/notes`."
    )


@pytest.mark.asyncio
async def test_its_presence_and_read_position_move(client, room):
    manager = room_channels.manager
    manager.set_herdr_presence(ROOM, {"voice-model": "idle"})
    write_cursors(ROOM, {"voice-model": 7, "hay": 3})

    await _rename(client, "docs-writer")
    assert manager.herdr_status(ROOM, "docs-writer") == "idle"
    assert manager.herdr_status(ROOM, "voice-model") is None
    assert "voice-model" not in load_cursors(ROOM)


def test_a_read_position_is_carried_to_the_new_handle():
    from app.services.persister import DeliveryLog, EpisodeCursors, rename_positions

    assert rename_positions({"voice-model": 7, "hay": 3}, "voice-model", "docs") == {
        "hay": 3,
        "docs": 7,
    }
    # The further one wins, so a rename never re-serves what either had read.
    assert rename_positions({"voice-model": 2, "docs": 5}, "voice-model", "docs") == {"docs": 5}
    assert rename_positions({"hay": 3}, "voice-model", "docs") == {"hay": 3}

    log = DeliveryLog(cursors={"voice-model": 0})
    log.rename("voice-model", "docs")
    assert log.cursors == {"docs": 0}
    threads = EpisodeCursors({"ep": {"voice-model": 4}})
    threads.rename("voice-model", "docs")
    assert threads.snapshot == {"ep": {"docs": 4}}


def _machine_with(handle: str) -> dict:
    """A runner whose machine has ``handle`` in a herdr pane in the room."""
    return {
        "id": "julias-mbp",
        "label": "Julia's MacBook",
        "owner": "julia",
        "platform": "darwin-arm64",
        "version": "1.0.0",
        "herdr": True,
        "roots": ["/Users/julia/code"],
        "frameworks": [],
        "agents": [],
        "machine": {
            "machine": "julias-mbp",
            "workspaces": [
                {
                    "id": "w5",
                    "label": "rename-room",
                    "room": ROOM,
                    "agents": [{"handle": handle, "room": ROOM, "pane": "w5:p3", "state": "idle"}],
                }
            ],
        },
    }


@pytest.fixture
async def machine(client):
    """A connected machine running @voice-model in a herdr pane."""
    from app.services import runners

    runners.registry.clear()
    assert (await client.post("/api/runners", json=_machine_with("voice-model"))).status_code == 200
    yield "julias-mbp"
    runners.registry.clear()


async def _told(client) -> list[dict]:
    messages = (await client.get(f"/api/rooms/{ROOM}/messages")).json()
    said = messages["messages"] if isinstance(messages, dict) else messages
    return [m for m in said if "you're @docs-writer now" in (m.get("content") or "")]


async def _report(client, job: str, status: str, **body) -> dict:
    resp = await client.patch(
        f"/api/runners/julias-mbp/jobs/{job}", json={"status": status, **body}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_nothing_changes_until_the_machine_running_it_says_yes(client, room, machine):
    body = (await _rename(client, "docs-writer")).json()
    assert body["pending"] is True
    assert body["memories"] == []
    assert body["restart_runner"] == machine
    job = (await client.get(f"/api/runners/{machine}/jobs/{body['restart_job']}")).json()
    assert job["kind"] == "rename"
    assert job["spec"] == {
        "room": ROOM,
        "handle": "voice-model",
        "to": "docs-writer",
        "by": "julia",
    }

    # Queued and asked: still @voice-model, and the room hasn't been told.
    await _report(client, job["id"], "waiting")
    assert _memory("agents/voice-model") is not None
    assert _memory("agents/docs-writer") is None
    assert await _told(client) == []

    # The yes: the runner reports it running, and the hub renames it before the restart.
    answered = await _report(client, job["id"], "running")
    assert answered["status"] == "running"
    assert _memory("agents/voice-model") is None
    assert _memory("agents/docs-writer") is not None
    assert len(await _told(client)) == 1

    # Reported again (the restart done), it isn't renamed twice.
    await _report(client, job["id"], "done", result={"handle": "docs-writer"})
    assert len(await _told(client)) == 1


@pytest.mark.asyncio
async def test_a_declined_rename_changes_nothing(client, room, machine):
    body = (await _rename(client, "docs-writer")).json()
    await _report(client, body["restart_job"], "waiting")
    await _report(client, body["restart_job"], "failed", error="Declined on julias-mbp.")
    assert _memory("agents/voice-model") is not None
    assert _memory("agents/docs-writer") is None
    assert await _told(client) == []


@pytest.mark.asyncio
async def test_a_name_taken_while_it_waited_fails_the_rename(client, room, machine):
    body = (await _rename(client, "docs-writer")).json()
    other = yaml.safe_dump({"adapter": "claude_code"})
    await client.post(
        f"/api/rooms/{ROOM}/memory",
        json={
            "items": [
                {"key": "agents/docs-writer", "value": other, "created_by": "hay", "embed": False}
            ]
        },
    )
    answered = await _report(client, body["restart_job"], "running")
    # Failed, so the runner restarts nothing, and @voice-model is as it was.
    assert answered["status"] == "failed"
    assert answered["error"] == "Not renamed: @docs-writer is already a member of rename-room."
    assert _memory("agents/voice-model") is not None
    assert await _told(client) == []


@pytest.mark.asyncio
async def test_the_schedules_it_owns_move_to_the_new_name(client, room):
    from app.services import schedules

    await schedules.create(
        ROOM,
        name="morning",
        owner="voice-model",
        every="1d",
        cron=None,
        prompt="Check the board.",
        check=None,
        task=None,
        expires_in_days=None,
        created_by="julia",
    )
    await _rename(client, "docs-writer")
    assert schedules.load(ROOM)["morning"].owner == "docs-writer"


@pytest.mark.asyncio
async def test_a_persons_handle_is_refused(client, room):
    await client.post("/api/users", json={"handle": "avery"})
    resp = await _rename(client, "avery")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "@avery is a person's name."
    assert _memory("agents/voice-model") is not None


@pytest.mark.asyncio
async def test_a_machine_running_another_agent_is_not_asked(client, room):
    from app.services import runners

    runners.registry.clear()
    await client.post("/api/runners", json=_machine_with("hay"))
    body = (await _rename(client, "docs-writer")).json()
    assert body["restart_job"] is None
    assert (await client.get("/api/runners/julias-mbp/jobs")).json() == []
    runners.registry.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("to", "old", "status", "says"),
    [
        ("docs-writer", "nobody", 404, "No agent @nobody"),
        ("voice-model", "voice-model", 422, "already called that"),
        ("Bad Name!", "voice-model", 422, "lowercase"),
    ],
)
async def test_a_rename_that_cant_be_done_writes_nothing(client, room, to, old, status, says):
    resp = await _rename(client, to, old=old)
    assert resp.status_code == status
    assert says in resp.json()["detail"]
    assert _memory("agents/voice-model") is not None


@pytest.mark.asyncio
async def test_a_taken_handle_is_refused_and_the_old_one_is_free(client, room):
    other = yaml.safe_dump({"adapter": "claude_code"})
    await client.post(
        f"/api/rooms/{ROOM}/memory",
        json={
            "items": [{"key": "agents/hay", "value": other, "created_by": "julia", "embed": False}]
        },
    )
    assert (await _rename(client, "hay")).status_code == 409

    await _rename(client, "docs-writer")
    # Nothing holds the old name: another agent can take it at once.
    assert (await _rename(client, "voice-model", old="hay")).status_code == 200


@pytest.mark.asyncio
async def test_an_engine_is_not_renamed(client, room):
    resp = await client.post(
        f"/api/rooms/{ROOM}/engines", json={"handle": "aligner", "kind": "aligner"}
    )
    assert resp.status_code in (200, 201), resp.text
    resp = await _rename(client, "mediator", old="aligner")
    assert resp.status_code == 422
    assert "engine" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_someone_must_say_who_is_renaming_it(client, room):
    resp = await _rename(client, "docs-writer", by=None)
    assert resp.status_code == 422
    assert _memory("agents/voice-model") is not None
