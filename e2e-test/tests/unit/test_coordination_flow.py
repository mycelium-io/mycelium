"""Unit tests for coordination flow helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from libs.coordination_flow import (
    AgentResponseSnapshot,
    AgentNegotiationSetup,
    collect_agent_responses,
    find_coordination_consensus,
    parse_session_room_from_cli,
    poll_for_consensus,
    poll_negotiation_completion,
    poll_room_consensus_outcome,
    setup_agent_driven_negotiation,
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


def test_find_coordination_consensus() -> None:
    messages = [
        {"message_type": "direct", "content": "{}"},
        {
            "message_type": "coordination_consensus",
            "content": json.dumps({"plan": "ship it", "broken": False}),
        },
    ]
    payload = find_coordination_consensus(messages)
    assert payload is not None
    assert payload["plan"] == "ship it"


def test_poll_negotiation_completion_via_session_state() -> None:
    api = MagicMock()
    api.get_coordination_sessions.return_value = (
        200,
        [
            {
                "display_name": "room:session:abc",
                "state": "complete",
            }
        ],
    )
    cli = MagicMock()
    result = poll_negotiation_completion(api, cli, "room", "room:session:abc")
    assert result is not None
    assert result["coordination_state"] == "complete"
    assert result["completion_source"] == "coordination_session"


def test_poll_room_consensus_outcome_via_failed_session() -> None:
    api = MagicMock()
    api.get_coordination_sessions.return_value = (
        200,
        [
            {
                "display_name": "room:session:abc",
                "state": "failed",
                "created_at": "2026-06-17T20:43:09Z",
            }
        ],
    )
    result = poll_room_consensus_outcome(api, "room")
    assert result is not None
    assert result["coordination_state"] == "failed"
    assert result["completion_source"] == "coordination_session"


def test_poll_room_consensus_outcome_scoped_ignores_other_sessions() -> None:
    """Session-scoped poll must not return a stale terminal session."""
    api = MagicMock()
    api.get_coordination_sessions.return_value = (
        200,
        [
            {
                "display_name": "room:session:old",
                "state": "failed",
                "created_at": "2026-06-18T21:01:02Z",
            },
            {
                "display_name": "room:session:new",
                "state": "negotiating",
                "created_at": "2026-06-18T21:11:01Z",
            },
        ],
    )
    api.get_room_messages.return_value = (200, [])

    parent_result = poll_room_consensus_outcome(api, "room")
    assert parent_result is not None
    assert parent_result["session_room"] == "room:session:old"

    scoped_result = poll_room_consensus_outcome(
        api,
        "room",
        session_room="room:session:new",
    )
    assert scoped_result is None


def test_poll_room_consensus_outcome_via_broken_consensus_message() -> None:
    api = MagicMock()
    api.get_coordination_sessions.return_value = (200, [])
    api.get_room_messages.return_value = (
        200,
        [
            {
                "message_type": "coordination_consensus",
                "content": json.dumps(
                    {
                        "plan": "Negotiation ended: timeout",
                        "broken": True,
                        "session": "room:session:xyz",
                    }
                ),
            }
        ],
    )
    result = poll_room_consensus_outcome(api, "room")
    assert result is not None
    assert result["coordination_state"] == "failed"
    assert result["completion_source"] == "coordination_consensus"


def test_setup_agent_driven_negotiation() -> None:
    api = MagicMock()
    cli = MagicMock()
    cli.session_create.return_value = MagicMock(ok=True, stdout='{"session_room":"room:session:abc"}')
    cli.session_join.return_value = MagicMock(ok=True)
    with patch("libs.coordination_flow.resolve_session_room", return_value="room:session:abc"):
        with patch("libs.coordination_flow.wait_for_message_type", return_value=True):
            setup = setup_agent_driven_negotiation(
                api,
                cli,
                "room",
                [("agent-alpha", "speed"), ("agent-beta", "quality")],
            )
    assert setup == AgentNegotiationSetup(
        session_room="room:session:abc",
        expected_handles=["agent-alpha", "agent-beta"],
    )


def test_poll_for_consensus_returns_on_first_terminal_outcome() -> None:
    api = MagicMock()
    with patch(
        "libs.coordination_flow.poll_room_consensus_outcome",
        side_effect=[None, {"coordination_state": "complete", "completion_source": "coordination_session"}],
    ):
        result = poll_for_consensus(api, "room", timeout=10, poll_interval=0)
    assert result is not None
    assert result["coordination_state"] == "complete"


def test_poll_for_consensus_passes_session_room() -> None:
    api = MagicMock()
    with patch(
        "libs.coordination_flow.poll_room_consensus_outcome",
        return_value={"coordination_state": "complete"},
    ) as poll_mock:
        poll_for_consensus(
            api,
            "room",
            session_room="room:session:abc",
            timeout=10,
            poll_interval=0,
        )
    poll_mock.assert_called_with(api, "room", session_room="room:session:abc")


def test_poll_negotiation_completion_via_consensus_message() -> None:
    api = MagicMock()
    api.get_coordination_sessions.return_value = (200, [])
    api.get_room_messages.return_value = (
        200,
        [
            {
                "message_type": "coordination_consensus",
                "content": json.dumps({"plan": "done"}),
            }
        ],
    )
    cli = MagicMock()
    result = poll_negotiation_completion(api, cli, "room", "room:session:xyz")
    assert result is not None
    assert result["coordination_state"] == "complete"
    assert result["completion_source"] == "coordination_consensus"
    assert result["consensus"]["plan"] == "done"
