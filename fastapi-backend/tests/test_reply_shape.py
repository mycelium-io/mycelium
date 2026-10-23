# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Replies read against their schema, and what was read put on the message."""

from __future__ import annotations

from app.services import conductor, protocols, reply_shape
from app.services.persister import TranscriptRecord, stored_message_from_record

THREAD = "urn:ioc:mycelium:episode:demo:t1"


def _said(text: str) -> dict:
    return {"content": text}


def test_an_anchor_reply_is_read_and_a_bad_one_says_what_it_lacks():
    ok = reply_shape.read(
        "concord-anchor-reply",
        _said(
            "Here you go:\n```xml\n<concord-anchor-reply><raw_reject>8</raw_reject>"
            "<raw_ideal>95.5</raw_ideal><note>R&D cost < 5k</note></concord-anchor-reply>\n```"
        ),
    )
    assert (ok["protocol"], ok["phase"], ok["parsed"]) == ("concord", "ANCHOR", True)
    assert ok["value"] == {"raw_reject": 8.0, "raw_ideal": 95.5, "note": "R&D cost < 5k"}

    flipped = reply_shape.read(
        "concord-anchor-reply",
        _said(
            "<concord-anchor-reply><raw_reject>80</raw_reject><raw_ideal>20</raw_ideal></concord-anchor-reply>"
        ),
    )
    assert flipped["parsed"] is False
    assert flipped["missing"] == ["raw_ideal above raw_reject"]

    # Out of range is refused, never clamped.
    over = reply_shape.read(
        "concord-anchor-reply",
        _said(
            "<concord-anchor-reply><raw_reject>0</raw_reject><raw_ideal>120</raw_ideal></concord-anchor-reply>"
        ),
    )
    assert over["missing"] == ["raw_ideal, a number from 0 to 100"]
    assert "raw_ideal" not in over["value"]


def test_prose_with_no_element_is_kept_as_text_and_marked_unparsed():
    read = reply_shape.read("concord-candidate-reply", _said("I'd go with 10% off."))
    assert read["parsed"] is False
    assert read["missing"] == ["a <concord-candidate-reply> element"]
    assert read["value"] == {}


def test_a_candidate_reply_needs_its_rationale():
    read = reply_shape.read(
        "concord-candidate-reply",
        _said("<concord-candidate-reply><candidate>10% off</candidate></concord-candidate-reply>"),
    )
    assert read["value"] == {"candidate": "10% off"}
    assert read["missing"] == ["a rationale"]


def test_a_score_reply_has_to_score_every_candidate_asked_with_reasoning():
    text = (
        "<concord-score-reply>"
        '<score candidate_id="seed-a"><raw>82</raw><reasoning>cheap</reasoning></score>'
        '<score candidate_id="seed-b"><raw>41</raw></score>'
        "</concord-score-reply>"
    )
    read = reply_shape.read(
        "concord-score-reply",
        _said(text),
        candidates=["seed-a", "seed-b", "r1-c"],
        anchor=(10, 90),
    )
    assert read["parsed"] is False
    assert read["missing"] == ["reasoning for seed-b", "a score for r1-c"]
    # What was read is kept, with each score normalized on the member's own anchors.
    assert read["value"]["scores"] == [
        {"candidate_id": "seed-a", "raw": 82.0, "reasoning": "cheap", "normalized": 0.9},
        {"candidate_id": "seed-b", "raw": 41.0, "reasoning": "", "normalized": 0.3875},
    ]


def _run() -> conductor.Run:
    concord = protocols.builtin("concord")
    assert concord is not None
    return conductor.Run(protocol=concord, ask="pick", handles=["a", "b"], bound={}, episode=THREAD)


def _content(text: str, kind: str = "reply") -> dict:
    return {"l9": {"payload": {"type": kind, "data": {}}}, "content": text}


def test_the_reader_reads_only_a_reply_the_step_is_waiting_on():
    run = _run()
    read = conductor.ConductorEngine._reader(run)
    candidate = "<concord-candidate-reply><candidate>x</candidate><rationale>y</rationale></concord-candidate-reply>"
    run.asking = run.protocol.step("propose")
    assert read("a", _content(candidate)) is None, "nobody is waiting on a"
    run.waiting = {"a"}
    reply = read("a", _content(candidate))
    assert reply is not None
    assert reply["step"] == "propose"
    assert reply["value"] == {"candidate": "x", "rationale": "y", "candidate_id": "seed-a"}
    # The conductor's own posts and the thread's pings are never a reply.
    assert read("conductor", _content(candidate, kind="message")) is None
    assert read("a", _content(candidate, kind="ping")) is None
    # A repair is the REPAIR phase, and its candidate is named by its round.
    run.asking, run.again, run.repairs = run.protocol.step("repair"), True, {"pick": 1}
    reply = read("a", _content(candidate))
    assert reply is not None
    assert (reply["phase"], reply["again"], reply["value"]["candidate_id"]) == (
        "REPAIR",
        True,
        "r1-a",
    )


def test_what_was_read_rides_the_message_metadata_beside_the_conductor_line():
    content = _content("<concord-anchor-reply>…</concord-anchor-reply>")
    reply_shape.attach(content, {"schema": "concord-anchor-reply", "parsed": False})
    record = TranscriptRecord(
        message_id="m1",
        sender="a",
        kind="exchange",
        subkind=None,
        content=content,
        recorded_at="2026-10-23T20:00:00+00:00",
    )
    msg = stored_message_from_record("demo", record)
    assert msg is not None
    assert msg.event_metadata == {"reply": {"schema": "concord-anchor-reply", "parsed": False}}
