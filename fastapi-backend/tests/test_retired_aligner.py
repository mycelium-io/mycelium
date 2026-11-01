# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A summon of the retired aligner is answered with what to run instead.

A room made before the aligner was retired can still hold an
``agents/aligner`` manifest; summoning it says, where it was asked, to use the
conductor's flows, never nothing.
"""

from __future__ import annotations

import asyncio

import pytest
import yaml

from app.services import message_format
from app.services.filesystem import ensure_room_structure, get_room_dir, write_memory_file
from app.services.message_models import Kind
from app.services.retired_aligner import RETIRED_TEXT, RetiredAligner
from tests.fakes import FakeChannel, FakeManaged, FakeManager

ROOM = "old-room"
THREAD = "urn:mycelium:episode:old-room:t1"


def _register(handle: str, body: dict) -> None:
    write_memory_file(
        get_room_dir(ROOM), f"agents/{handle}", yaml.safe_dump(body), created_by="julia"
    )


def _summon(sender: str = "julia"):
    return message_format.build_envelope(
        kind=Kind.exchange,
        episode=THREAD,
        sender=sender,
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
    )


async def _said(handle: str, sender: str = "julia") -> list[str]:
    channel = FakeChannel()
    engine = RetiredAligner(FakeManager(FakeManaged(room=ROOM, channel=channel)))  # type: ignore[arg-type]
    engine.handle_summon(ROOM, handle, _summon(sender))
    await asyncio.sleep(0)
    return [(extra or {}).get("content", "") for _env, extra in channel.sent]


@pytest.fixture(autouse=True)
def _room() -> None:
    ensure_room_structure(get_room_dir(ROOM))


@pytest.mark.asyncio
async def test_a_rooms_old_aligner_manifest_says_to_use_the_conductor():
    _register("mediator", {"adapter": "engine", "kind": "aligner"})
    assert await _said("mediator") == [RETIRED_TEXT]
    assert "board coordinate <row> conductor" in RETIRED_TEXT


@pytest.mark.asyncio
async def test_it_answers_in_the_thread_it_was_asked_in():
    _register("aligner", {"adapter": "engine", "kind": "aligner"})
    channel = FakeChannel()
    engine = RetiredAligner(FakeManager(FakeManaged(room=ROOM, channel=channel)))  # type: ignore[arg-type]
    engine.handle_summon(ROOM, "aligner", _summon())
    await asyncio.sleep(0)
    ((env, _extra),) = channel.sent
    assert env.header.message.episode == THREAD
    assert env.header.participants.actors[0].id == message_format.SYSTEM_ACTOR_ID


@pytest.mark.asyncio
async def test_the_usual_handle_with_no_manifest_still_gets_the_answer():
    assert await _said("aligner") == [RETIRED_TEXT]


@pytest.mark.asyncio
async def test_a_member_of_another_kind_is_left_alone():
    _register("aligner", {"adapter": "engine", "kind": "conductor"})
    _register("bob", {"adapter": "claude_code"})
    assert await _said("aligner") == []
    assert await _said("bob") == []


@pytest.mark.asyncio
async def test_it_never_answers_its_own_line():
    assert await _said("aligner", sender=message_format.SYSTEM_ACTOR_ID) == []
