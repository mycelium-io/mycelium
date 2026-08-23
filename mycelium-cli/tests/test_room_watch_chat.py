"""What the live tail (`mycelium room watch`) shows for chat and for an edit.

Chat reaches the tail two ways — the history replay's already-folded broadcast
and the live stream's raw L9 envelope — and both go through ``chat_line``.
"""

from __future__ import annotations

from mycelium.commands.room import chat_line


def _l9(text: str, *, subkind: str | None = None, parents: list[str] | None = None) -> dict:
    header: dict = {"kind": "exchange", "message": {"parents": parents or []}}
    if subkind:
        header["subkind"] = subkind
    return {"content": text, "l9": {"header": header, "payload": {"type": "message"}}}


def test_live_chat_is_unwrapped_from_its_envelope() -> None:
    """Without this the tail drops every live message: chat rides SSE as l9_exchange."""
    line = chat_line(
        "l9_exchange", {}, _l9("hello over the live channel"), "growth", "12:00:00", ""
    )

    assert line is not None
    assert "hello over the live channel" in line
    assert "growth" in line


def test_a_control_payload_carries_no_prose() -> None:
    assert chat_line("l9_exchange", {}, _l9(""), "growth", "12:00:00", "") is None


def test_a_live_amendment_reads_as_an_edit_of_what_it_revises() -> None:
    line = chat_line(
        "l9_exchange",
        {},
        _l9("the TTL is 300s", subkind="amend", parents=["a1b2c3d4-dead-beef-0000-000000000000"]),
        "growth",
        "12:00:00",
        "",
    )

    assert line is not None
    assert "edits" in line
    assert "a1b2c3d4" in line
    assert "the TTL is 300s" in line


def test_the_replayed_history_marks_a_revised_message_edited() -> None:
    """The backend folded it already; the tail just has to say it was revised."""
    line = chat_line(
        "broadcast",
        {"content": "the TTL is 300s", "edited_at": "2026-08-23T04:00:00+00:00"},
        {},
        "growth",
        "12:00:00",
        "",
    )

    assert line is not None
    assert "the TTL is 300s" in line
    assert "(edited)" in line


def test_a_message_nobody_amended_carries_no_marker() -> None:
    line = chat_line("broadcast", {"content": "plain"}, {}, "growth", "12:00:00", "")

    assert line is not None
    assert "(edited)" not in line
