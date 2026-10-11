# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Room settings: ``settings/`` memories checked against one frozen table."""

import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import room_settings

_CONTRACT = json.loads(
    (Path(__file__).resolve().parent.parent.parent / "contracts" / "room-settings.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr("app.services.embedding._STUB", True)


async def _make_room(client, name: str = "demo") -> None:
    await client.post("/api/rooms", json={"name": name})


def test_table_matches_contract():
    assert _CONTRACT["namespace"] == room_settings.NAMESPACE
    assert _CONTRACT["value_field"] == room_settings.VALUE_FIELD
    ours = []
    for spec in room_settings.TABLE:
        row: dict = {"id": spec.id, "kind": spec.kind}
        if spec.options:
            row["options"] = list(spec.options)
        if spec.default is not None:
            row["default"] = list(spec.default) if spec.kind == "set" else spec.default
        if spec.min is not None:
            row["min"] = spec.min
        if spec.inherits:
            row["inherits"] = spec.inherits
        if spec.at_most_hub:
            row["at_most_hub"] = True
        ours.append(row)
    assert ours == _CONTRACT["settings"]


def test_every_inherited_setting_reads_a_hub_value():
    for spec in room_settings.TABLE:
        if spec.inherits:
            assert room_settings.hub_value(spec) is not None


@pytest.mark.asyncio
async def test_unset_settings_read_the_hub_or_the_default(client, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 60)
    await _make_room(client)
    resp = await client.get("/api/rooms/demo/settings")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.json()}
    assert by_id["worker-turns"]["value"] == 60
    assert by_id["worker-turns"]["source"] == "hub"
    assert by_id["worker-turns"]["max"] == 60
    assert by_id["chat-board-moves"]["value"] == ["filed", "resolved"]
    assert by_id["chat-board-moves"]["source"] == "default"
    assert by_id["dependency-gate"]["value"] is False


@pytest.mark.asyncio
async def test_set_and_reset_a_room_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 60)
    await _make_room(client)
    resp = await client.put(
        "/api/rooms/demo/settings/worker-turns",
        json={"value": 20, "reason": "Keep the swarm short.", "by": "julia"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 20
    assert body["source"] == "room"
    assert body["reason"] == "Keep the swarm short."
    assert body["updated_by"] == "julia"
    assert room_settings.value("demo", "worker-turns") == 20

    # It is a memory, readable as one.
    mem = await client.get("/api/rooms/demo/memory/settings/worker-turns")
    assert mem.status_code == 200
    assert mem.json()["meta"]["setting"] == 20

    reset = await client.delete("/api/rooms/demo/settings/worker-turns")
    assert reset.status_code == 200
    assert reset.json()["source"] == "hub"
    assert room_settings.value("demo", "worker-turns") == 60


@pytest.mark.asyncio
async def test_a_room_cannot_raise_the_hubs_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 30)
    await _make_room(client)
    resp = await client.put(
        "/api/rooms/demo/settings/worker-turns", json={"value": 31, "by": "julia"}
    )
    assert resp.status_code == 422
    assert "at most the hub's 30" in resp.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_a_lowered_hub_cap_wins_over_an_older_room_value(client, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 60)
    await _make_room(client)
    await client.put("/api/rooms/demo/settings/worker-turns", json={"value": 50, "by": "julia"})
    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 10)
    assert room_settings.value("demo", "worker-turns") == 10


@pytest.mark.asyncio
async def test_a_hand_edited_value_below_the_floor_runs_at_the_floor(client, monkeypatch):
    """A file edited by hand to `setting: 0` never silences the room's workers."""
    from app.services.filesystem import get_room_dir, write_memory_file

    monkeypatch.setattr(settings, "WORKER_MAX_TURNS_PER_ROOM", 60)
    await _make_room(client)
    write_memory_file(
        get_room_dir("demo"),
        "settings/worker-turns",
        "edited by hand\n",
        created_by="julia",
        extra_meta={"setting": 0},
    )
    assert room_settings.value("demo", "worker-turns") == 1


@pytest.mark.asyncio
async def test_memory_set_hits_the_same_check(client):
    """The table is enforced at the memory upsert, so a plain memory write is refused too."""
    await _make_room(client)
    bad = await client.post(
        "/api/rooms/demo/memory",
        json={
            "items": [
                {
                    "key": "settings/chat-board-moves",
                    "value": "why",
                    "created_by": "agent",
                    "meta": {"setting": ["filed", "everything"]},
                }
            ]
        },
    )
    assert bad.status_code == 422
    assert "everything" in bad.json()["detail"]["message"]

    unknown = await client.post(
        "/api/rooms/demo/memory",
        json={
            "items": [
                {
                    "key": "settings/theme",
                    "value": "x",
                    "created_by": "agent",
                    "meta": {"setting": 1},
                }
            ]
        },
    )
    assert unknown.status_code == 422
    assert "no room setting 'theme'" in unknown.json()["detail"]["message"]

    missing = await client.post(
        "/api/rooms/demo/memory",
        json={"items": [{"key": "settings/dependency-gate", "value": "x", "created_by": "agent"}]},
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_a_set_is_stored_in_table_order_once(client):
    await _make_room(client)
    resp = await client.put(
        "/api/rooms/demo/settings/chat-board-moves",
        json={"value": ["resolved", "claimed", "resolved"], "by": "julia"},
    )
    assert resp.json()["value"] == ["claimed", "resolved"]


@pytest.mark.asyncio
async def test_a_reason_only_write_keeps_the_value(client):
    await _make_room(client)
    await client.put(
        "/api/rooms/demo/settings/dependency-gate", json={"value": True, "by": "julia"}
    )
    resp = await client.post(
        "/api/rooms/demo/memory",
        json={
            "items": [
                {"key": "settings/dependency-gate", "value": "Because.", "created_by": "julia"}
            ]
        },
    )
    assert resp.status_code == 201
    assert room_settings.value("demo", "dependency-gate") is True


@pytest.mark.asyncio
async def test_unknown_setting_and_room_are_404(client):
    await _make_room(client)
    assert (await client.get("/api/rooms/nope/settings")).status_code == 404
    resp = await client.put("/api/rooms/demo/settings/theme", json={"value": 1, "by": "julia"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_rooms_dependency_gate_refuses_a_claim(client, monkeypatch):
    """The hub's gate is off; the room turns it on, and a waiting row can't be claimed."""
    monkeypatch.setattr(settings, "BOARD_DEPENDENCY_GATE", False)
    await _make_room(client)
    await client.post(
        "/api/rooms/demo/memory",
        json={"items": [{"key": "work/first", "value": "First", "created_by": "julia"}]},
    )
    await client.post(
        "/api/rooms/demo/memory",
        json={
            "items": [
                {
                    "key": "work/second",
                    "value": "Second",
                    "created_by": "julia",
                    "meta": {"depends-on": "work/first"},
                }
            ]
        },
    )
    claim = {"key": "work/second", "handle": "bob"}
    await client.put(
        "/api/rooms/demo/settings/dependency-gate", json={"value": True, "by": "julia"}
    )
    refused = await client.post("/api/rooms/demo/assignments/claim", json=claim)
    assert refused.status_code == 409
    assert refused.json()["detail"]["waiting_on"] == ["work/first"]

    await client.delete("/api/rooms/demo/settings/dependency-gate")
    taken = await client.post("/api/rooms/demo/assignments/claim", json=claim)
    assert taken.status_code == 200


def test_worker_turns_follow_the_room(monkeypatch, tmp_path):
    """With no cap given, a worker's cap is the room's setting, read on each turn."""
    from app.services.worker_engine import WorkerEngine

    engine = WorkerEngine(manager=None)  # type: ignore[arg-type]
    assert engine._max_turns is None
    monkeypatch.setattr(room_settings, "value", lambda room, sid: 0)
    import asyncio

    said = asyncio.run(engine.turn("demo", "w", episode="e", ask="hi"))
    assert said is None
