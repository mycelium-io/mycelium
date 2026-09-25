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
