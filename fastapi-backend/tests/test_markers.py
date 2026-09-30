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
