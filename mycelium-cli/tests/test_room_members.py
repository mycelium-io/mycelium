# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium room members``: who is in a room and what each one is doing now.

Everyone the room knows (its people, agents and engines, from
``/rooms/{room}/members``) with each one's state from the hub's live presence
(``/rooms/{room}/sessions/members``)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium.commands import room as room_cmd
from tests.hub_answers import ok

runner = CliRunner()

MEMBERS_SYNC = (
    "mycelium_backend_client.api.members.list_members_api_rooms_room_name_members_get.sync_detailed"
)
PRESENCE_SYNC = "mycelium_backend_client.api.sessions.list_members_api_rooms_room_name_sessions_members_get.sync_detailed"


@pytest.fixture(autouse=True)
def _hub(backend, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from mycelium_backend_client.models import RoomMembers, RoomPresenceRead

    backend(room_cmd, room="demo", active_room="demo")
    known = RoomMembers.from_dict(
        {
            "people": [
                {"handle": "avery", "joined_at": "2026-10-01T10:00:00+00:00", "via": "added"},
                {"handle": "sam", "joined_at": "2026-10-01T10:00:00+00:00", "via": "added"},
            ],
            "agents": [
                {"handle": "coder", "owner": "avery"},
                {"handle": "scout", "owner": "avery"},
                {"handle": "quiet", "owner": "sam"},
            ],
            "engines": [{"handle": "conductor", "owner": None}],
            # Running `await` without ever being registered.
            "others": [{"handle": "drifter", "holds_task": False, "present": True}],
        }
    )
    live = RoomPresenceRead.from_dict(
        {
            "members": [
                {"handle": "avery", "kind": "lease"},
                {"handle": "drifter", "kind": "lease", "status": "working"},
                {"handle": "coder", "kind": "lease", "status": "working", "wake_pending": True},
                {
                    "handle": "scout",
                    "kind": "lease",
                    "status": "idle",
                    "can_reply": False,
                    "cant_reply_why": "This computer isn't signed in to the hub (laptop).",
                },
            ],
            "floors": [],
            "subscriptions": [],
            "paused": [],
        }
    )
    monkeypatch.setattr(MEMBERS_SYNC, lambda *_a, **_k: ok(known))
    monkeypatch.setattr(PRESENCE_SYNC, lambda *_a, **_k: ok(live))


def _rows() -> dict[str, dict[str, Any]]:
    result = runner.invoke(room_cmd.app, ["members", "--room", "demo", "--json"])
    assert result.exit_code == 0, result.output
    return {r["handle"]: r for r in json.loads(result.output)}


def test_everyone_the_room_knows_with_what_each_is_doing():
    rows = _rows()
    assert {h: (r["kind"], r["status"]) for h, r in rows.items()} == {
        "avery": ("person", "here"),
        "sam": ("person", "away"),
        "coder": ("agent", "working"),
        "scout": ("agent", "idle"),
        "quiet": ("agent", "away"),
        "conductor": ("engine", "on call"),
        "drifter": ("other", "working"),
    }
    assert rows["coder"]["wake_pending"] is True
    assert rows["coder"]["owner"] == "avery"


def test_an_agent_that_cant_post_says_so_and_why():
    rows = _rows()
    assert rows["scout"]["can_reply"] is False
    assert "isn't signed in" in rows["scout"]["cant_reply_why"]
    assert rows["quiet"]["can_reply"] is None

    table = runner.invoke(room_cmd.app, ["members", "--room", "demo"], terminal_width=200)
    assert table.exit_code == 0, table.output
    line = next(ln for ln in table.output.splitlines() if "@scout" in ln)
    assert "can't reply" in line
