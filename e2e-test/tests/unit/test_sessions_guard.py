"""Unit tests for :mod:`libs.sessions` session-guard helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from libs.sessions import SessionError, wait_for_no_active_sessions, wait_for_session_terminal


class _FakeAPI:
    def __init__(self, base_url: str):
        self.responses: list[tuple[int, list[dict]]] = []

    def get_coordination_sessions(self, parent_room: str, limit: int = 50):
        if self.responses:
            return self.responses.pop(0)
        return 200, []


def test_wait_for_no_active_sessions_returns_when_clear():
    fake = _FakeAPI("http://localhost:8000")
    fake.responses = [(200, [{"state": "agreed", "parent_room_name": "scn-suite-abc"}])]

    with patch("libs.mycelium_api.MyceliumAPI", return_value=fake):
        wait_for_no_active_sessions("http://localhost:8000", "scn-suite-abc", timeout_seconds=1.0)


def test_wait_for_no_active_sessions_raises_when_stuck():
    fake = _FakeAPI("http://localhost:8000")
    fake.responses = [
        (200, [{"state": "negotiating", "parent_room_name": "scn-suite-abc"}]),
    ] * 10

    with patch("libs.mycelium_api.MyceliumAPI", return_value=fake):
        with pytest.raises(SessionError, match="active coordination session"):
            wait_for_no_active_sessions(
                "http://localhost:8000",
                "scn-suite-abc",
                timeout_seconds=0.1,
                poll_interval=0.05,
            )


def test_wait_for_session_terminal_returns_when_failed():
    fake = _FakeAPI("http://localhost:8000")
    fake.responses = [
        (
            200,
            [
                {
                    "display_name": "scn-suite-abc:session:dead",
                    "state": "failed",
                    "parent_room_name": "scn-suite-abc",
                }
            ],
        )
    ]

    with patch("libs.mycelium_api.MyceliumAPI", return_value=fake):
        wait_for_session_terminal(
            "http://localhost:8000",
            "scn-suite-abc",
            "scn-suite-abc:session:dead",
            timeout_seconds=1.0,
        )
