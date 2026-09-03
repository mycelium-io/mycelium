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


@pytest.mark.asyncio
async def test_materialize_writes_a_built_in_once(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    get_room_dir(ROOM)
    gated = protocols.builtin("gated")
    assert gated is not None

    assert await protocols.materialize(ROOM, gated, created_by="conductor") is True
    assert protocols.room_protocol_names(ROOM) == ["gated"]
    found = protocols.load_protocol(ROOM, "gated")
    assert found == gated
    # Already the room's: left alone, so an edit survives the next run.
    assert await protocols.materialize(ROOM, gated, created_by="conductor") is False
