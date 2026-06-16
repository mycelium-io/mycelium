"""Unit tests for coordination flow helpers."""

from __future__ import annotations

import json

from libs.coordination_flow import (
    AgentResponseSnapshot,
    collect_agent_responses,
    parse_session_room_from_cli,
)


def test_parse_session_room_from_cli_top_level() -> None:
    stdout = json.dumps({"session_room": "room:session:abc123"})
    assert parse_session_room_from_cli(stdout, "room") == "room:session:abc123"


def test_parse_session_room_from_cli_nested() -> None:
    stdout = json.dumps({"session": {"display_name": "parent:session:xyz"}})
    assert parse_session_room_from_cli(stdout, "parent") == "parent:session:xyz"


def test_parse_session_room_from_cli_invalid() -> None:
    assert parse_session_room_from_cli("not-json", "room") is None


def test_collect_agent_responses_direct_messages() -> None:
    messages = [
        {"id": "1", "message_type": "coordination_tick", "content": "{}"},
        {
            "id": "2",
            "message_type": "direct",
            "sender_handle": "agent-alpha",
            "content": '{"action":"accept"}',
        },
        {
            "id": "3",
            "message_type": "direct",
            "sender_handle": "agent-beta",
            "content": '{"action":"accept"}',
        },
    ]
    snapshot = collect_agent_responses(messages, ["agent-alpha", "agent-beta"])
    assert snapshot.all_responded
    assert len(snapshot.responses["agent-alpha"]) == 1
    assert len(snapshot.responses["agent-beta"]) == 1


def test_collect_agent_responses_dedupes_by_id() -> None:
    messages = [
        {
            "id": "same",
            "message_type": "direct",
            "sender_handle": "agent-alpha",
            "content": "first",
        },
        {
            "id": "same",
            "message_type": "direct",
            "sender_handle": "agent-alpha",
            "content": "duplicate",
        },
    ]
    seen: set[str] = set()
    snapshot = collect_agent_responses(
        messages,
        ["agent-alpha"],
        seen_ids=seen,
    )
    assert snapshot.responses["agent-alpha"] == ["first"]


def test_agent_response_snapshot_all_responded_false_when_missing() -> None:
    snapshot = AgentResponseSnapshot(responses={"a": ["ok"], "b": []})
    assert not snapshot.all_responded
