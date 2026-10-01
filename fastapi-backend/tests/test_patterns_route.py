# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""/api/patterns: design patterns as scenarios, loaded as a room.

Through the app, node-free. What a pack offers; what loading writes (the room,
its engines, memories and task) and that it stops there unless told to run;
that a name is claimed whole, so two loads at once are two rooms; that a step
that fails takes the room away; and what the hub refuses on its own say: a
scenario that does not fit, a flow the hub cannot parse, a worker on a hub set
to personas only, a scenario sent in the request on a hub that takes none.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from fastapi import HTTPException

from app.config import settings
from app.services import patterns, persister
from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file

if TYPE_CHECKING:
    from pathlib import Path

FLOW = {
    "description": "Defend, then answer.",
    "roles": ["proposer", "critic"],
    "steps": [
        {"id": "propose", "to": "proposer", "prompt": "{ask}", "next": "done"},
        {"id": "done", "end": "resolved"},
    ],
}


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


def scenario(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "pattern": "approval-gate-agent",
        "title": "Approval gate",
        "summary": "An agent proposes, a person decides.",
        "room": {"title": "Refund batch", "description": "Gate."},
        "context": [{"key": "context/policy", "text": "Over 5000 needs a person."}],
        "members": [
            {"handle": "ops", "kind": "persona", "description": "Ops.", "notes": "You are ops."},
            {"handle": "you", "kind": "human"},
        ],
        "task": {"title": "Refund the batch", "body": "It is over the limit."},
        "summon": {"flow": "gated", "members": ["ops", "you"], "ask": "Refund them."},
    }
    data.update(over)
    return data


def write_pack(root: Path, flow: dict | str | None = None, **over: Any) -> Path:
    data = scenario(**over)
    folder = root / "scenarios" / data["pattern"]
    folder.mkdir(parents=True)
    if flow is not None:
        data["flow_file"] = "protocol.yaml"
        (folder / "protocol.yaml").write_text(
            flow if isinstance(flow, str) else yaml.safe_dump(flow)
        )
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    return root


@pytest.fixture
def pack(tmp_path, monkeypatch) -> Path:
    root = write_pack(tmp_path / "pack")
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(root))
    return root


def kind_of(room: str, handle: str) -> str | None:
    found = read_memory_file(get_room_dir(room), f"agents/{handle}")
    return (yaml.safe_load(found[1]) or {}).get("kind") if found else None


# ── what a pack offers ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hub_with_no_pack_offers_none(client, monkeypatch):
    monkeypatch.setattr(settings, "PATTERNS_DIR", "")
    resp = await client.get("/api/patterns")
    assert resp.status_code == 200
    assert resp.json() == {"patterns": [], "skipped": {}}
    assert (await client.get("/api/patterns/approval-gate-agent")).status_code == 404


@pytest.mark.asyncio
async def test_the_pack_is_listed_and_read(client, pack):
    listed = (await client.get("/api/patterns")).json()["patterns"]
    assert [p["pattern"] for p in listed] == ["approval-gate-agent"]
    assert listed[0]["flow"] == "gated"
    assert listed[0]["roles"] == ["proposer", "guardian"]
    assert [m["handle"] for m in listed[0]["members"]] == ["ops", "you"]

    full = (await client.get("/api/patterns/approval-gate-agent")).json()
    assert full["scenario"]["task"]["title"] == "Refund the batch"
    assert full["flow_body"] is None


@pytest.mark.asyncio
async def test_a_scenario_that_does_not_load_is_skipped_and_says_why(client, pack, tmp_path):
    write_pack(
        tmp_path / "pack",
        pattern="broken",
        members=[{"handle": "ops", "kind": "persona"}],
        summon=None,
    )
    body = (await client.get("/api/patterns")).json()
    assert [p["pattern"] for p in body["patterns"]] == ["approval-gate-agent"]
    assert "needs notes" in body["skipped"]["broken"]
    assert (await client.get("/api/patterns/broken")).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["nope", "..", "a%2Fb", "Not-A-Slug"])
async def test_a_name_that_is_not_in_the_pack_is_not_found(client, pack, name):
    assert (await client.get(f"/api/patterns/{name}")).status_code == 404
    assert (await client.post(f"/api/patterns/{name}/load", json={})).status_code == 404


# ── loading ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loading_makes_a_room_ready_and_paused(client, pack):
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={"created_by": "julia"})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    room = body["room"]
    assert room == "approval-gate-agent"
    assert body["ran"] is False
    assert body["summon"] == "@conductor gated @ops @julia: Refund them."
    assert body["members"] == ["conductor", "ops"]

    info = (await client.get(f"/api/rooms/{room}")).json()
    assert info["title"] == "Refund batch"
    assert info["owner"] == "julia"
    assert info["is_public"] is True
    assert (kind_of(room, "conductor"), kind_of(room, "ops")) == ("conductor", "persona")
    assert kind_of(room, "you") is None  # the person is not an engine

    notes = read_memory_file(get_room_dir(room), "agents/ops/notes")
    assert notes is not None
    assert "You are ops." in notes[1]
    policy = read_memory_file(get_room_dir(room), "context/policy")
    assert policy is not None
    assert "Over 5000" in policy[1]
    rows = [key for key, _m, _c in list_memory_files(get_room_dir(room), prefix="work/")]
    assert rows == [body["key"]]
    row = read_memory_file(get_room_dir(room), body["key"])
    assert row is not None
    assert "It is over the limit." in row[1]
    assert body["episode"]

    # Paused: the summon was not posted.
    assert [m for m in persister.prose_messages(room) if m.episode == body["episode"]] == []


@pytest.mark.asyncio
async def test_run_posts_the_summon_in_the_tasks_thread(client, pack):
    resp = await client.post(
        "/api/patterns/approval-gate-agent/load", json={"created_by": "julia", "run": True}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ran"] is True
    said = [
        m.content for m in persister.prose_messages(body["room"]) if m.episode == body["episode"]
    ]
    sent = said or [
        m["content"]
        for m in (await client.get(f"/api/rooms/{body['room']}/messages")).json()["messages"]
    ]
    assert "@conductor gated @ops @julia: Refund them." in sent


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing(client, pack):
    resp = await client.post(
        "/api/patterns/approval-gate-agent/load", json={"dry_run": True, "created_by": "julia"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["dry_run"] is True
    assert resp.json()["key"] is None
    assert (await client.get("/api/rooms/approval-gate-agent")).status_code == 404


@pytest.mark.asyncio
async def test_a_private_room_needs_an_owner(client, pack):
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={"private": True})
    assert resp.status_code == 422
    assert (await client.get("/api/rooms/approval-gate-agent")).status_code == 404


@pytest.mark.asyncio
async def test_a_taken_name_is_counted_past_unless_asked_for(client, pack):
    first = await client.post("/api/patterns/approval-gate-agent/load", json={})
    second = await client.post("/api/patterns/approval-gate-agent/load", json={})
    assert (first.json()["room"], second.json()["room"]) == (
        "approval-gate-agent",
        "approval-gate-agent-2",
    )

    named = await client.post("/api/patterns/approval-gate-agent/load", json={"room": "mine"})
    assert named.json()["room"] == "mine"
    again = await client.post("/api/patterns/approval-gate-agent/load", json={"room": "mine"})
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_two_loads_at_once_are_two_rooms(client, pack):
    results = await asyncio.gather(
        *(client.post("/api/patterns/approval-gate-agent/load", json={}) for _ in range(4))
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    rooms = sorted(r.json()["room"] for r in results)
    assert len(set(rooms)) == 4
    for room in rooms:
        assert kind_of(room, "ops") == "persona"


@pytest.mark.asyncio
async def test_a_reserved_or_unusable_room_name_is_refused(client, pack):
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={"room": "a/b"})
    assert resp.status_code == 422
    assert (await client.get("/api/rooms/approval-gate-agent")).status_code == 404


@pytest.mark.asyncio
async def test_a_failed_step_takes_the_room_away(client, pack, monkeypatch):
    async def boom(*_a, **_k):
        raise HTTPException(status_code=500, detail="disk full")

    monkeypatch.setattr("app.routes.patterns.create_memories", boom)
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={})

    assert resp.status_code == 500
    assert "Could not write the context and the members' notes: disk full" in resp.text
    assert (await client.get("/api/rooms/approval-gate-agent")).status_code == 404


@pytest.mark.asyncio
async def test_an_unexpected_error_takes_the_room_away_too(client, pack, monkeypatch):
    async def boom(*_a, **_k):
        msg = "not even an HTTP error"
        raise RuntimeError(msg)

    monkeypatch.setattr("app.routes.patterns.create_task_route", boom)
    with pytest.raises(RuntimeError):
        await client.post("/api/patterns/approval-gate-agent/load", json={})
    assert (await client.get("/api/rooms/approval-gate-agent")).status_code == 404


# ── the pack's own flow ──────────────────────────────────────────────────────

OWN: dict[str, Any] = {
    "pattern": "adversarial-review-agents",
    "members": [
        {"handle": "proposer", "kind": "persona", "notes": "You propose."},
        {"handle": "critic", "kind": "persona", "notes": "You criticise."},
    ],
    "summon": {"flow": "adversarial-review", "members": ["proposer", "critic"], "ask": "Sign?"},
}


@pytest.mark.asyncio
async def test_a_flow_the_pack_brings_is_the_rooms_flow(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(write_pack(tmp_path / "p", FLOW, **OWN)))
    resp = await client.post("/api/patterns/adversarial-review-agents/load", json={})
    assert resp.status_code == 201, resp.text
    room = resp.json()["room"]
    flows = {f["name"]: f for f in (await client.get(f"/api/rooms/{room}/protocols")).json()}
    assert flows["adversarial-review"]["source"] == "room"
    assert flows["adversarial-review"]["roles"] == ["proposer", "critic"]


@pytest.mark.asyncio
async def test_a_pack_flow_that_shares_a_built_ins_name_wins(client, tmp_path, monkeypatch):
    over = {**OWN, "summon": {**OWN["summon"], "flow": "gated"}}
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(write_pack(tmp_path / "p", FLOW, **over)))
    resp = await client.post("/api/patterns/adversarial-review-agents/load", json={})
    assert resp.status_code == 201, resp.text
    flows = {
        f["name"]: f
        for f in (await client.get(f"/api/rooms/{resp.json()['room']}/protocols")).json()
    }
    assert flows["gated"]["source"] == "room"


@pytest.mark.asyncio
async def test_a_flow_the_hub_cannot_parse_is_refused_before_any_room(
    client, tmp_path, monkeypatch
):
    bad = {**FLOW, "steps": [{"id": "propose", "to": "proposer", "next": "nowhere"}]}
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(write_pack(tmp_path / "p", bad, **OWN)))
    resp = await client.post("/api/patterns/adversarial-review-agents/load", json={})
    assert resp.status_code == 422
    assert "nowhere" in resp.text
    assert (await client.get("/api/rooms/adversarial-review-agents")).status_code == 404


@pytest.mark.asyncio
async def test_a_flow_file_cannot_reach_outside_its_folder(client, tmp_path, monkeypatch):
    (tmp_path / "secret.yaml").write_text(yaml.safe_dump(FLOW))
    root = write_pack(tmp_path / "p", None, **OWN)
    path = root / "scenarios/adversarial-review-agents/scenario.yaml"
    data = yaml.safe_load(path.read_text())
    data["flow_file"] = "../../../../secret.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(root))
    resp = await client.post("/api/patterns/adversarial-review-agents/load", json={})
    assert resp.status_code == 422
    assert "not a file in the scenario's folder" in resp.text


# ── what the hub will not do ─────────────────────────────────────────────────

WORKER: dict[str, Any] = {
    "members": [
        {"handle": "ops", "kind": "worker", "notes": "You do the work."},
        {"handle": "you", "kind": "human"},
    ]
}


@pytest.mark.asyncio
async def test_a_hub_set_to_personas_only_refuses_a_worker(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(write_pack(tmp_path / "p", **WORKER)))
    assert (await client.post("/api/patterns/approval-gate-agent/load", json={})).status_code == 201

    monkeypatch.setattr(settings, "PATTERNS_PERSONAS_ONLY", True)
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={"room": "again"})
    assert resp.status_code == 422
    assert "personas only" in resp.text
    assert (await client.get("/api/rooms/again")).status_code == 404
    listed = (await client.get("/api/patterns")).json()
    assert "approval-gate-agent" in listed["skipped"]


@pytest.mark.asyncio
async def test_a_scenario_in_the_request_loads_when_the_hub_allows_it(client, pack):
    resp = await client.post(
        "/api/patterns/load",
        json={"scenario": scenario(pattern="mine"), "created_by": "julia", "room": "inline-room"},
    )
    assert resp.status_code == 201, resp.text
    assert kind_of("inline-room", "ops") == "persona"


@pytest.mark.asyncio
async def test_a_scenario_in_the_request_brings_its_own_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "PATTERNS_DIR", "")
    data = scenario(**OWN, flow_file="protocol.yaml")
    resp = await client.post(
        "/api/patterns/load", json={"scenario": data, "flow": yaml.safe_dump(FLOW)}
    )
    assert resp.status_code == 201, resp.text
    flows = {
        f["name"]: f
        for f in (await client.get(f"/api/rooms/{resp.json()['room']}/protocols")).json()
    }
    assert flows["adversarial-review"]["source"] == "room"


@pytest.mark.asyncio
async def test_a_hub_that_takes_no_inline_scenario_says_so(client, pack, monkeypatch):
    monkeypatch.setattr(settings, "PATTERNS_ALLOW_INLINE", False)
    resp = await client.post("/api/patterns/load", json={"scenario": scenario()})
    assert resp.status_code == 403
    # Its own pack still loads.
    assert (await client.post("/api/patterns/approval-gate-agent/load", json={})).status_code == 201


@pytest.mark.asyncio
async def test_a_scenario_in_the_request_is_checked_like_any_other(client, pack):
    resp = await client.post(
        "/api/patterns/load",
        json={
            "scenario": scenario(summon={"flow": "gated", "members": ["ops", "ghost"], "ask": "x"})
        },
    )
    assert resp.status_code == 422
    assert "does not cast" in resp.text
    resp = await client.post("/api/patterns/load", json={"scenario": {"pattern": "x"}})
    assert resp.status_code == 422


# ── the scenario itself ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"members": [{"handle": "ops", "kind": "persona"}]}, "needs notes"),
        (
            {"summon": {"flow": "my-own", "members": ["ops"], "ask": "x"}},
            "not built in",
        ),
        (
            {
                "members": [
                    {"handle": "ops", "kind": "persona", "notes": "n"},
                    {"handle": "judge", "kind": "aligner"},
                ],
                "summon": {"flow": "gated", "members": ["ops", "judge"], "ask": "x"},
            },
            "cannot ask",
        ),
        ({"members": [{"handle": "conductor", "kind": "hello"}]}, "not 'conductor'"),
        (
            {"members": [scenario()["members"][0], scenario()["members"][0]]},
            "distinct",
        ),
        (
            {"summon": {"flow": "fan-out", "members": ["ops"], "ask": "x"}},
            "asks workers",
        ),
        ({"context": [{"key": "notes/x", "text": "t"}]}, "context/<slug>"),
        ({"pattern": "Not A Slug"}, "lowercase slug"),
    ],
)
def test_a_scenario_that_does_not_fit_is_refused(over, message):
    with pytest.raises(patterns.PatternInvalid, match=message):
        patterns.parse(scenario(**over))


def test_a_scenario_with_no_flow_needs_no_conductor():
    loaded = patterns.parse(scenario(summon=None))
    plan = patterns.build_plan(loaded, "julia")
    assert plan.summon is None
    assert [h for h, _, _ in plan.engines] == ["ops"]


def test_the_person_takes_the_human_seat():
    plan = patterns.build_plan(patterns.parse(scenario()), "julia")
    assert plan.cast == ["ops", "julia"]
    assert plan.memories[1] == {"key": "agents/ops/notes", "value": "You are ops.", "embed": False}
