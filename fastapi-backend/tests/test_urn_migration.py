# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The ``mycelium-3.1-names`` migration: a room recorded before 3.1 reads like a new one."""

from __future__ import annotations

import json

import pytest

from app.services import message_format, migrations, urn_migration
from app.services.filesystem import ensure_room_structure, get_data_dir, get_room_dir
from app.services.persister import load_transcript, record_episode

OLD_THREAD = "urn:ioc:mycelium:episode:ops:4f2a9c1e"
OLD_LIVE = "urn:ioc:mycelium:episode:ops:live"


def _old_record(episode: str, text: str) -> dict:
    return {
        "message_id": f"m-{text}",
        "sender": "juno",
        "kind": "exchange",
        "subkind": None,
        "recorded_at": "2026-10-01T12:00:00+00:00",
        "content": {
            "content": text,
            "l9": {
                "header": {
                    "protocol": "SSTP",
                    "subprotocol": "mycelium",
                    "version": "0.0.6",
                    "kind": "exchange",
                    "participants": {"actors": [{"id": "juno", "role": "agent"}], "groups": None},
                    "message": {"id": f"m-{text}", "parents": [], "episode": episode},
                    "context": {"topic": "urn:concept:mycelium:ops"},
                },
                "payload": {"type": "message", "data": {}},
            },
        },
    }


@pytest.fixture
def old_room():
    migrations.forget_seen()
    room = get_room_dir("ops")
    ensure_room_structure(room)
    (room / "log").mkdir(exist_ok=True)
    lines = [_old_record(OLD_LIVE, "hello"), _old_record(OLD_THREAD, "in the thread")]
    (room / "log" / "transcript.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8"
    )
    (room / "work").mkdir(exist_ok=True)
    (room / "work" / "ship-it.md").write_text(
        f"---\nepisode: {OLD_THREAD}\n---\nShip it.\n", encoding="utf-8"
    )
    return room


async def test_a_room_from_before_31_is_rewritten_once(old_room) -> None:
    assert await urn_migration.migrate_rooms(["ops"]) == 1
    text = (old_room / "log" / "transcript.jsonl").read_text(encoding="utf-8")
    assert "urn:ioc:" not in text
    assert "urn:concept:" not in text
    assert '"SSTP"' not in text
    assert '"0.0.6"' not in text
    assert "urn:mycelium:episode:ops:4f2a9c1e" in (old_room / "work" / "ship-it.md").read_text(
        encoding="utf-8"
    )
    records = load_transcript("ops")
    assert all(message_format.CONTENT_ENVELOPE_KEY in r.content for r in records)
    assert all("l9" not in r.content for r in records)
    assert message_format.is_live_episode("ops", record_episode(records[0]))
    assert record_episode(records[1]) == "urn:mycelium:episode:ops:4f2a9c1e"
    # Each file it changed was copied first, as it was.
    backup = get_data_dir() / urn_migration.BACKUP_DIR / "ops"
    assert "urn:ioc:" in (backup / "log" / "transcript.jsonl").read_text(encoding="utf-8")
    assert "urn:ioc:" in (backup / "work" / "ship-it.md").read_text(encoding="utf-8")
    # The ledger has it: a second start leaves the room alone.
    assert await urn_migration.migrate_rooms(["ops"]) == 0


async def test_a_message_that_quotes_the_old_key_keeps_its_text(old_room) -> None:
    transcript = old_room / "log" / "transcript.jsonl"
    quoting = _old_record(OLD_LIVE, 'the old shape was {"l9": {"header": {}}}')
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(quoting) + "\n")
    await urn_migration.migrate_rooms(["ops"])
    last = load_transcript("ops")[-1]
    assert last.content["content"] == 'the old shape was {"l9": {"header": {}}}'


def test_an_old_id_still_reads_as_the_new_one() -> None:
    assert message_format.canonical_urn(OLD_THREAD) == "urn:mycelium:episode:ops:4f2a9c1e"
    assert message_format.is_live_episode("ops", OLD_LIVE)
    assert message_format.canonical_urn("urn:mycelium:episode:ops:x") == (
        "urn:mycelium:episode:ops:x"
    )


def test_new_messages_carry_the_new_names() -> None:
    env = message_format.build_envelope(
        kind=message_format.Kind.exchange,
        episode=message_format.live_episode_urn("ops"),
        topic=message_format.topic_urn("ops"),
    )
    header = message_format.envelope_to_dict(env)["header"]
    assert (header["protocol"], header["version"]) == ("MYCP", "1.0.0")
    assert header["message"]["episode"] == "urn:mycelium:episode:ops:live"
    assert header["context"]["topic"] == "urn:mycelium:topic:ops"
