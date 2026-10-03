# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a woken agent is told: why it woke, what changed, what asked for it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import l9, wake_digest
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.persister import TranscriptRecord

ROOM = "digest-room"
NOW = datetime(2026, 10, 1, 10, 44, tzinfo=UTC)
THREAD = "urn:ioc:mycelium:episode:digest-room:t1"


def _said(
    n: int, sender: str, text: str, minutes_ago: int, episode: str | None = None
) -> TranscriptRecord:
    ep = episode or l9.live_episode_urn(ROOM)
    return TranscriptRecord(
        message_id=f"m{n}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {
                    "kind": "exchange",
                    "message": {"episode": ep},
                    "participants": {"actors": [{"id": sender}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
    )


def _notice(n: int, minutes_ago: int) -> TranscriptRecord:
    record = _said(n, "system", "", minutes_ago)
    record.content["l9"]["payload"] = {"type": l9.NOTICE_PAYLOAD_TYPE}
    return record


LONG = (
    "Pulled 40 orders from last week where the total was off. Every one of them has at "
    "least three line items with a fractional tax, and the drift is always in the customer's "
    "favor, so we've been under-collecting rather than over-charging.\n\n@builder, can you "
    "take the fix? I'd round once on the order total like finance wants, and keep per-line "
    "amounts unrounded for display only. "
) * 3


def _task_thread() -> None:
    write_memory_file(
        get_room_dir(ROOM),
        "work/fix-the-receipt-tax",
        "# Fix the receipt tax\n\nTotals are off by a cent.",
        created_by="hay",
        extra_meta={
            "episode": THREAD,
            "assignment": "held",
            "owner": "builder",
            "claimed_at": (NOW - timedelta(hours=1)).isoformat(),
            "ttl_minutes": 600,
        },
    )


def test_a_mention_digest_says_why_what_changed_and_what_asked():
    _task_thread()
    records = [
        _said(1, "builder", "on it", 41),
        _said(2, "reviewer", "@builder I went through the receipt code. " + "x " * 300, 40, THREAD),
        _said(3, "hay", "unrelated chatter in the room", 30),
        _notice(4, 20),
        _said(5, "scout", LONG, 2, THREAD),
    ]
    digest = wake_digest.build(
        ROOM, {"handle": "builder", "reason": "mention", "from": "scout"}, records, NOW
    )

    assert digest.startswith("mycelium wake for @builder in digest-room\n")
    assert (
        'Why:     2 messages mention you in "Fix the receipt tax" (work/fix-the-receipt-tax), latest 2m ago'
        in digest
    )
    assert (
        "Since:   your last turn, 41m ago: 2 in this thread (@reviewer 1, @scout 1), 1 elsewhere in the room, 1 board move"
        in digest
    )
    assert 'Tasks:   claimed "Fix the receipt tax" (1h ago)' in digest
    # Each message says who, when and how long, and is cut with the rest counted.
    assert f"--- @scout, 2m ago, {len(LONG.strip()):,} chars, latest ---" in digest
    assert "--- @reviewer, 40m ago," in digest
    assert "chars]" in digest
    # The latest gets more room than the ones before it.
    blocks = digest.split("--- ")
    assert len(blocks[-1]) > len(blocks[-2])
    assert "First:  mycelium await --room digest-room --handle builder --json --timeout 5" in digest
    # The reply names the task, so it lands in its thread even without the await.
    assert (
        'Reply:  mycelium respond --room digest-room --handle builder --task work/fix-the-receipt-tax --body "..."'
        in digest
    )
    assert '(lands in "Fix the receipt tax")' in digest


def test_a_room_mention_replies_into_the_room():
    records = [_said(1, "hay", "@builder quick one: are you around?", 1)]
    digest = wake_digest.build(ROOM, {"handle": "builder", "from": "hay"}, records, NOW)
    assert "Why:     @hay mentioned you in the room (digest-room)" in digest
    assert (
        'Reply:  mycelium respond --room digest-room --handle builder --body "..."   (lands in the room)'
        in digest
    )


def test_a_delivered_wake_says_its_agent_is_responding(monkeypatch, tmp_path):
    from app.routes import sessions
    from app.services import activity, room_channels

    signals: list[tuple[str, str, str]] = []
    monkeypatch.setattr(activity, "signal", lambda r, h, s, **_: signals.append((r, h, s)))
    monkeypatch.setattr(sessions, "room_exists", lambda _r: True)
    monkeypatch.setattr(
        room_channels.manager,
        "drain_herdr_wakes",
        lambda _r: [{"handle": "builder", "reason": "mention", "from": "hay"}],
    )
    monkeypatch.setattr(room_channels.manager, "get", lambda _r: None)

    import asyncio

    body = asyncio.run(sessions.drain_herdr_wakes(ROOM))
    assert body["wakes"][0]["prompt"].startswith("mycelium wake for @builder")
    assert signals == [(ROOM, "builder", "responding")]


def test_a_task_filed_for_the_agent_says_how_to_take_it():
    digest = wake_digest.build(
        ROOM,
        {
            "handle": "builder",
            "reason": "assigned",
            "from": "operator",
            "key": "work/x",
            "title": "Do X",
        },
        [],
        NOW,
    )
    assert 'Why:     @operator gave you a task: "Do X" (work/x)' in digest
    assert "Since:   you joined" in digest
    assert "Claim:  mycelium board claim work/x --room digest-room --to @builder" in digest


def test_cut_counts_exactly_what_it_leaves_out():
    text = "word " * 100
    out = wake_digest.cut(text, 50)
    kept = out.split("… [+")[0]
    left = int(out.split("[+")[1].split(" ")[0].replace(",", ""))
    assert len(kept) + left == len(text.strip())
    assert wake_digest.cut("short", 50) == "short"
