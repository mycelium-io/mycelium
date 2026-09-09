"""Unit tests for SLIM-native coordination flow helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from libs.coordination_flow import (
    SUBKIND_CONVERGED,
    SUBKIND_REJECTED,
    TERMINAL_SUBKINDS,
    RoundSnapshot,
    _parse_l9_commit,
    collect_room_responses,
    poll_for_terminal_state,
    scan_for_terminal,
)


def _l9_commit_msg(subkind: str) -> dict:
    """Build a minimal l9_commit message."""
    return {
        "message_type": "l9_commit",
        "content": json.dumps({
            "l9": {"header": {"subkind": subkind}},
            "payload": {},
        }),
    }


# ── _parse_l9_commit ──────────────────────────────────────────────────────────


def test_parse_converged() -> None:
    msg = _l9_commit_msg("converged")
    result = _parse_l9_commit(msg)
    assert result is not None
    assert result["l9"]["header"]["subkind"] == "converged"


def test_parse_rejected() -> None:
    msg = _l9_commit_msg("rejected")
    result = _parse_l9_commit(msg)
    assert result is not None


def test_parse_non_terminal_subkind_returns_none() -> None:
    msg = _l9_commit_msg("in_progress")
    assert _parse_l9_commit(msg) is None


def test_parse_wrong_message_type_returns_none() -> None:
    msg = {"message_type": "broadcast", "content": "{}"}
    assert _parse_l9_commit(msg) is None


def test_parse_invalid_json_returns_raw() -> None:
    msg = {"message_type": "l9_commit", "content": "not-json-but-converged"}
    # Non-terminal (can't parse subkind) → None
    assert _parse_l9_commit(msg) is None


# ── scan_for_terminal ─────────────────────────────────────────────────────────


def test_scan_finds_converged() -> None:
    msgs = [
        {"message_type": "broadcast", "content": "hello"},
        _l9_commit_msg("converged"),
    ]
    result = scan_for_terminal(msgs)
    assert result is not None
    assert result["l9"]["header"]["subkind"] == "converged"


def test_scan_finds_rejected() -> None:
    msgs = [_l9_commit_msg("rejected")]
    assert scan_for_terminal(msgs) is not None


def test_scan_returns_none_when_absent() -> None:
    msgs = [{"message_type": "broadcast", "content": "nothing here"}]
    assert scan_for_terminal(msgs) is None


def test_scan_empty_list() -> None:
    assert scan_for_terminal([]) is None


# ── Terminal subkind constants ────────────────────────────────────────────────


def test_terminal_subkinds_nonempty() -> None:
    assert SUBKIND_CONVERGED in TERMINAL_SUBKINDS
    assert SUBKIND_REJECTED in TERMINAL_SUBKINDS


# ── RoundSnapshot ─────────────────────────────────────────────────────────────


def test_round_snapshot_all_responded_true() -> None:
    snap = RoundSnapshot(responses={"stub-a": 2, "stub-b": 1})
    assert snap.all_responded is True


def test_round_snapshot_all_responded_false_when_zero() -> None:
    snap = RoundSnapshot(responses={"stub-a": 1, "stub-b": 0})
    assert snap.all_responded is False


def test_round_snapshot_all_responded_false_when_empty() -> None:
    assert RoundSnapshot(responses={}).all_responded is False


def test_round_snapshot_total() -> None:
    snap = RoundSnapshot(responses={"a": 3, "b": 2})
    assert snap.total_responses() == 5


# ── collect_room_responses ────────────────────────────────────────────────────


def test_collect_counts_broadcast_per_handle() -> None:
    api = MagicMock()
    api.get_room_messages.return_value = (200, [
        {"message_type": "broadcast", "sender_handle": "stub-a", "content": "hi"},
        {"message_type": "broadcast", "sender_handle": "stub-a", "content": "hi2"},
        {"message_type": "broadcast", "sender_handle": "stub-b", "content": "yo"},
        {"message_type": "l9_commit", "sender_handle": "aligner", "content": "{}"},
    ])
    snap = collect_room_responses(api, "qa-room", ["stub-a", "stub-b"])
    assert snap.responses == {"stub-a": 2, "stub-b": 1}


def test_collect_ignores_non_broadcast() -> None:
    api = MagicMock()
    api.get_room_messages.return_value = (200, [
        {"message_type": "coordination_join", "sender_handle": "stub-a"},
    ])
    snap = collect_room_responses(api, "qa-room", ["stub-a"])
    assert snap.responses == {"stub-a": 0}


# ── poll_for_terminal_state ───────────────────────────────────────────────────


def test_poll_returns_on_converged_message() -> None:
    api = MagicMock()
    api.get_room_messages.return_value = (200, [
        _l9_commit_msg("converged"),
    ])
    result = poll_for_terminal_state(api, "qa-room", timeout=5, poll_interval=1)
    assert result is not None
    assert result["converged"] is True
    assert result["subkind"] == "converged"


def test_poll_returns_on_rejected_message() -> None:
    api = MagicMock()
    api.get_room_messages.return_value = (200, [
        _l9_commit_msg("rejected"),
    ])
    result = poll_for_terminal_state(api, "qa-room", timeout=5, poll_interval=1)
    assert result is not None
    assert result["converged"] is False
    assert result["subkind"] == "rejected"


def test_poll_returns_none_on_timeout() -> None:
    api = MagicMock()
    api.get_room_messages.return_value = (200, [
        {"message_type": "broadcast", "content": "nothing terminal"},
    ])
    result = poll_for_terminal_state(api, "qa-room", timeout=1, poll_interval=1)
    assert result is None


def test_poll_ignores_already_seen_messages() -> None:
    """If all messages are in seen_ids, should not return them."""
    api = MagicMock()
    msg = {**_l9_commit_msg("converged"), "id": "msg-1"}
    api.get_room_messages.return_value = (200, [msg])
    seen = {"msg-1"}
    result = poll_for_terminal_state(
        api, "qa-room", timeout=1, poll_interval=1, seen_message_ids=seen
    )
    assert result is None
