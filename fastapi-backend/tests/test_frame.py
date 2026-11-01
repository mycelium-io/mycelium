# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The shared frame: labelled pieces merged in code, problems flagged, never resolved."""

from __future__ import annotations

from app.services import frame as framing

CAST = ["a", "b", "c"]


def _point(label: str, text: str, **extra: str) -> dict:
    return {"label": label, "text": text, **extra}


def test_equal_points_fold_and_keep_who_stated_them():
    frame = framing.Frame()
    out = framing.fold(
        frame,
        [
            ("a", [_point("objective", "Renew Acme.")]),
            ("b", [_point("objective", "renew   ACME.")]),
            ("c", [_point("constraint", "Renew Acme.")]),
        ],
        similar=None,
    )
    assert out.added == ["p1", "p2"]
    assert [(p.id, p.type, p.authors) for p in frame.points] == [
        ("p1", "objective", ["a", "b"]),
        ("p2", "constraint", ["c"]),
    ], "the same words under a different label are a different point"


def test_the_same_replies_in_the_same_order_give_the_same_ids():
    replies = [
        ("a", [_point("objective", "One."), _point("sub_goal", "Two.")]),
        ("b", [_point("sub_goal", "Two."), _point("deliverable", "Three.")]),
    ]
    first, second = framing.Frame(), framing.Frame()
    framing.fold(first, replies, similar=None)
    framing.fold(second, replies, similar=None)
    assert [(p.id, p.text) for p in first.points] == [(p.id, p.text) for p in second.points]


def test_single_and_conflict_are_flagged_and_both_sides_kept():
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("constraint", "At most 15% off.", about="pricing")]),
            ("b", [_point("constraint", "Up to 20% off.", about="Pricing")]),
            ("c", [_point("objective", "Renew.")]),
        ],
        similar=None,
    )
    made = framing.contract(frame, cast=CAST, ask="", task="work/x", title="X", similar=None)
    texts = [p["text"] for p in made["points"]]
    assert texts == ["At most 15% off.", "Up to 20% off.", "Renew."], "nothing dropped"
    assert made["points"][0]["flags"] == ["single", "conflict", "unchecked"]
    assert made["points"][1]["flags"] == ["single", "conflict", "unchecked"]
    kinds = [f["kind"] for f in made["flags"]]
    assert kinds.count("conflict") == 1
    # One open item for every point stated once, not one per point.
    (single,) = [f for f in made["flags"] if f["kind"] == "single"]
    assert single["text"] == "Every point was stated by only one person (3 points)"
    assert single["points"] == ["p1", "p2", "p3"]


def test_one_persons_two_points_about_a_subject_are_no_conflict():
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            (
                "a",
                [
                    _point("constraint", "At most 15% off.", about="pricing"),
                    _point("constraint", "Paid upfront.", about="pricing"),
                ],
            )
        ],
        similar=None,
    )
    made = framing.contract(frame, cast=["a"], ask="", task="", title="", similar=None)
    assert "conflict" not in [f["kind"] for f in made["flags"]]


def test_a_long_list_of_points_is_counted_not_spelled_out():
    frame = framing.Frame()
    framing.fold(
        frame,
        [("a", [_point("sub_goal", f"Part {n}.") for n in range(10)]), ("b", [])],
        similar=None,
    )
    made = framing.contract(frame, cast=["a", "b"], ask="", task="", title="", similar=None)
    (single,) = [f for f in made["flags"] if f["kind"] == "single"]
    assert single["text"] == "Every point was stated by only one person (10 points)"
    frame.points[0].authors.append("b")
    made = framing.contract(frame, cast=["a", "b"], ask="", task="", title="", similar=None)
    (single,) = [f for f in made["flags"] if f["kind"] == "single"]
    assert single["text"] == (
        "Only one person said this: p2, p3, p4, p5, p6, p7, p8, p9 and 1 more"
    )
    assert len(single["points"]) == 9


def test_a_members_later_meaning_replaces_its_earlier_one():
    frame = framing.Frame()
    framing.fold(
        frame, [("a", [{"label": "term", "term": "Renewal", "text": "Old."}])], similar=None
    )
    framing.fold(
        frame, [("a", [{"label": "term", "term": "renewal", "text": "New."}])], similar=None
    )
    assert frame.terms == {"renewal": ("Renewal", {"a": "New."})}


def test_equal_meanings_agree_and_different_ones_are_contested_never_merged():
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [{"label": "term", "term": "renewal", "text": "A new term."}]),
            ("b", [{"label": "term", "term": "renewal", "text": "a new term."}]),
            ("c", [{"label": "term", "term": "renewal", "text": "Any later contract."}]),
            ("a", [{"label": "term", "term": "lead", "text": "A prospect."}]),
        ],
        similar=None,
    )
    assert framing.contested(frame, None) == ["renewal"]
    assert framing.contested_members(frame, CAST, None) == ["a", "b", "c"]
    made = framing.contract(frame, cast=CAST, ask="", task="", title="", similar=None)
    renewal, lead = made["glossary"]
    assert renewal["status"] == "contested"
    assert renewal["meanings"] == [
        {"text": "A new term.", "members": ["a", "b"]},
        {"text": "Any later contract.", "members": ["c"]},
    ]
    assert lead["status"] == "agreed"


def test_one_sense_said_several_ways_is_one_sense_and_two_senses_stay_apart():
    """Meanings are compared at the meaning bar (lower than for points), and a
    meaning joins a sense when it matches anyone already in it."""
    scores = {
        frozenset({"End date, signed.", "Deadline to sign."}): 0.88,
        frozenset({"Deadline to sign.", "Date it must be in effect."}): 0.87,
        frozenset({"End date, signed.", "Date it must be in effect."}): 0.80,
        frozenset({"List price.", "End date, signed."}): 0.60,
    }

    def similar(x: str, y: str) -> float:
        return scores.get(frozenset({x, y}), 0.5)

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [{"label": "term", "term": "renewal date", "text": "End date, signed."}]),
            ("b", [{"label": "term", "term": "renewal date", "text": "Deadline to sign."}]),
            (
                "c",
                [{"label": "term", "term": "renewal date", "text": "Date it must be in effect."}],
            ),
            ("a", [{"label": "term", "term": "standard terms", "text": "List price."}]),
            ("b", [{"label": "term", "term": "standard terms", "text": "The template."}]),
        ],
        similar=similar,
    )
    assert [m for _t, m in framing.senses(frame, "renewal date", similar)] == [["a", "b", "c"]]
    assert framing.contested(frame, similar) == ["standard terms"]
    assert framing.MEANING_THRESHOLD <= framing.SIMILARITY_THRESHOLD


def test_a_meaning_that_matches_two_senses_joins_them_whatever_the_order():
    """a and c are further apart than the bar, b matches both: one sense,
    even though c answered before b."""
    scores = {
        frozenset({"Exit 2 with one line.", "One stderr line, status 2."}): 0.84,
        frozenset({"Exit 2 with one line.", "A short error, exit code 2."}): 0.88,
        frozenset({"One stderr line, status 2.", "A short error, exit code 2."}): 0.88,
    }

    def similar(x: str, y: str) -> float:
        return scores.get(frozenset({x, y}), 0.5)

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [{"label": "term", "term": "handle", "text": "Exit 2 with one line."}]),
            ("c", [{"label": "term", "term": "handle", "text": "One stderr line, status 2."}]),
            ("b", [{"label": "term", "term": "handle", "text": "A short error, exit code 2."}]),
        ],
        similar=similar,
    )
    assert [m for _t, m in framing.senses(frame, "handle", similar)] == [["a", "c", "b"]]
    assert framing.contested(frame, similar) == []


def test_one_point_said_three_ways_folds_and_a_different_point_stays_apart():
    """Scores shaped like a real run: one objective said three ways scored
    0.84-0.89 pairwise, and a different point on the same task 0.83. A new
    text joins a point when it nearly matches any text already in it; under
    the bar for saying nothing, the point keeps every wording and asks people
    to check they agree, rather than claiming one member said it."""
    one = "Reject a bad amount with a clear message."
    two = "A bad amount gives a clear error, not a crash."
    three = "Someone who mistypes an amount is told plainly what was wrong."
    other = "Fix the rounding so each share adds up to the total."
    scores = {
        frozenset({one, two}): 0.89,
        frozenset({two, three}): 0.89,
        frozenset({one, three}): 0.84,
        frozenset({one, other}): 0.83,
        frozenset({two, other}): 0.81,
        frozenset({three, other}): 0.80,
    }

    def similar(x: str, y: str) -> float:
        return scores.get(frozenset({x, y}), 0.5)

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("objective", one), _point("objective", other)]),
            ("b", [_point("objective", two)]),
            ("c", [_point("objective", three)]),
        ],
        similar=similar,
    )
    assert [(p.text, p.authors) for p in frame.points] == [(one, ["a", "b", "c"]), (other, ["a"])]
    made = framing.contract(
        frame, cast=["a", "b", "c"], ask="x", task="work/x", title="X", similar=similar
    )
    flagged = {f["kind"]: f["points"] for f in made["flags"] if "points" in f}
    assert flagged["single"] == ["p2"]
    assert flagged["reworded"] == ["p1"]
    assert made["points"][0]["wordings"] == [
        {"member": "a", "text": one},
        {"member": "b", "text": two},
        {"member": "c", "text": three},
    ]


def test_a_disagreement_embeddings_cant_tell_apart_is_never_shown_as_agreement():
    """'Rejects' and 'accepts' the same thing score 0.88 by embedding. They
    land on one point, but as two wordings to check, not one agreed line."""
    rejects = "Reject a negative tip with an error."
    accepts = "Accept a negative tip as a discount."

    def similar(_x: str, _y: str) -> float:
        return 0.88

    frame = framing.Frame()
    framing.fold(
        frame,
        [("a", [_point("constraint", rejects)]), ("b", [_point("constraint", accepts)])],
        similar=similar,
    )
    made = framing.contract(
        frame, cast=["a", "b"], ask="x", task="work/x", title="X", similar=similar
    )
    (point,) = made["points"]
    assert "reworded" in point["flags"]
    assert [w["text"] for w in point["wordings"]] == [rejects, accepts]
    shown = framing.render(made)
    assert f"  - a: {rejects}" in shown
    assert f"  - b: {accepts}" in shown
    assert "stated by 2 of 2" not in shown
    assert "Said in different words. Check they agree: p1" in shown
    assert "p1 (constraint) said in different words. Check they agree:" in framing.show_points(
        frame, ["a", "b"]
    )


def test_a_near_duplicate_over_the_bar_folds_without_a_flag():
    def similar(_x: str, _y: str) -> float:
        return 0.95

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("objective", "Renew Acme.")]),
            ("b", [_point("objective", "Renew the Acme deal.")]),
        ],
        similar=similar,
    )
    made = framing.contract(
        frame, cast=["a", "b"], ask="x", task="work/x", title="X", similar=similar
    )
    assert "reworded" not in made["points"][0]["flags"]
    assert "wordings" not in made["points"][0]
    assert all(f["kind"] != "reworded" for f in made["flags"])


def test_similarity_folds_near_duplicates_and_its_failure_falls_back_once():
    calls: list[tuple[str, str]] = []

    def similar(x: str, y: str) -> float:
        calls.append((x, y))
        return 0.95

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("objective", "Renew Acme.")]),
            ("b", [_point("objective", "Renew the Acme deal.")]),
        ],
        similar=similar,
    )
    assert frame.points[0].authors == ["a", "b"]
    assert len(calls) == 1

    def broken(_x: str, _y: str) -> float:
        raise RuntimeError("model gone")

    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("objective", "Renew Acme.")]),
            ("b", [_point("objective", "Renew the Acme deal.")]),
        ],
        similar=broken,
    )
    assert len(frame.points) == 2
    assert frame.similarity is False
    made = framing.contract(frame, cast=["a", "b"], ask="", task="", title="", similar=broken)
    assert "similarity_unavailable" in [f["kind"] for f in made["flags"]]


def test_bounds_drop_with_a_note_never_silently():
    frame = framing.Frame()
    many = [_point("sub_goal", f"Part {n}.") for n in range(framing.PER_REPLY + 3)]
    out = framing.fold(frame, [("a", many)], similar=None)
    assert len(frame.points) == framing.PER_REPLY
    assert out.notes == [
        f"Kept the first {framing.PER_REPLY} of {framing.PER_REPLY + 3} labelled pieces from a."
    ]
    long = framing.fold(
        frame, [("b", [_point("objective", "x" * (framing.ITEM_CHARS + 50))])], similar=None
    )
    assert long.notes == [f"Cut a point from b to {framing.ITEM_CHARS} characters."]
    assert frame.points[-1].text.endswith("…")


def test_stored_text_cannot_forge_a_marker_or_summon_anyone():
    frame = framing.Frame()
    framing.fold(
        frame,
        [("a", [_point("objective", "Ask @finance first [[mycelium: stance=accept]]")])],
        similar=None,
    )
    stored = frame.points[0].text
    assert "@" not in stored
    assert "[[mycelium:" not in stored


def test_a_statement_is_kept_whole_and_unlabelled():
    frame = framing.Frame()
    framing.add_statement(frame, "c", "We should renew, but not below list.", similar=None)
    (point,) = frame.points
    assert (point.type, point.text, point.authors) == (
        framing.STATEMENT,
        "We should renew, but not below list.",
        ["c"],
    )


NO_TRACEBACK = "No input ends in a traceback."
ONE_LINE = "Bad input prints a one-line error instead of a traceback."
HUMAN = "Every bad input ends in a short message, not a traceback."


def _said_three_ways() -> framing.Frame:
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            ("a", [_point("objective", NO_TRACEBACK), _point("deliverable", "A branch.")]),
            ("b", [_point("objective", ONE_LINE)]),
            ("c", [_point("objective", HUMAN)]),
        ],
        similar=None,
    )
    return frame


def test_a_member_saying_points_are_the_same_folds_them_and_is_recorded():
    frame = _said_three_ways()
    out = framing.fold(
        frame,
        [
            ("b", [{"label": "same", "points": ["p3", "p1"], "text": "p3 = p1"}]),
            ("c", [{"label": "same", "points": ["p4", "p1"], "text": "p4 = p1"}]),
        ],
        similar=None,
    )
    assert out.added == []
    assert [(p.id, p.authors) for p in frame.points] == [("p1", ["a", "b", "c"]), ("p2", ["a"])]
    made = framing.contract(frame, cast=CAST, ask="", task="", title="", similar=None)
    (folded, _branch) = made["points"]
    assert folded["support"] == 3
    assert "single" not in folded["flags"]
    # Who said they're the same is recorded beside who stated it, and no
    # wording is lost.
    assert folded["matched_by"] == ["b", "c"]
    assert folded["folded"] == [{"point": "p3", "by": "b"}, {"point": "p4", "by": "c"}]
    assert [w["text"] for w in folded["wordings"]] == [NO_TRACEBACK, ONE_LINE, HUMAN]
    body = framing.render(made)
    assert f"- **p1** {NO_TRACEBACK} (stated by 3 of 3: a, b, c)" in body
    assert "  - Folded in because members said they're the same: p3 (b), p4 (c)" in body
    assert f"  - b: {ONE_LINE}" in body
    shown = framing.show_points(frame, CAST)
    assert f"p1 (objective, stated by 3 of 3): {NO_TRACEBACK}" in shown
    assert "(folded in: p3 (b said it's the same), p4 (c said it's the same))" in shown
    # One member's say-so can't quietly merge a disagreement: a wrote p1 and
    # hasn't said these match, so it stays an open item.
    assert "folded" in folded["flags"]
    assert "- Folded because a member said they're the same. Check they agree: p1" in body


def test_a_fold_needs_no_check_once_every_author_has_named_it_or_it_was_their_own():
    frame = _said_three_ways()
    framing.fold(
        frame,
        [
            ("b", [{"label": "same", "points": ["p3", "p1"], "text": "p3 = p1"}]),
            ("c", [{"label": "same", "points": ["p4", "p1"], "text": "p4 = p1"}]),
            ("a", [{"label": "same", "points": ["p3", "p1"], "text": "p3 = p1"}]),
        ],
        similar=None,
    )
    made = framing.contract(frame, cast=CAST, ask="", task="", title="", similar=None)
    assert "folded" not in [f["kind"] for f in made["flags"]], "a, b and c all said so"

    own = framing.Frame()
    framing.fold(
        own,
        [
            ("a", [_point("objective", NO_TRACEBACK), _point("objective", ONE_LINE)]),
            ("a", [{"label": "same", "points": ["p2", "p1"], "text": "p2 = p1"}]),
        ],
        similar=None,
    )
    made = framing.contract(own, cast=CAST, ask="", task="", title="", similar=None)
    assert "folded" not in [f["kind"] for f in made["flags"]], "a folded its own two points"


def test_a_chain_folds_into_the_last_and_ids_stay_unique_after_a_fold():
    frame = _said_three_ways()
    framing.fold(
        frame,
        [("a", [{"label": "same", "points": ["p4", "p3", "p1"], "text": "p4 = p3 = p1"}])],
        similar=None,
    )
    assert [p.id for p in frame.points] == ["p1", "p2"]
    # A point added after a fold gets an id no point ever had.
    out = framing.fold(frame, [("b", [_point("constraint", "Exit 1.")])], similar=None)
    assert out.added == ["p5"]
    # A later line naming a point already folded names where it went.
    framing.fold(
        frame,
        [("c", [{"label": "same", "points": ["p3", "p1"], "text": "p3 = p1"}])],
        similar=None,
    )
    assert [p.id for p in frame.points] == ["p1", "p2", "p5"]


def test_a_check_on_a_folded_point_covers_the_point_it_went_into():
    frame = _said_three_ways()
    framing.fold(
        frame,
        [
            ("a", [{"label": "check", "text": "Run each case.", "covers": ["p3"]}]),
            ("b", [{"label": "same", "points": ["p3", "p1"], "text": "p3 = p1"}]),
            ("c", [{"label": "check", "text": "Diff stderr.", "covers": ["p4", "p3"]}]),
        ],
        similar=None,
    )
    framing.known_covers(frame)
    assert [(c.text, c.covers) for c in frame.checks] == [
        ("Run each case.", ["p1"]),
        ("Diff stderr.", ["p4", "p1"]),
    ]


def test_naming_a_point_that_isnt_there_folds_nothing_and_says_so():
    frame = _said_three_ways()
    out = framing.fold(
        frame,
        [("b", [{"label": "same", "points": ["p9", "p1"], "text": "p9 = p1"}])],
        similar=None,
    )
    assert len(frame.points) == 4
    assert out.notes == ["b said p9 matched a point, but there's no such point."]


def test_checks_cover_points_and_the_rest_are_unchecked():
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            (
                "a",
                [
                    _point("objective", "Renew."),
                    _point("deliverable", "A signed form."),
                    _point("assumption", "Acme wants to stay."),
                    {"label": "check", "text": "Finance signs.", "covers": ["p2", "p9"]},
                ],
            )
        ],
        similar=None,
    )
    framing.known_covers(frame)
    made = framing.contract(frame, cast=["a"], ask="", task="", title="", similar=None)
    assert made["checks"] == [{"text": "Finance signs.", "covers": ["p2"], "owner": "a"}]
    assert made["unchecked"] == ["p1"], "an assumption is not something a check covers"


def test_a_member_who_never_answered_is_flagged_quiet():
    frame = framing.Frame()
    framing.fold(frame, [("a", [_point("objective", "Renew.")]), ("b", [])], similar=None)
    made = framing.contract(frame, cast=CAST, ask="", task="", title="", similar=None)
    assert {"kind": "quiet_member", "text": "No answer from c", "members": ["c"]} in made["flags"]


def test_render_lists_points_words_checks_and_open_items_in_plain_words():
    frame = framing.Frame()
    framing.fold(
        frame,
        [
            (
                "a",
                [
                    _point("objective", "Renew."),
                    {"label": "term", "term": "renewal", "text": "New term."},
                ],
            ),
            ("b", [_point("objective", "Renew."), _point("out_of_scope", "Pricing.")]),
        ],
        similar=None,
    )
    made = framing.contract(
        frame, cast=["a", "b"], ask="Agree it", task="work/x", title="Renew Acme", similar=None
    )
    text = framing.render(made)
    assert text.startswith("# Shared summary: Renew Acme\n")
    assert "## What it's for\n\n- **p1** Renew. (stated by 2 of 2: a, b)" in text
    assert "## Out of scope" in text
    assert "- **renewal**: New term. (a)" in text
    assert "## Open items" in text
    assert "- Only one person said this: p2" in text
    assert "contract" not in text.lower()
    assert "—" not in text
