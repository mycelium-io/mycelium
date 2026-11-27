# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Emoji reactions on a message.

A reaction is an ``exchange:reaction`` message parented on the one it is on.
These cover the read-path fold (:func:`persister.collapse_reactions`), the route
that posts one, and how the message's author reads it on their next wake.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.routes.messages import _read_messages
from app.services import in_memory_store, message_format, persister, wake_digest
from app.services.filesystem import get_room_dir
from app.services.message_format import serialize_content
from app.services.message_models import Kind
from app.services.persister import TranscriptRecord

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)


def _record(
    message_id: str,
    *,
    sender: str,
    text: str,
    on: str | None = None,
    emoji: str = "👍",
    put_on: bool = True,
    minutes_ago: int = 0,
):
    env = message_format.build_envelope(
        kind=Kind.exchange,
        subkind=message_format.REACTION_SUBKIND if on else None,
        episode=message_format.live_episode_urn("r"),
        parents=[on] if on else None,
        sender=sender,
        recipients=[],
        topic="urn:mycelium:topic:r",
        message_id=message_id,
        payload_type="message",
    )
    extra: dict = {"content": text}
    if on:
        extra["reaction"] = {"emoji": emoji, "on": put_on}
    record = persister.record_from(env, serialize_content(env, extra=extra))
    record.recorded_at = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return record


def _row(sender: str, text: str, *, minutes: int = 0, **reaction):
    return in_memory_store.StoredMessage(
        room_name="r",
        sender_handle=sender,
        message_type="broadcast",
        content=text,
        created_at=NOW + timedelta(minutes=minutes),
        **reaction,
    )


def test_reaction_is_a_valid_exchange_subkind():
    message_format.validate_subkind(Kind.exchange, message_format.REACTION_SUBKIND)


def test_reactions_fold_into_their_message_and_never_show_as_rows():
    said = _row("builder", "Shipped the fix")
    said.message_id = "m-1"
    folded = persister.collapse_reactions(
        [
            said,
            _row("julia", "@~builder 👍", minutes=1, reacts="m-1", reaction="👍"),
            _row("lead", "@~builder 🎉", minutes=2, reacts="m-1", reaction="🎉"),
            _row("lead", "@~builder 👍", minutes=3, reacts="m-1", reaction="👍"),
        ]
    )
    assert [m.content for m in folded] == ["Shipped the fix"]
    assert folded[0].reactions == [
        {"emoji": "👍", "by": ["julia", "lead"]},
        {"emoji": "🎉", "by": ["lead"]},
    ]


def test_taking_a_reaction_off_removes_only_yours():
    said = _row("builder", "Shipped the fix")
    said.message_id = "m-1"
    folded = persister.collapse_reactions(
        [
            said,
            _row("julia", "@~builder 👍", minutes=1, reacts="m-1", reaction="👍"),
            _row("lead", "@~builder 👍", minutes=2, reacts="m-1", reaction="👍"),
            _row("julia", "👍", minutes=3, reacts="m-1", reaction="👍", reaction_on=False),
        ]
    )
    assert folded[0].reactions == [{"emoji": "👍", "by": ["lead"]}]


def test_a_reaction_to_a_message_out_of_view_is_dropped():
    folded = persister.collapse_reactions(
        [_row("julia", "@~builder 👍", reacts="gone", reaction="👍")]
    )
    assert folded == []


def test_the_transcript_keeps_each_reaction_and_the_read_folds_them(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "reaction-transcript-room"
    get_room_dir(room)
    persister.append_transcript(room, _record("m-1", sender="builder", text="Shipped the fix"))
    persister.append_transcript(
        room, _record("m-2", sender="julia", text="@~builder 🎉", on="m-1", emoji="🎉")
    )

    assert len(persister.load_transcript(room)) == 2
    served = _read_messages(room, None)
    assert [m.content for m in served] == ["Shipped the fix"]
    assert served[0].reactions == [{"emoji": "🎉", "by": ["julia"]}]


def test_a_reaction_is_not_chat():
    """So a schedule, a subscription or the wake's counts never read one as something said."""
    record = _record("m-2", sender="julia", text="@~builder 👍", on="m-1")
    assert persister._conversational_text(record.content) is None
    assert persister.reaction_text(record.content) == "@~builder 👍"


async def _post(client, room: str, sender: str, text: str) -> str:
    posted = await client.post(
        f"/api/rooms/{room}/messages",
        json={"sender_handle": sender, "message_type": "broadcast", "content": text},
    )
    assert posted.status_code == 201
    return posted.json()["id"]


@pytest.mark.asyncio
async def test_react_route_puts_an_emoji_on_and_takes_it_off(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "reaction-route-room"
    get_room_dir(room)
    message_id = await _post(client, room, "builder", "Shipped the fix")
    url = f"/api/rooms/{room}/messages/{message_id}/reactions"

    reacted = await client.post(url, json={"sender_handle": "julia", "emoji": "👍"})
    assert reacted.status_code == 201
    assert reacted.json()["id"] == message_id  # the message it's on, not the reaction
    assert reacted.json()["reactions"] == [{"emoji": "👍", "by": ["julia"]}]

    listed = await client.get(f"/api/rooms/{room}/messages")
    rows = listed.json()["messages"]
    assert [m["content"] for m in rows] == ["Shipped the fix"]
    assert rows[0]["reactions"] == [{"emoji": "👍", "by": ["julia"]}]

    taken = await client.post(url, json={"sender_handle": "julia", "emoji": "👍", "on": False})
    assert taken.status_code == 201
    assert taken.json()["reactions"] == []


@pytest.mark.asyncio
async def test_react_route_takes_only_an_emoji(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "reaction-words-room"
    get_room_dir(room)
    message_id = await _post(client, room, "builder", "Shipped the fix")
    url = f"/api/rooms/{room}/messages/{message_id}/reactions"

    words = await client.post(url, json={"sender_handle": "julia", "emoji": "nice"})
    assert words.status_code == 422
    missing = await client.post(
        f"/api/rooms/{room}/messages/nope-nope/reactions",
        json={"sender_handle": "julia", "emoji": "👍"},
    )
    assert missing.status_code == 404


def _named_block(digest: str) -> list[str]:
    lines = digest.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("Mentioned:")), None)
    if start is None:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith("   ")), len(lines)
    )
    return lines[start:end]


def test_the_author_reads_a_reaction_on_their_next_wake():
    room = "r"
    records: list[TranscriptRecord] = [
        _record("m-1", sender="builder", text="Shipped the fix\nmore detail", minutes_ago=60),
        _record("m-2", sender="julia", text="@~builder 🎉", on="m-1", emoji="🎉", minutes_ago=30),
        _record("m-3", sender="lead", text="@~builder 👀", on="m-1", emoji="👀", minutes_ago=20),
        _record(
            "m-4", sender="lead", text="👀", on="m-1", emoji="👀", put_on=False, minutes_ago=10
        ),
        _record("m-5", sender="julia", text="@builder look at this", minutes_ago=1),
    ]
    digest = wake_digest.build(room, {"handle": "builder", "from": "julia"}, records, NOW)
    assert _named_block(digest) == [
        "Mentioned: you were mentioned silently (@~) once since your last turn:",
        "         @julia reacted 🎉 · 30m ago · in the room, to: Shipped the fix"
        f"   (mycelium room messages {room} --id {wake_digest.short_id(records[0])})",
    ]
    # Reactions aren't something said, so the wake's count leaves them out.
    assert "Since:   your last turn, 1h ago: 1 in the room (@julia 1)" in digest
