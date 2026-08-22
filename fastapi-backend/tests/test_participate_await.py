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
from starlette.requests import Request

from app.routes import participate
from app.services import l9, persister
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content

# A bare ASGI request — ``authorize_handle`` is stubbed out, so the route never
# reads it; it exists only to satisfy the ``Request`` parameter type.
_REQUEST = Request({"type": "http", "method": "GET", "path": "/await", "headers": []})


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
    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
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
    first = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert first["message_id"] == "m1"

    second = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
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
    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert result["message"] is None


# ── the summon guard's wake gate (#summonguard) ──────────────────────────────


def _mention_record(message_id: str, *, text: str, sender: str = "avery"):
    """A broadcast that only *names* a handle in prose — no L9 recipient.

    This is the shape a guard is allowed to judge: nothing in the protocol
    addressed the handle, the wake comes purely from ``@handle`` in the text.
    """
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn("r", "live"),
        sender=sender,
        sender_role="human",
        topic=l9.topic_urn("r"),
        message_id=message_id,
        payload_type="message",
    )
    return persister.record_from(env, serialize_content(env, extra={"content": text}))


@pytest.fixture
def guarded(monkeypatch):
    """Install a summon filter returning a fixed decision map."""
    from app.services import summonguard
    from app.services.engine_events import SUMMON_FILTER, lifecycle

    def _install(decisions: dict[str, str]) -> None:
        async def _filter(ctx):
            summonguard.verdicts.put(
                summonguard.SummonVerdict(
                    room=ctx.room,
                    message_id=ctx.message_id,
                    sender=ctx.sender,
                    text=ctx.text,
                    decisions=decisions,
                )
            )
            return decisions

        lifecycle.install("r", SUMMON_FILTER, "watcher", _filter)

    yield _install
    lifecycle.clear()
    summonguard.verdicts.clear()


@pytest.mark.asyncio
async def test_await_skips_a_mention_the_guard_called_provenance(wired, guarded):
    """The guard's whole point: being named in passing is not a turn."""
    from app.services import summonguard

    log = persister.DeliveryLog()
    log.record(
        _mention_record("m1", text="shipped it, credit to @claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )
    wired(log)
    guarded({"claude-code-agent": "mention"})
    await summonguard.decide(
        summonguard.SummonContext(
            room="r",
            message_id="m1",
            sender="avery",
            text="shipped it, credit to @claude-code-agent",
            handles=("claude-code-agent",),
        )
    )

    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=1)
    assert result["message"] is None
    # The record was scanned and consumed, not merely out of the cursor's reach —
    # otherwise this would pass for a handle the poll never looked at.
    assert log.position("claude-code-agent") == 1


@pytest.mark.asyncio
async def test_await_serves_a_mention_the_guard_called_a_summon(wired, guarded):
    from app.services import summonguard

    text = "@claude-code-agent can you cost this out?"
    log = persister.DeliveryLog()
    log.record(
        _mention_record("m1", text=text), delivered_to=set(), recipients=["claude-code-agent"]
    )
    wired(log)
    guarded({"claude-code-agent": "wake"})
    await summonguard.decide(
        summonguard.SummonContext(
            room="r", message_id="m1", sender="avery", text=text, handles=("claude-code-agent",)
        )
    )

    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert result["message_id"] == "m1"


@pytest.mark.asyncio
async def test_a_protocol_addressed_tick_is_never_the_guards_to_judge(wired, guarded):
    """A mediator tick names the handle as an L9 recipient — that is a turn by
    construction, so a guard that would suppress it does not get asked."""
    log = persister.DeliveryLog()
    log.record(
        _addressed_record("m1", to="claude-code-agent"),
        delivered_to=set(),
        recipients=["claude-code-agent"],
    )
    wired(log)
    guarded({"claude-code-agent": "mention"})

    result = await participate.await_message("r", _REQUEST, handle="claude-code-agent", timeout=0)
    assert result["message_id"] == "m1"
