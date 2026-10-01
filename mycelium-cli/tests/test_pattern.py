# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium pattern``: a pack of scenarios loaded as a paused room.

No hub and no git: the hub is an ``httpx.MockTransport`` and the pack a folder
in ``tmp_path``. These hold what the command asks of the hub (the room, its
engines, the notes and context and flow as memories, the task, and the summon
only when told to run), what it refuses before touching the hub, and that a
failed load takes its room away.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import pattern
from mycelium.commands.swarm import SwarmError

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


def scenario_data(**over: Any) -> dict[str, Any]:
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


def write_pack(root: Path, **over: Any) -> Path:
    data = scenario_data(**over)
    folder = root / "scenarios" / data["pattern"]
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    return root


class Hub:
    """A hub stand-in: it records every call and answers like the real routes."""

    def __init__(
        self,
        *,
        taken: tuple[str, ...] = (),
        fail_on: str | None = None,
        flows: list[dict[str, str]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.taken = set(taken)
        self.fail_on = fail_on
        self.flows = flows if flows is not None else [{"name": "gated", "source": "builtin"}]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if self.fail_on and path.endswith(self.fail_on):
            return httpx.Response(500, text="boom")
        if request.method == "GET" and path.startswith("/api/rooms/") and path.count("/") == 3:
            return httpx.Response(200 if path.rsplit("/", 1)[1] in self.taken else 404)
        if request.method == "GET" and path.endswith("/protocols"):
            return httpx.Response(200, json=self.flows)
        if path.endswith("/tasks"):
            return httpx.Response(201, json={"key": "work/refund-the-batch", "episode": "urn:t1"})
        return httpx.Response(201, json={})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://hub", transport=httpx.MockTransport(self))

    def paths(self) -> list[str]:
        return [f"{m} {p}" for m, p, _ in self.calls]


def plan_for(tmp_path: Path, **over: Any) -> pattern.Plan:
    pack = pattern.Pack(root=write_pack(tmp_path, **over), source=str(tmp_path))
    name = scenario_data(**over)["pattern"]
    return pattern.build_plan(pack.load(name), "gate-room", "julia")


# ── the pack ─────────────────────────────────────────────────────────────────


def test_a_pack_lists_and_loads_its_scenarios(tmp_path: Path) -> None:
    pack = pattern.fetch_pack(str(write_pack(tmp_path)))
    assert pack.names() == ["approval-gate-agent"]
    summon = pack.load("approval-gate-agent").summon
    assert summon is not None
    assert summon.flow == "gated"


def test_an_unknown_scenario_names_the_known_ones(tmp_path: Path) -> None:
    pack = pattern.fetch_pack(str(write_pack(tmp_path)))
    with pytest.raises(pattern.PatternError, match="Known: approval-gate-agent"):
        pack.load("nope")


def test_a_source_that_is_neither_a_folder_nor_a_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(pattern.PatternError, match="not a folder or a git URL"):
        pattern.fetch_pack(str(tmp_path / "missing"))


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"members": [{"handle": "ops", "kind": "persona"}]}, "needs notes"),
        (
            {"summon": {"flow": "gated", "members": ["ops", "ghost"], "ask": "x"}},
            "does not cast",
        ),
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
    ],
)
def test_a_scenario_that_does_not_fit_is_refused(
    tmp_path: Path, over: dict[str, Any], message: str
) -> None:
    pack = pattern.Pack(root=write_pack(tmp_path, **over), source="x")
    with pytest.raises(pattern.PatternError, match=message):
        pack.load("approval-gate-agent")


def test_a_flow_file_outside_the_scenario_folder_is_refused(tmp_path: Path) -> None:
    (tmp_path / "secret.yaml").write_text("x: 1")
    over = {
        "flow_file": "../../../secret.yaml",
        "summon": {"flow": "mine", "members": ["ops"], "ask": "x"},
    }
    pack = pattern.Pack(root=write_pack(tmp_path / "pack", **over), source="x")
    with pytest.raises(pattern.PatternError, match="not in the folder"):
        pack.load("approval-gate-agent")


# ── the plan ─────────────────────────────────────────────────────────────────


def test_the_plan_seats_the_person_and_registers_the_rest(tmp_path: Path) -> None:
    plan = plan_for(tmp_path)
    assert [(h, k) for h, k, _ in plan.engines] == [("conductor", "conductor"), ("ops", "persona")]
    assert plan.summon == "@conductor gated @ops @julia: Refund them."
    assert [m["key"] for m in plan.memories] == ["context/policy", "agents/ops/notes"]
    assert plan.memories[1]["embed"] is False


def test_a_flow_file_is_written_as_the_rooms_protocol(tmp_path: Path) -> None:
    folder = write_pack(
        tmp_path, flow_file="protocol.yaml", summon={"flow": "mine", "members": ["ops"], "ask": "x"}
    )
    (folder / "scenarios/approval-gate-agent/protocol.yaml").write_text(yaml.safe_dump(FLOW))
    scenario = pattern.Pack(root=folder, source="x").load("approval-gate-agent")
    plan = pattern.build_plan(scenario, "r", "julia")
    assert plan.memories[-1]["key"] == "protocols/mine"
    assert yaml.safe_load(plan.memories[-1]["value"])["roles"] == ["proposer", "critic"]


def test_a_scenario_without_a_flow_registers_no_conductor(tmp_path: Path) -> None:
    plan = plan_for(tmp_path, summon=None)
    assert plan.summon is None
    assert "conductor" not in [h for h, _, _ in plan.engines]


def test_a_taken_room_name_is_refused_when_asked_for_and_counted_past_otherwise() -> None:
    hub = Hub(taken=("gate", "gate-2"))
    with hub.client() as client:
        assert pattern.free_room_name(client, "gate", exact=False) == "gate-3"
        with pytest.raises(pattern.PatternError, match="already exists"):
            pattern.free_room_name(client, "gate", exact=True)
        assert pattern.free_room_name(client, "fresh", exact=True) == "fresh"


# ── the load ─────────────────────────────────────────────────────────────────


def test_loading_builds_the_room_and_stays_paused(tmp_path: Path) -> None:
    hub = Hub()
    plan = plan_for(tmp_path)
    with hub.client() as client:
        key, episode = pattern.load(client, plan)
    assert (key, episode) == ("work/refund-the-batch", "urn:t1")
    assert hub.paths() == [
        "POST /api/rooms",
        "POST /api/rooms/gate-room/engines",
        "POST /api/rooms/gate-room/engines",
        "POST /api/rooms/gate-room/memory",
        "GET /api/rooms/gate-room/protocols",
        "POST /api/rooms/gate-room/tasks",
        "POST /api/rooms/gate-room/memory",
    ]
    room = hub.calls[0][2]
    assert room["title"] == "Refund batch"
    assert room["owner"] == "julia"
    assert room["is_public"] is True
    task_body = hub.calls[-1][2]["items"][0]
    assert task_body["key"] == "work/refund-the-batch"
    assert task_body["value"].startswith("Refund the batch\n\nIt is over the limit.")


def test_run_posts_the_summon_in_the_tasks_thread(tmp_path: Path) -> None:
    hub = Hub()
    with hub.client() as client:
        pattern.load(client, plan_for(tmp_path), run=True)
    method, path, body = hub.calls[-1]
    assert (method, path) == ("POST", "/api/rooms/gate-room/messages")
    assert body["content"] == "@conductor gated @ops @julia: Refund them."
    assert body["episode"] == "urn:t1"
    assert body["sender_handle"] == "julia"


def test_a_failed_step_removes_the_room(tmp_path: Path) -> None:
    hub = Hub(fail_on="/memory")
    with hub.client() as client, pytest.raises(SwarmError, match="write the context"):
        pattern.load(client, plan_for(tmp_path))
    assert hub.paths()[-1] == "DELETE /api/rooms/gate-room"


def test_a_flow_the_hub_leaves_out_fails_the_load(tmp_path: Path) -> None:
    hub = Hub(flows=[{"name": "round-robin", "source": "builtin"}])
    with hub.client() as client, pytest.raises(SwarmError, match="did not accept the flow"):
        pattern.load(client, plan_for(tmp_path))
    assert hub.paths()[-1] == "DELETE /api/rooms/gate-room"


def test_a_pack_flow_must_win_over_the_builtin_of_the_same_name(tmp_path: Path) -> None:
    folder = write_pack(
        tmp_path,
        flow_file="protocol.yaml",
        summon={"flow": "gated", "members": ["ops"], "ask": "x"},
    )
    (folder / "scenarios/approval-gate-agent/protocol.yaml").write_text(yaml.safe_dump(FLOW))
    scenario = pattern.Pack(root=folder, source="x").load("approval-gate-agent")
    hub = Hub()  # lists gated as built in: the pack's copy was not taken
    with hub.client() as client, pytest.raises(SwarmError, match="kept its built-in"):
        pattern.load(client, pattern.build_plan(scenario, "gate-room", "julia"))


# ── the command ──────────────────────────────────────────────────────────────


def test_dry_run_shows_the_plan_and_touches_no_hub(tmp_path: Path) -> None:
    pack = write_pack(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "pattern",
            "use",
            "approval-gate-agent",
            "--from",
            str(pack),
            "--dry-run",
            "--as",
            "julia",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Would create" in result.output
    assert "@julia" in result.output


def test_ls_lists_the_pack(tmp_path: Path) -> None:
    pack = write_pack(tmp_path)
    result = CliRunner().invoke(app, ["pattern", "ls", "--from", str(pack)])
    assert result.exit_code == 0, result.output
    assert "approval-gate-agent" in result.output


def test_use_names_a_missing_scenario(tmp_path: Path) -> None:
    pack = write_pack(tmp_path)
    result = CliRunner().invoke(
        app, ["pattern", "use", "nope", "--from", str(pack), "--dry-run", "--as", "julia"]
    )
    assert result.exit_code == 1
    assert "no scenario named" in result.output
