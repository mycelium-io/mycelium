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
