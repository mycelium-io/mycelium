# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` delivers off the durable per-handle cursor (#649).

Node-free: the SLIM channel is faked so the test exercises only the delivery
logic — that a first ``await`` replays a message already sitting in the
transcript addressed to the handle (the reported bug), consumes it, and that the
cursor is the durable inbox's, not a process-local one.
"""

from __future__ import annotations

import pytest

from app.routes import participate
from app.services import l9, persister
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content


def _addressed_record(message_id: str, *, to: str, sender: str = "avery"):
    """A human exchange @-addressed to ``to`` (an L9 recipient, as the send path
    builds it), recorded as a transcript record."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn("r", "live"),
        sender=sender,
        sender_role="human",
        recipients=[to],
        topic=l9.topic_urn("r"),
        message_id=message_id,
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": f"@{to} hello"})
    return persister.record_from(env, content)


class _FakePersister:
    """Just enough of RoomPersister for the await loop: a durable log + the
    consume-side cursor advance (no disk write needed in the unit test)."""

    def __init__(self, log: persister.DeliveryLog) -> None:
        self.log = log

    def advance_cursor(self, handle: str, pos: int) -> None:
        self.log.advance(handle, pos)


class _Managed:
    def __init__(self, persister_: _FakePersister) -> None:
        self.persister = persister_


@pytest.fixture
def wired(monkeypatch):
    """Wire the await route to a fake room whose transcript we control."""

    def _wire(log: persister.DeliveryLog) -> None:
        managed = _Managed(_FakePersister(log))

        async def _provision(_room):
            return managed

        monkeypatch.setattr(participate, "room_exists", lambda _r: True)
        monkeypatch.setattr(participate.actor, "authorize_handle", lambda *a, **k: None)
        monkeypatch.setattr(participate.room_channels.manager, "provision", _provision)
        monkeypatch.setattr(
            participate.room_channels.manager, "refresh_lease", lambda *a, **k: None
        )
        # Keep the empty-poll cases from spinning the full long-poll window.
        monkeypatch.setattr(participate, "_POLL_INTERVAL_S", 0.01)

    return _wire


@pytest.mark.asyncio
async def test_first_await_replays_a_mention_sent_before_it(wired):
    """The repro: a message addressed to a fresh handle *before* its first await
    is delivered, not skipped at "now"."""
    # A mention broadcast anchors an untracked recipient's cursor at itself.
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )

    wired(log)
    result = await participate.await_message("r", object(), handle="claude-code-agent", timeout=0)
    assert result["message_id"] == "m1"
    assert result["prompt"] == "@claude-code-agent hello"


@pytest.mark.asyncio
async def test_await_consumes_the_message_it_serves(wired):
    """A served turn is not served again: the durable cursor advanced past it."""
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )

    wired(log)
    first = await participate.await_message("r", object(), handle="claude-code-agent", timeout=0)
    assert first["message_id"] == "m1"

    second = await participate.await_message("r", object(), handle="claude-code-agent", timeout=1)
    assert second["message"] is None  # consumed, nothing left


@pytest.mark.asyncio
async def test_await_ignores_turns_addressed_to_others(wired):
    """A handle only wakes on turns addressed to it — an observer broadcast to a
    peer is consumed silently, never returned."""
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="someone-else"),
        delivered_to=set(),
        recipients=["someone-else"],
    )

    wired(log)
    result = await participate.await_message("r", object(), handle="claude-code-agent", timeout=1)
    assert result["message"] is None
