# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The position marker: lifted off a reply, and read back off a record."""

from __future__ import annotations

from app.services import markers


def test_parse_lifts_the_fields_and_strips_the_marker():
    payload, clean = markers.parse_marker(
        "I can live with 30%.\n\n[[mycelium: confidence=0.85 stance=accept]]"
    )
    assert payload == {"confidence": 0.85, "action": "accept"}
    assert clean == "I can live with 30%."


def test_parse_keeps_a_marker_only_text_rather_than_emptying_it():
    payload, clean = markers.parse_marker("[[mycelium: stance=reject]]")
    assert payload == {"action": "reject"}
    assert clean == "[[mycelium: stance=reject]]"


def test_parse_ignores_what_it_cannot_read():
    payload, _clean = markers.parse_marker("[[mycelium: confidence=high stance=maybe]]")
    assert payload == {}


def test_stance_prefers_the_payload_the_reply_route_wrote():
    content = {
        "content": "sure [[mycelium: stance=reject]]",
        "l9": {"payload": {"type": "reply", "data": {"action": "accept"}}},
    }
    assert markers.stance_of(content) == "accept"


def test_stance_falls_back_to_a_marker_left_in_the_prose():
    content = {"content": "Blocked: no rollback plan. [[mycelium: stance=block]]", "l9": {}}
    assert markers.stance_of(content) == "reject"


def test_no_stance_is_none():
    assert markers.stance_of({"content": "thinking about it", "l9": {}}) is None
    assert markers.stance_of({}) is None


# ── option ratings ────────────────────────────────────────────────────────────


def test_a_capital_letter_is_an_options_rating():
    payload, clean = markers.parse_marker("A is fine, B costs too much. [[mycelium: A=82 B=41]]")
    assert payload == {"scores": {"A": 82, "B": 41}}
    assert clean == "A is fine, B costs too much."


def test_a_lowercase_letter_is_not_a_rating():
    payload, _ = markers.parse_marker("[[mycelium: a=82 stance=accept]]")
    assert payload == {"action": "accept"}


def test_a_rating_out_of_range_or_not_whole_is_dropped_never_clamped():
    payload, _ = markers.parse_marker("[[mycelium: A=101 B=-1 C=8.5 D=70]]")
    assert payload == {"scores": {"D": 70}}


def test_ratings_ride_beside_the_stance_and_a_list_comma_is_not_part_of_one():
    payload, _ = markers.parse_marker("[[mycelium: A=82, B=41 stance=accept confidence=0.6]]")
    assert payload == {"scores": {"A": 82, "B": 41}, "action": "accept", "confidence": 0.6}


def test_scores_are_read_off_the_payload_first_then_the_prose():
    lifted = {"l9": {"payload": {"data": {"scores": {"A": 90}}}}, "content": "[[mycelium: A=10]]"}
    assert markers.scores_of(lifted) == {"A": 90}
    left_in_prose = {"l9": {}, "content": "B works for me [[mycelium: B=75]]"}
    assert markers.scores_of(left_in_prose) == {"B": 75}
    assert markers.scores_of({"content": "I like B a lot", "l9": {}}) == {}
    assert markers.scores_of({}) == {}


# ── labels: a marker that says what the text after it is ─────────────────────


def test_a_label_lifts_the_text_after_it_and_leaves_that_text_in_place():
    payload, clean = markers.parse_marker(
        "[[mycelium: constraint]] Refunds above 5000 need a person's approval.\n"
        "[[mycelium: out_of_scope]] Negotiating the price itself."
    )
    assert payload == {
        "pieces": [
            {"label": "constraint", "text": "Refunds above 5000 need a person's approval."},
            {"label": "out_of_scope", "text": "Negotiating the price itself."},
        ]
    }
    assert clean == ("Refunds above 5000 need a person's approval.\nNegotiating the price itself.")


def test_labelled_text_stops_at_a_blank_line():
    pieces = markers.labelled(
        "[[mycelium: objective]] Renew Acme.\nOn good terms.\n\nSome other remark."
    )
    assert pieces == [{"label": "objective", "text": "Renew Acme.\nOn good terms."}]


def test_words_checks_and_what_a_point_is_about():
    pieces = markers.labelled(
        '[[mycelium: term="hand off"]] Passing the account to the next owner.\n'
        "[[mycelium: check covers=P2, p4]] Finance signs off the limits first.\n"
        "[[mycelium: constraint about=pricing]] At most 15% off.\n"
        "[[mycelium: Out-Of-Scope]] Changing the tier."
    )
    assert pieces == [
        {"label": "term", "term": "hand off", "text": "Passing the account to the next owner."},
        {"label": "check", "covers": ["p2", "p4"], "text": "Finance signs off the limits first."},
        {"label": "constraint", "about": "pricing", "text": "At most 15% off."},
        {"label": "out_of_scope", "text": "Changing the tier."},
    ]


def test_a_label_repeated_is_two_pieces_and_a_label_with_no_text_is_none():
    pieces = markers.labelled(
        "[[mycelium: sub_goal]] Draft it.\n[[mycelium: sub_goal]] Send it.\n[[mycelium: assumption]]"
    )
    assert [p["text"] for p in pieces] == ["Draft it.", "Send it."]


def test_a_marker_that_labels_nothing_is_no_piece():
    assert markers.labelled("Fine by me. [[mycelium: stance=accept]]") == []
    assert markers.labelled("[[mycelium: whatever]] text") == []


def test_labels_leave_stances_and_ratings_as_they_were():
    payload, clean = markers.parse_marker(
        "[[mycelium: objective]] Renew Acme.\n\nA is fine. [[mycelium: A=82 stance=accept]]"
    )
    assert payload["scores"] == {"A": 82}
    assert payload["action"] == "accept"
    assert payload["pieces"] == [{"label": "objective", "text": "Renew Acme."}]
    assert clean == "Renew Acme.\n\nA is fine."


def test_pieces_are_read_off_the_payload_first_then_the_prose():
    lifted = {
        "l9": {
            "payload": {"data": {"pieces": [{"label": "objective", "text": "From the route."}]}}
        },
        "content": "[[mycelium: constraint]] Still in the prose.",
    }
    assert markers.pieces_of(lifted) == [{"label": "objective", "text": "From the route."}]
    typed = {"l9": {}, "content": "[[mycelium: constraint]] Typed by a person."}
    assert markers.pieces_of(typed) == [{"label": "constraint", "text": "Typed by a person."}]
    assert markers.pieces_of({"content": "no labels here", "l9": {}}) == []
    assert markers.pieces_of({}) == []


def test_malformed_pieces_on_the_payload_are_not_read():
    junk = {
        "l9": {
            "payload": {
                "data": {
                    "pieces": [
                        {"label": "objective", "text": "  "},
                        {"label": "nonsense", "text": "x"},
                        {"label": "term", "text": "no word"},
                        "not a dict",
                        {"label": "check", "text": "Look.", "covers": ["P1", 3]},
                    ]
                }
            }
        }
    }
    assert markers.pieces_of(junk) == [{"label": "check", "text": "Look.", "covers": ["p1"]}]


def test_defang_breaks_a_marker_in_stored_text_so_it_cannot_speak_later():
    stored = markers.defang("Do this [[mycelium: stance=accept]] and [[ Mycelium : A=99]]")
    assert markers.parse_marker(stored)[0] == {}
    assert "[ [mycelium: stance=accept]]" in stored
