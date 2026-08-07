# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Self-rejoin: POST /sessions re-invites on every join, not just the first.

A connector announces itself on each (re)connect. So a member dropped while its
host slept must be re-invited by a *repeat* join — otherwise it sits reconnected-
but-uninvited until a human @mentions it. This pins that the SLIM invite fires on
the second join too (the durable inbox then re-serves its missed tail).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import room_channels


@pytest.mark.asyncio
async def test_repeat_join_reinvites(client, monkeypatch: pytest.MonkeyPatch) -> None:
    invites: list[str] = []
    monkeypatch.setattr(room_channels.manager, "provision", AsyncMock(return_value=None))
    monkeypatch.setattr(
        room_channels.manager,
        "invite_in_background",
        MagicMock(side_effect=lambda _room, handle: invites.append(handle)),
    )

    body = {"agent_handle": "growth"}
    first = await client.post("/api/rooms/rejoin-room/sessions", json=body)
    assert first.status_code == 201
    second = await client.post("/api/rooms/rejoin-room/sessions", json=body)
    assert second.status_code == 201

    # Both joins invite — the reconnect (2nd) is re-invited, not silently skipped.
    assert invites == ["growth", "growth"]
