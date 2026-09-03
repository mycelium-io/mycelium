# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The transcript-backed read path.

``GET /messages`` merges the durable transcript with the in-memory list store so
the room view survives a restart and both post paths converge. These exercise the
merge/dedup directly, node-free: they seed the transcript + list store and assert
what ``_read_messages`` returns.
"""

from datetime import UTC, datetime

from app.routes.messages import _read_messages
from app.services import in_memory_store, l9, persister
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
    """A restart wipes ``in_memory_store`` but not the transcript: the read path still
    returns the room's history."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "read-restart-room"
    get_room_dir(room)
    persister.append_transcript(room, _record("a-1", sender="growth", text="from before restart"))

    served = _read_messages(room, None)
    assert [m.content for m in served] == ["from before restart"]


def test_read_dedups_a_message_present_in_both_stores(tmp_path, monkeypatch):
    """A live message is in both the list store and the transcript; the read path
    shows it once (the list-store row wins, keeping its ledger fields and id)."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "read-dedup-room"
    get_room_dir(room)

    record = _record("a-1", sender="growth", text="hello")
    persister.append_transcript(room, record)
    mem_row = persister.stored_message_from_record(room, record)
    assert mem_row is not None
    in_memory_store.add_message(room, mem_row)

    served = _read_messages(room, None)
    assert len(served) == 1
    assert served[0].id == mem_row.id  # the list-store row, not a second disk copy


def test_read_merges_event_ledger_rows_that_only_live_in_memory(tmp_path, monkeypatch):
    """An event row (ttl/status) never rides the transcript; it must still surface
    alongside the transcript-backed chat."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "read-merge-room"
    get_room_dir(room)

    persister.append_transcript(room, _record("a-1", sender="growth", text="chat"))
    in_memory_store.add_message(
        room,
        in_memory_store.StoredMessage(
            room_name=room,
            sender_handle="github-poller",
            message_type="event",
            content="a PR opened",
            event_kind="source_event",
        ),
    )

    served = _read_messages(room, None)
    assert {m.content for m in served} == {"chat", "a PR opened"}


def _knowledge_record(message_id: str, *, key: str, recorded_at: str | None):
    """A raise-up ``knowledge`` record, optionally with its ``recorded_at`` stripped."""
    from app.services import memory_sync

    write = memory_sync.KnowledgeWrite(
        key=key,
        content="note",
        version=1,
        created_by="julia",
        updated_by="julia",
        updated_at="2026-08-19T09:48:00+00:00",
    )
    env = memory_sync.build_knowledge_envelope(
        room="r",
        write=write,
        recipients=[l9.SYSTEM_ACTOR_ID],
        subkind=memory_sync.MEMORY_WRITE_SUBKIND,
    )
    record = persister.record_from(
        env, serialize_content(env, extra={"content": f"memory updated → {key}"})
    )
    record.message_id = message_id
    record.recorded_at = recorded_at or ""
    return record


def _stamped(message_id: str, *, text: str, recorded_at: str):
    record = _record(message_id, sender="julia", text=text)
    record.recorded_at = recorded_at
    return record


def test_a_record_with_no_stamp_holds_its_place_instead_of_dating_to_now(tmp_path, monkeypatch):
    """A transcript line with no timestamp holds its place rather than sorting
    to the end of the feed."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "unstamped-room"
    get_room_dir(room)
    for record in (
        _stamped("c-1", text="morning", recorded_at="2026-08-19T09:00:00+00:00"),
        _knowledge_record("k-1", key="agents/590", recorded_at=None),
        _stamped("c-2", text="evening", recorded_at="2026-08-20T22:17:00+00:00"),
    ):
        persister.append_transcript(room, record)

    served = sorted(_read_messages(room, None), key=lambda m: m.created_at)

    # Beside the record it was appended after, not below the newest message.
    assert [m.message_type for m in served] == ["broadcast", "l9_knowledge", "broadcast"]
    assert served[1].created_at == served[0].created_at


def test_an_unstamped_record_reports_the_same_time_on_every_read(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "unstamped-stable-room"
    get_room_dir(room)
    persister.append_transcript(
        room, _stamped("c-1", text="morning", recorded_at="2026-08-19T09:00:00+00:00")
    )
    persister.append_transcript(room, _knowledge_record("k-1", key="agents/590", recorded_at=None))

    first = _read_messages(room, None)
    persister._conversational_cache.clear()
    second = _read_messages(room, None)

    assert [m.created_at for m in first] == [m.created_at for m in second]


def test_a_leading_unstamped_record_inherits_the_first_stamp_that_follows(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))
    in_memory_store.clear_all()
    room = "leading-unstamped-room"
    get_room_dir(room)
    persister.append_transcript(room, _knowledge_record("k-1", key="agents/590", recorded_at=None))
    persister.append_transcript(
        room, _stamped("c-1", text="morning", recorded_at="2026-08-19T09:00:00+00:00")
    )

    served = _read_messages(room, None)

    assert {m.created_at for m in served} == {datetime(2026, 8, 19, 9, 0, tzinfo=UTC)}
