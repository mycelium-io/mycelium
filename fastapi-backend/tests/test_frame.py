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
