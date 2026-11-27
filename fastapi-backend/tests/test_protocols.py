# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Protocol specs: the built-ins are sound, a bad graph is refused, a room's own wins."""

from __future__ import annotations

import pytest
import yaml

from app.services import protocols
from app.services.filesystem import get_room_dir, write_memory_file

ROOM = "spec-room"


@pytest.mark.parametrize("name", protocols.builtin_names())
def test_every_builtin_validates(name: str):
    spec = protocols.builtin(name)
    assert spec is not None
    assert spec.name == name
    assert any(s.end for s in spec.steps)


def test_the_gated_review_branches_on_stance():
    gated = protocols.builtin("gated")
    assert gated is not None
    review = gated.step("review")
    assert review.edge("accept") == "approved"
    assert review.edge("reject") == "propose"
    assert review.edge(None) == "propose"
    assert review.edge("silent") == "propose"


def test_a_plain_edge_ignores_the_stance():
    step = protocols.Step(id="a", to="each", next="b")
    assert step.edge("reject") == "b"


def test_a_branch_with_no_fallback_reads_a_non_answer_as_reject():
    step = protocols.Step(id="a", to="each", next={"accept": "yes", "reject": "no"})
    assert step.edge(None) == "no"
    assert step.edge("silent") == "no"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (
            {"name": "x", "steps": [{"id": "a", "to": "each", "next": "a"}]},
            "at least one end step",
        ),
        (
            {
                "name": "x",
                "steps": [{"id": "a", "to": "each", "next": "zz"}, {"id": "d", "end": "resolved"}],
            },
            "not a step",
        ),
        (
            {
                "name": "x",
                "steps": [{"id": "a", "to": "boss", "next": "d"}, {"id": "d", "end": "resolved"}],
            },
            "neither a role nor a group",
        ),
        (
            {"name": "x", "steps": [{"id": "a", "end": "resolved", "to": "each"}]},
            "cannot also address",
        ),
        (
            {
                "name": "x",
                "steps": [
                    {"id": "a", "to": "each", "next": {"maybe": "d"}},
                    {"id": "d", "end": "resolved"},
                ],
            },
            "branches on",
        ),
        (
            {"name": "x", "roles": ["each"], "steps": [{"id": "d", "end": "resolved"}]},
            "cannot be named",
        ),
        (
            {
                "name": "x",
                "steps": [{"id": "d", "end": "resolved"}, {"id": "d", "end": "rejected"}],
            },
            "distinct",
        ),
    ],
)
def test_a_bad_graph_is_refused(spec, message):
    with pytest.raises(ValueError, match=message):
        protocols.Protocol.model_validate(spec)


def test_parse_takes_the_name_from_the_key_not_the_body():
    body = yaml.safe_dump(
        {"name": "impostor", "roles": ["r"], "steps": [{"id": "d", "end": "resolved"}]}
    )
    assert protocols.parse_protocol("mine", body).name == "mine"


def test_load_falls_back_to_the_builtin():
    get_room_dir(ROOM)
    spec = protocols.load_protocol(ROOM, "Gated")
    assert spec is not None
    assert spec.name == "gated"
    assert protocols.load_protocol(ROOM, "nope") is None
    assert protocols.load_protocol(ROOM, "") is None


def test_a_rooms_own_spec_wins_under_the_same_name():
    write_memory_file(
        get_room_dir(ROOM),
        "protocols/gated",
        yaml.safe_dump(
            {
                "roles": ["author"],
                "max_steps": 2,
                "steps": [
                    {"id": "ask", "to": "author", "prompt": "go", "next": "done"},
                    {"id": "done", "end": "resolved"},
                ],
            }
        ),
        created_by="julia",
    )
    spec = protocols.load_protocol(ROOM, "gated")
    assert spec is not None
    assert spec.roles == ["author"]
    assert spec.max_steps == 2


def test_a_spec_that_does_not_parse_is_absent_not_half_read():
    write_memory_file(
        get_room_dir(ROOM), "protocols/broken", "steps: [nonsense", created_by="julia"
    )
    assert protocols.load_protocol(ROOM, "broken") is None
    write_memory_file(
        get_room_dir(ROOM), "protocols/loose", yaml.safe_dump({"steps": []}), created_by="julia"
    )
    assert protocols.load_protocol(ROOM, "loose") is None


def test_the_catalogue_puts_the_rooms_own_first_and_leaves_out_what_does_not_parse():
    room = "catalogue-room"
    one_step = {
        "roles": ["author"],
        "steps": [
            {"id": "ask", "to": "author", "prompt": "go", "next": "done"},
            {"id": "done", "end": "resolved"},
        ],
    }
    write_memory_file(
        get_room_dir(room), "protocols/gated", yaml.safe_dump(one_step), created_by="julia"
    )
    write_memory_file(
        get_room_dir(room), "protocols/pair", yaml.safe_dump(one_step), created_by="julia"
    )
    write_memory_file(
        get_room_dir(room), "protocols/broken", "steps: [nonsense", created_by="julia"
    )

    listed = [(p.name, source, p.roles) for p, source in protocols.catalogue(room)]
    assert listed[:2] == [("gated", "room", ["author"]), ("pair", "room", ["author"])]
    names = [name for name, _, _ in listed]
    # The room's gated stands in for the built-in rather than beside it.
    assert names.count("gated") == 1
    assert "broken" not in names
    assert set(protocols.builtin_names()) - {"gated"} <= set(names)


@pytest.mark.asyncio
async def test_the_protocols_route_lists_each_flow_with_its_roles(client):
    await client.post("/api/rooms", json={"name": "flows"})
    resp = await client.get("/api/rooms/flows/protocols")
    assert resp.status_code == 200
    by_name = {p["name"]: p for p in resp.json()}
    assert by_name["gated"]["roles"] == ["proposer", "guardian"]
    assert by_name["gated"]["source"] == "builtin"
    assert by_name["round-robin"]["roles"] == []
    assert by_name["review"]["description"]

    missing = await client.get("/api/rooms/no-such-room/protocols")
    assert missing.status_code == 404


def test_describe_reads_as_a_person_would():
    gated = protocols.builtin("gated")
    assert gated is not None
    text = protocols.describe(gated)
    assert text.splitlines()[0].startswith("**gated**: A proposer proposes")
    assert "roles: proposer, guardian (bound in that order)" in text
    assert "- propose: asks proposer, then review" in text
    assert (
        "- review: asks guardian, then by stance (accept: approved, reject: propose, default: propose)"
        in text
    )
    assert "- approved: ends resolved" in text
    assert text.splitlines()[-1] == "up to 6 steps"


def test_describe_says_rounds_and_tells():
    spec = protocols.Protocol.model_validate(
        {
            "name": "x",
            "steps": [
                {"id": "r", "to": "each", "rounds": 2, "next": "n"},
                {"id": "n", "to": "all", "wait": "none", "next": "d"},
                {"id": "d", "end": "resolved"},
            ],
        }
    )
    text = protocols.describe(spec)
    assert "- r: asks each, 2 rounds, then n" in text
    assert "- n: tells all, then d" in text


def test_edge_line_names_the_branch_taken_and_nothing_for_a_plain_edge():
    gated = protocols.builtin("gated")
    assert gated is not None
    review = gated.step("review")
    assert protocols.edge_line(review, "reject", "sec") == "review: sec blocked, on to propose"
    assert protocols.edge_line(review, "accept", "sec") == "review: sec accepted, on to approved"
    assert (
        protocols.edge_line(review, "silent", "sec") == "review: sec did not answer, on to propose"
    )
    assert protocols.edge_line(review, None, "sec") == "review: sec stated no stance, on to propose"
    assert protocols.edge_line(gated.step("propose"), None, "api") is None


def test_spec_of_round_trips_through_the_memory_body():
    for name in protocols.builtin_names():
        spec = protocols.builtin(name)
        assert spec is not None
        body = yaml.safe_dump(protocols.spec_of(spec), sort_keys=False)
        again = protocols.parse_protocol(name, body)
        assert again == spec


# ── what a step can be ────────────────────────────────────────────────────────

ASKS = {"id": "ask", "to": "all", "prompt": "go", "next": "done"}
DONE = {"id": "done", "end": "resolved"}


def _spec(*steps: dict) -> dict:
    return {"name": "t", "steps": list(steps)}


@pytest.mark.parametrize("kind", ["select", "tally", "lock", "vote"])
def test_a_step_kind_other_than_ask_is_refused_by_name(kind: str):
    step = {"id": "pick", "kind": kind, "next": {"feasible": "done"}}
    with pytest.raises(
        ValueError, match=f"step 'pick' has kind '{kind}', which is not a step kind"
    ):
        protocols.Protocol.model_validate(_spec(ASKS | {"next": "pick"}, step, DONE))


@pytest.mark.parametrize("field", ["collect", "threshold", "max_repairs", "of", "max_rounds"])
def test_a_field_no_step_takes_is_refused_rather_than_ignored(field: str):
    with pytest.raises(ValueError, match=f"sets {field}, which no step takes"):
        protocols.Protocol.model_validate(_spec(ASKS | {field: "scores"}, DONE))


def test_a_run_ends_resolved_or_rejected_and_a_reply_can_require_only_a_stance():
    with pytest.raises(ValueError, match="end"):
        protocols.Protocol.model_validate(_spec(ASKS, {"id": "done", "end": "converged"}))
    with pytest.raises(ValueError, match="require"):
        protocols.Protocol.model_validate(_spec(ASKS | {"require": "scores"}, DONE))
    spec = protocols.Protocol.model_validate(_spec(ASKS | {"require": "stance"}, DONE))
    assert spec.step("ask").needs == "stance"


def test_a_rooms_flow_with_a_step_kind_there_is_not_is_left_out_and_logged(caplog):
    room = "old-flow-room"
    body = yaml.safe_dump(
        {
            "steps": [
                {"id": "rate", "to": "all", "prompt": "rate", "next": "pick"},
                {"id": "pick", "kind": "select", "next": {"feasible": "done"}},
                {"id": "done", "end": "resolved"},
            ]
        }
    )
    write_memory_file(get_room_dir(room), "protocols/settle", body, created_by="julia")

    with caplog.at_level("WARNING", logger=protocols.logger.name):
        assert protocols.load_protocol(room, "settle") is None

    (said,) = [r.getMessage() for r in caplog.records]
    assert said.startswith(f"room {room}: flow protocols/settle is left out:")
    assert "has kind 'select', which is not a step kind" in said
