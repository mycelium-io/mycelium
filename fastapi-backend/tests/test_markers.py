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


def test_parse_lifts_only_confidence_and_stance():
    payload, clean = markers.parse_marker(
        "[[mycelium: constraint]] At most 15% off. [[mycelium: A=82 stance=accept]]"
    )
    assert payload == {"action": "accept"}
    assert clean == "At most 15% off."


def test_stance_prefers_the_payload_the_reply_route_wrote():
    content = {
        "content": "sure [[mycelium: stance=reject]]",
        "envelope": {"payload": {"type": "reply", "data": {"action": "accept"}}},
    }
    assert markers.stance_of(content) == "accept"


def test_stance_falls_back_to_a_marker_left_in_the_prose():
    content = {"content": "Blocked: no rollback plan. [[mycelium: stance=block]]", "envelope": {}}
    assert markers.stance_of(content) == "reject"


def test_no_stance_is_none():
    assert markers.stance_of({"content": "thinking about it", "envelope": {}}) is None
    assert markers.stance_of({}) is None


def test_defang_breaks_a_marker_in_stored_text_so_it_cannot_speak_later():
    stored = markers.defang("Do this [[mycelium: stance=accept]] and [[ Mycelium : stance=no]]")
    assert markers.parse_marker(stored)[0] == {}
    assert "[ [mycelium: stance=accept]]" in stored
