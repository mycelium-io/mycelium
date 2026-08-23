# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Additive message edit (issue #814).

An amendment is an ``exchange:amend`` message parented on the one it revises;
nothing in the transcript is rewritten. These cover the two halves: the read-path
fold (:func:`persister.collapse_amendments`) and the route that posts one.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.routes.messages import _read_messages
from app.services import l9, local_state, persister
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content


def _record(message_id: str, *, sender: str, text: str, amends: str | None = None):
    env = l9.build_envelope(
        kind=Kind.exchange,
        subkind=l9.AMEND_SUBKIND if amends else None,
        episode="urn:ioc:mycelium:episode:r:s",
        parents=[amends] if amends else None,
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic="urn:concept:mycelium:r",
        message_id=message_id,
        payload_type="reply",
    )
    return persister.record_from(env, serialize_content(env, extra={"content": text}))


def _row(sender: str, text: str, *, amends: str | None = None, minutes: int = 0):
    return local_state.StoredMessage(
        room_name="r",
        sender_handle=sender,
        message_type="broadcast",
        content=text,
        message_id=None,
        amends=amends,
        created_at=datetime.now(UTC) + timedelta(minutes=minutes),
    )


def test_amend_is_a_valid_exchange_subkind():
    l9.validate_subkind(Kind.exchange, l9.AMEND_SUBKIND)


def test_the_transcript_keeps_every_version(tmp_path, monkeypatch):
    """The fold is a read-time derivation: both texts stay on disk."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "amend-transcript-room"
    get_room_dir(room)
    persister.append_transcript(room, _record("m-1", sender="growth", text="TTL is 30s"))
    persister.append_transcript(
        room, _record("m-2", sender="growth", text="TTL is 300s", amends="m-1")
    )

    on_disk = [r.content["content"] for r in persister.load_transcript(room)]
    assert on_disk == ["TTL is 30s", "TTL is 300s"]

    served = _read_messages(room, None)
    assert [m.content for m in served] == ["TTL is 300s"]
    assert served[0].message_id == "m-1"  # the original row, revised in place on read
    assert served[0].edited_at is not None


def test_the_newest_amendment_wins():
    first = _row("growth", "one")
    first.message_id = "m-1"
    revisions = [
        _row("growth", "two", amends="m-1", minutes=1),
        _row("growth", "three", amends="m-1", minutes=2),
    ]

    folded = persister.collapse_amendments([first, *revisions])
    assert [m.content for m in folded] == ["three"]


def test_an_amendment_of_an_amendment_folds_into_the_original():
    first = _row("growth", "one")
    first.message_id = "m-1"
    second = _row("growth", "two", amends="m-1", minutes=1)
    second.message_id = "m-2"
    third = _row("growth", "three", amends="m-2", minutes=2)

    folded = persister.collapse_amendments([first, second, third])
    assert [m.content for m in folded] == ["three"]


def test_an_amendment_from_another_sender_does_not_fold():
    """Folding it would put someone else's words under the original author's name."""
    first = _row("growth", "one")
    first.message_id = "m-1"
    impostor = _row("ops", "not what I said", amends="m-1", minutes=1)

    folded = persister.collapse_amendments([first, impostor])
    assert [(m.sender_handle, m.content) for m in folded] == [
        ("growth", "one"),
        ("ops", "not what I said"),
    ]


def test_an_orphan_amendment_stays_visible():
    """Its target isn't in this view; dropping it would invent a deletion."""
    orphan = _row("growth", "correction", amends="m-gone")

    folded = persister.collapse_amendments([orphan])
    assert [m.content for m in folded] == ["correction"]
    assert folded[0].edited_at is None


def test_a_message_nobody_amended_is_untouched():
    plain = _row("growth", "one")

    folded = persister.collapse_amendments([plain])
    assert folded == [plain]


@pytest.mark.asyncio
async def test_amend_route_revises_what_the_room_reads(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "amend-route-room"
    get_room_dir(room)

    posted = await client.post(
        f"/api/rooms/{room}/messages",
        json={"sender_handle": "growth", "message_type": "broadcast", "content": "TTL is 30s"},
    )
    assert posted.status_code == 201
    message_id = posted.json()["id"]

    amended = await client.post(
        f"/api/rooms/{room}/messages/{message_id}/amend",
        json={"sender_handle": "growth", "content": "TTL is 300s"},
    )
    assert amended.status_code == 201
    assert amended.json()["content"] == "TTL is 300s"
    assert amended.json()["edited_at"] is not None
    assert amended.json()["id"] == message_id  # the revised message, not the amendment

    listed = await client.get(f"/api/rooms/{room}/messages")
    assert [m["content"] for m in listed.json()["messages"]] == ["TTL is 300s"]


@pytest.mark.asyncio
async def test_amend_accepts_an_unambiguous_id_prefix(client, tmp_path, monkeypatch):
    """The short id `mycelium room messages` prints is enough to name a message."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "amend-prefix-room"
    get_room_dir(room)

    posted = await client.post(
        f"/api/rooms/{room}/messages",
        json={"sender_handle": "growth", "message_type": "broadcast", "content": "first"},
    )
    short = posted.json()["id"][:8]

    amended = await client.post(
        f"/api/rooms/{room}/messages/{short}/amend",
        json={"sender_handle": "growth", "content": "revised"},
    )
    assert amended.status_code == 201
    assert amended.json()["content"] == "revised"


@pytest.mark.asyncio
async def test_only_the_sender_may_amend(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "amend-author-room"
    get_room_dir(room)

    posted = await client.post(
        f"/api/rooms/{room}/messages",
        json={"sender_handle": "growth", "message_type": "broadcast", "content": "mine"},
    )
    message_id = posted.json()["id"]

    refused = await client.post(
        f"/api/rooms/{room}/messages/{message_id}/amend",
        json={"sender_handle": "ops", "content": "not yours"},
    )
    assert refused.status_code == 403
    assert "growth" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_amending_an_unknown_message_is_a_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "amend-missing-room"
    get_room_dir(room)

    missing = await client.post(
        f"/api/rooms/{room}/messages/2b1c0d9e-8f7a-6b5c-4d3e-2f1a0b9c8d7e/amend",
        json={"sender_handle": "growth", "content": "into the void"},
    )
    assert missing.status_code == 404
