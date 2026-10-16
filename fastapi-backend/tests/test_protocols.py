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
    assert by_name["concord"]["roles"] == []
    assert by_name["accord"]["description"]

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


# ── picking: select steps, bottleneck, converged ──────────────────────────────


def _spec(*steps: dict, roles: list[str] | None = None) -> protocols.Protocol:
    return protocols.Protocol.model_validate(
        {"name": "t", "roles": roles or [], "steps": list(steps)}
    )


ASK = {"id": "ask", "to": "all", "collect": "scores", "prompt": "rate", "next": "pick"}
PICK = {
    "id": "pick",
    "kind": "select",
    "next": {"feasible": "ok", "infeasible": "ask", "stuck": "no"},
}
ENDS = ({"id": "ok", "end": "converged"}, {"id": "no", "end": "rejected"})


def test_a_select_step_validates_and_fills_its_bar():
    spec = _spec(ASK, PICK, *ENDS)
    pick = spec.step("pick")
    assert pick.threshold == protocols.DEFAULT_THRESHOLD
    assert pick.max_repairs == protocols.DEFAULT_MAX_REPAIRS
    # Collecting ratings requires them.
    assert spec.step("ask").needs == "scores"


@pytest.mark.parametrize(
    "extra",
    [{"to": "all"}, {"prompt": "hi"}, {"collect": "options"}, {"require": "stance"}],
)
def test_a_select_asks_nobody(extra: dict):
    with pytest.raises(ValueError, match="asks nobody"):
        _spec(ASK, PICK | extra, *ENDS)


def test_a_select_branches_only_on_how_the_pick_went():
    with pytest.raises(ValueError, match="branches on"):
        _spec(ASK, PICK | {"next": {"feasible": "ok", "accept": "no"}}, *ENDS)
    with pytest.raises(ValueError, match="branches by map"):
        _spec(ASK, PICK | {"next": "ok"}, *ENDS)


def test_a_bar_belongs_to_a_select_step():
    with pytest.raises(ValueError, match="belong to a select"):
        _spec(ASK | {"threshold": 0.5}, PICK, *ENDS)


def test_the_bottleneck_is_asked_only_after_a_pick_on_every_path():
    fix = {"id": "fix", "to": "bottleneck", "prompt": "fix it", "next": "ask"}
    _spec(ASK, PICK | {"next": {"feasible": "ok", "infeasible": "fix", "stuck": "no"}}, fix, *ENDS)
    with pytest.raises(ValueError, match="before any select"):
        _spec(fix | {"next": "ask"}, ASK, PICK, *ENDS)
    # A side path that skips the pick is refused too.
    branch = {
        "id": "vote",
        "to": "all",
        "prompt": "go?",
        "next": {"accept": "ask", "reject": "fix"},
    }
    with pytest.raises(ValueError, match="before any select"):
        _spec(branch, ASK, PICK, fix, *ENDS)


def test_converged_is_reached_only_from_a_feasible_edge():
    with pytest.raises(ValueError, match="only a select's feasible edge"):
        _spec(
            {"id": "ask", "to": "all", "prompt": "go", "next": "ok"},
            {"id": "ok", "end": "converged"},
        )
    with pytest.raises(ValueError, match="only a select's feasible edge"):
        _spec(ASK, PICK | {"next": {"feasible": "no", "infeasible": "ok"}}, *ENDS)


def test_a_step_that_collects_ratings_cannot_require_a_stance():
    with pytest.raises(ValueError, match="requires ratings, not a stance"):
        _spec(ASK | {"require": "stance"}, PICK, *ENDS)


def test_only_a_picks_infeasible_edge_leads_to_the_bottleneck():
    fix = {"id": "fix", "to": "bottleneck", "prompt": "fix it", "next": "ask"}
    with pytest.raises(ValueError, match="only its infeasible edge"):
        _spec(ASK, PICK | {"next": {"feasible": "ok", "default": "fix"}}, fix, *ENDS)


def test_nobody_can_play_the_bottleneck():
    with pytest.raises(ValueError, match="cannot be named"):
        _spec(ASK, PICK, *ENDS, roles=["bottleneck"])


def test_spec_of_carries_what_the_app_needs_to_draw_a_pick():
    concord = protocols.builtin("concord")
    assert concord is not None
    steps = {s["id"]: s for s in protocols.spec_of(concord)["steps"]}
    assert steps["pick"] == {
        "id": "pick",
        "kind": "select",
        "threshold": 0.7,
        "max_repairs": 2,
        "next": {"feasible": "agreed", "infeasible": "repair", "stuck": "no_deal"},
    }
    assert steps["score"]["collect"] == "scores"
    assert "kind" not in steps["score"], "an ask step's default is dropped"
    accord = protocols.builtin("accord")
    assert accord is not None
    steps = {s["id"]: s for s in protocols.spec_of(accord)["steps"]}
    assert steps["frame"]["collect"] == "pieces"
    assert steps["frame"]["require"] == "pieces"
    assert steps["added"] == {
        "id": "added",
        "kind": "tally",
        "of": "points",
        "max_rounds": 3,
        "next": {"grew": "more", "settled": "ground", "empty": "nothing"},
    }
    assert steps["words"]["of"] == "terms"
    assert steps["restate"]["to"] == "contested"
    assert steps["lock"] == {
        "id": "lock",
        "kind": "lock",
        "next": {"locked": "locked", "empty": "nothing"},
    }


def test_describe_says_what_a_pick_does():
    concord = protocols.builtin("concord")
    assert concord is not None
    text = protocols.describe(concord)
    assert "- pick: picks the option the least happy member likes best, bar 70" in text
    assert "- agreed: ends converged" in text


# ── a shared frame: tally steps, the contested, the lock ─────────────────────

FRAME = {
    "id": "frame",
    "to": "all",
    "collect": "pieces",
    "require": "pieces",
    "prompt": "frame it",
    "next": "added",
}
TALLY = {
    "id": "added",
    "kind": "tally",
    "of": "points",
    "next": {"grew": "frame", "settled": "ground", "empty": "nothing"},
}
GROUND = {"id": "ground", "to": "all", "collect": "pieces", "prompt": "words", "next": "words"}
WORDS = {
    "id": "words",
    "kind": "tally",
    "of": "terms",
    "next": {"contested": "restate", "clear": "lock"},
}
RESTATE = {
    "id": "restate",
    "to": "contested",
    "collect": "pieces",
    "prompt": "again",
    "next": "words",
}
LOCK = {"id": "lock", "kind": "lock", "next": {"locked": "done", "empty": "nothing"}}
FRAME_ENDS = ({"id": "done", "end": "resolved"}, {"id": "nothing", "end": "rejected"})


def test_a_tally_validates_and_fills_its_round_cap():
    spec = _spec(FRAME, TALLY, GROUND, WORDS, RESTATE, LOCK, *FRAME_ENDS)
    assert spec.step("added").max_rounds == protocols.DEFAULT_MAX_ROUNDS["points"]
    assert spec.step("words").max_rounds == protocols.DEFAULT_MAX_ROUNDS["terms"]
    assert spec.step("frame").needs == "pieces"


@pytest.mark.parametrize(
    "extra",
    [{"to": "all"}, {"prompt": "hi"}, {"collect": "pieces"}, {"require": "pieces"}],
)
def test_a_tally_and_a_lock_ask_nobody(extra: dict):
    with pytest.raises(ValueError, match="asks nobody"):
        _spec(FRAME, TALLY | extra, GROUND, WORDS, RESTATE, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="asks nobody"):
        _spec(FRAME, TALLY, GROUND, WORDS, RESTATE, LOCK | extra, *FRAME_ENDS)


def test_a_tally_branches_only_on_what_it_reads():
    with pytest.raises(ValueError, match="needs of"):
        _spec(FRAME, {k: v for k, v in TALLY.items() if k != "of"}, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="branches on"):
        _spec(FRAME, TALLY | {"next": {"grew": "frame", "contested": "lock"}}, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="branches by map"):
        _spec(FRAME, TALLY | {"next": "lock"}, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="branches on"):
        _spec(FRAME | {"next": "lock"}, LOCK | {"next": {"feasible": "done"}}, *FRAME_ENDS)


def test_round_caps_belong_to_a_tally_and_labels_must_be_collected():
    with pytest.raises(ValueError, match="belong to a tally"):
        _spec(FRAME | {"max_rounds": 2}, TALLY, GROUND, WORDS, RESTATE, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="must collect them"):
        _spec(FRAME | {"collect": None}, TALLY, GROUND, WORDS, RESTATE, LOCK, *FRAME_ENDS)
    with pytest.raises(ValueError, match="belong to a select"):
        _spec(FRAME, TALLY | {"threshold": 0.5}, LOCK, *FRAME_ENDS)


def test_the_contested_are_asked_only_after_a_tally_of_words_on_every_path():
    with pytest.raises(ValueError, match="before any tally of terms"):
        _spec(RESTATE | {"next": "frame"}, FRAME, TALLY, GROUND, WORDS, LOCK, *FRAME_ENDS)
    # A tally of points defines nobody contested.
    with pytest.raises(ValueError, match="before any tally of terms"):
        _spec(
            FRAME,
            TALLY | {"next": {"grew": "restate", "settled": "ground", "empty": "nothing"}},
            RESTATE,
            GROUND,
            WORDS,
            LOCK,
            *FRAME_ENDS,
        )
    with pytest.raises(ValueError, match="only its contested edge"):
        _spec(
            FRAME,
            TALLY,
            GROUND,
            WORDS | {"next": {"contested": "lock", "clear": "restate"}},
            RESTATE,
            LOCK,
            *FRAME_ENDS,
        )


def test_nobody_can_play_the_contested():
    with pytest.raises(ValueError, match="cannot be named"):
        _spec(FRAME, TALLY, GROUND, WORDS, RESTATE, LOCK, *FRAME_ENDS, roles=["contested"])


def test_accord_has_no_roles_and_cannot_converge():
    accord = protocols.builtin("accord")
    assert accord is not None
    assert accord.roles == []
    assert all(s.end != "converged" for s in accord.steps)


def test_describe_says_what_a_tally_and_a_lock_do_in_plain_words():
    accord = protocols.builtin("accord")
    assert accord is not None
    text = protocols.describe(accord)
    assert (
        "- added: sees whether the last round added a point, up to 3 rounds; new points: "
        "more, nothing new: ground, nobody gave any: nothing"
    ) in text
    assert "- words: sees whether a word is used in different senses, at most 2 times" in text
    assert "- restate: asks whoever means a word differently, then words" in text
    assert "- lock: saves the shared summary; saved: locked, nothing to save: nothing" in text
    assert "roles:" not in text


def test_edge_line_says_nothing_for_a_step_that_asks_nobody():
    accord = protocols.builtin("accord")
    assert accord is not None
    assert protocols.edge_line(accord.step("added"), None, "") is None
    assert protocols.edge_line(accord.step("lock"), None, "") is None
