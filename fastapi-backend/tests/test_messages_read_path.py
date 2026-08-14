# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The transcript-backed read path (issue #497 §3).

``GET /messages`` merges the durable transcript with the in-memory list store so
the room view survives a restart and both post paths converge. These exercise the
merge/dedup directly, node-free: they seed the transcript + list store and assert
what ``_read_messages`` returns.
"""

from app.routes.messages import _read_messages
from app.services import l9, local_state, persister
from app.services.filesystem import get_room_dir
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content


def _record(message_id: str, *, sender: str, text: str):
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode="urn:ioc:mycelium:episode:r:s",
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic="urn:concept:mycelium:r",
        message_id=message_id,
        payload_type="reply",
    )
    return persister.record_from(env, serialize_content(env, extra={"content": text}))


def test_read_serves_the_transcript_when_memory_is_empty(tmp_path, monkeypatch):
    """A restart wipes ``local_state`` but not the transcript: the read path still
    returns the room's history."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "read-restart-room"
    get_room_dir(room)
    persister.append_transcript(room, _record("a-1", sender="growth", text="from before restart"))

    served = _read_messages(room, None)
    assert [m.content for m in served] == ["from before restart"]


def test_read_dedups_a_message_present_in_both_stores(tmp_path, monkeypatch):
    """A live message is in both the list store and the transcript; the read path
    shows it once (the list-store row wins, keeping its ledger fields and id)."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "read-dedup-room"
    get_room_dir(room)

    record = _record("a-1", sender="growth", text="hello")
    persister.append_transcript(room, record)
    mem_row = persister.stored_message_from_record(room, record)
    assert mem_row is not None
    local_state.add_message(room, mem_row)

    served = _read_messages(room, None)
    assert len(served) == 1
    assert served[0].id == mem_row.id  # the list-store row, not a second disk copy


def test_read_merges_event_ledger_rows_that_only_live_in_memory(tmp_path, monkeypatch):
    """An event row (ttl/status) never rides the transcript; it must still surface
    alongside the transcript-backed chat."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    local_state.clear_all()
    room = "read-merge-room"
    get_room_dir(room)

    persister.append_transcript(room, _record("a-1", sender="growth", text="chat"))
    local_state.add_message(
        room,
        local_state.StoredMessage(
            room_name=room,
            sender_handle="github-poller",
            message_type="event",
            content="a PR opened",
            event_kind="source_event",
        ),
    )

    served = _read_messages(room, None)
    assert {m.content for m in served} == {"chat", "a PR opened"}
