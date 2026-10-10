# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a woken agent is told: why it woke, what changed, what asked for it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import message_format, wake_digest
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.persister import TranscriptRecord

ROOM = "digest-room"
NOW = datetime(2026, 10, 1, 10, 44, tzinfo=UTC)
THREAD = "urn:ioc:mycelium:episode:digest-room:t1"


def _said(
    n: int, sender: str, text: str, minutes_ago: int, episode: str | None = None
) -> TranscriptRecord:
    ep = episode or message_format.live_episode_urn(ROOM)
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


def _notice(n: int, minutes_ago: int, **data: str) -> TranscriptRecord:
    record = _said(n, "system", "", minutes_ago)
    record.content["l9"]["payload"] = {"type": message_format.NOTICE_PAYLOAD_TYPE, "data": data}
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
        _notice(
            4,
            20,
            subkind="claimed",
            key="work/fix-the-receipt-tax",
            title="Fix the receipt tax",
            by="builder",
        ),
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
        "Since:   your last turn, 41m ago: 2 in this thread (@reviewer 1, @scout 1), 1 elsewhere in the room\n"
        in digest
    )
    assert 'Tasks:   claimed "Fix the receipt tax" (1h ago)' in digest
    assert 'Board:   @builder claimed "Fix the receipt tax"\n         open now: 1 claimed' in digest
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
    # The last line says the whole room can be searched, not only paged.
    assert digest.splitlines()[-1].startswith(
        'Find:   mycelium room search "<words> from:<handle> task:<row> after:1d" --room digest-room'
    )


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


def _summary(key: str, flags: list[str]) -> None:
    write_memory_file(
        get_room_dir(ROOM),
        key,
        "# Shared summary: Fix the receipt tax\n",
        created_by="conductor",
        extra_meta={
            "contract": {"flags": [{"kind": "single", "text": t} for t in flags]},
            "relates-to": "work/fix-the-receipt-tax",
        },
    )


def test_a_wake_in_a_task_points_at_what_the_team_agreed_for_it():
    _task_thread()
    _summary(
        "context/summary/fix-the-receipt-tax",
        ["Only one person said this: p2 (hay)", "No answer from scout", "a", "b"],
    )
    records = [_said(1, "scout", "@builder can you take it?", 2, THREAD)]
    digest = wake_digest.build(ROOM, {"handle": "builder", "from": "scout"}, records, NOW)
    assert (
        "Agreed:  context/summary/fix-the-receipt-tax (shared summary); read it: mycelium "
        "memory get context/summary/fix-the-receipt-tax --room digest-room. Open items: "
        "Only one person said this: p2 (hay); No answer from scout; a and 1 more"
    ) in digest


def test_a_wake_with_nothing_agreed_says_nothing_about_it():
    digest = wake_digest.build(
        ROOM,
        {"handle": "builder", "reason": "assigned", "key": "work/never", "title": "Never"},
        [],
        NOW,
    )
    assert "Agreed:" not in digest


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


def _board_lines(digest: str) -> list[str]:
    lines = digest.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Board:"))
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith("         "))
    return [ln[9:] for ln in lines[start:end]]


def test_the_board_line_lists_what_changed_newest_first_then_whats_open():
    records = [
        _said(1, "builder", "back", 60),
        _notice(
            2,
            50,
            subkind="filed",
            key="work/a",
            title="Add Apple Pay",
            by="julia",
            kind="task",
            **{"for": "builder"},
        ),
        _notice(
            3,
            40,
            subkind="filed",
            key="decisions/b",
            title="Refund or support?",
            by="reviewer",
            kind="decision",
        ),
        _notice(4, 30, subkind="floor", key="t1", by="builder"),
        _notice(
            5, 20, subkind="expired", key="work/c", title="Hands-free voice mode", by="voice-model"
        ),
        _notice(6, 15, subkind="expired", key="work/d", title="Nobody held this", by="runtime"),
        _notice(
            7,
            10,
            subkind="resolved",
            key="work/e",
            title="Say 'the desktop app' everywhere in the docs and the app",
            by="schedule-ux",
        ),
    ]
    digest = wake_digest.build(ROOM, {"handle": "builder", "from": "julia"}, records, NOW)
    assert _board_lines(digest) == [
        "@schedule-ux resolved \"Say 'the desktop app' everywhere in the docs…\"",
        '"Nobody held this" expired',
        '"Hands-free voice mode" expired, @voice-model stopped renewing',
        '@reviewer filed a decision "Refund or support?"',
        '@julia filed "Add Apple Pay" for @builder',
        "open now: nothing open",
    ]
    # The changes are listed, so the count of them is no longer said.
    assert "board move" not in digest


def test_the_board_line_keeps_the_newest_changes_and_counts_the_rest():
    records = [_said(0, "builder", "back", 60)] + [
        _notice(n, 50 - n, subkind="claimed", key=f"work/t{n}", title=f"Task {n}", by="hay")
        for n in range(1, 9)
    ]
    lines = _board_lines(wake_digest.build(ROOM, {"handle": "builder"}, records, NOW))
    assert lines[:5] == [f'@hay claimed "Task {n}"' for n in (8, 7, 6, 5, 4)]
    assert lines[5:] == ["and 3 more", "open now: nothing open"]


def test_a_pull_request_changing_shares_the_board_list():
    # One list, newest first: a change to the agent's own row's pull request
    # sits between board changes and shares their cap; someone else's approval
    # is theirs, and a merge is everyone's.
    room_dir = get_room_dir(ROOM)
    write_memory_file(
        room_dir, "work/mine", "# Mine", created_by="hay", extra_meta={"assignee": "builder"}
    )
    write_memory_file(
        room_dir, "work/theirs", "# Theirs", created_by="hay", extra_meta={"assignee": "scout"}
    )
    pr = {"subkind": "upstream", "ref": "acme/shop#12"}
    records = [
        _said(0, "builder", "back", 60),
        _notice(1, 50, subkind="claimed", key="work/theirs", title="Theirs", by="scout"),
        _notice(2, 40, **pr, key="work/mine", title="Mine", change="ci_failed"),
        _notice(3, 30, **pr, key="work/theirs", title="Theirs", change="approved"),
        _notice(4, 20, **pr, key="work/theirs", title="Theirs", change="merged"),
        _notice(5, 10, **pr, key="work/mine", title="Mine", change="review_requested", who="ana"),
    ]
    lines = _board_lines(wake_digest.build(ROOM, {"handle": "builder"}, records, NOW))
    assert lines[:4] == [
        'review requested on "Mine" from @ana (acme/shop#12, 10m ago)',
        '"Theirs" merged (acme/shop#12, 20m ago)',
        'CI went red on "Mine" (acme/shop#12, 40m ago)',
        '@scout claimed "Theirs"',
    ]
    assert lines[4].startswith("open now: ")
    # An upstream notice is never printed as a board change.
    assert not any("upstream" in line for line in lines)


def test_a_pull_request_line_cuts_a_long_title_like_the_board_does():
    long = "Turn on Apple Pay for every customer in every region before the sale starts"
    line = wake_digest.upstream_line(
        {"change": "merged", "title": long, "ref": "acme/shop#12"}, NOW, NOW
    )
    cut_title = wake_digest._short(long, wake_digest.TITLE_CHARS)
    assert line == f'"{cut_title}" merged (acme/shop#12, now)'
    assert cut_title.endswith("…")


def test_the_tally_names_the_rows_someone_has_to_act_on():
    room_dir = get_room_dir(ROOM)
    for n in range(1, 6):
        write_memory_file(
            room_dir,
            f"work/drained-{n}",
            f"# Drained task {n}",
            created_by="hay",
            extra_meta={
                "assignment": "held",
                "owner": "voice-model",
                "claimed_at": (NOW - timedelta(hours=3)).isoformat(),
                "ttl_minutes": 30,
            },
        )
    write_memory_file(
        room_dir,
        "work/stuck",
        "# Waiting on the GitHub token",
        created_by="hay",
        extra_meta={"blocked_by": "julia"},
    )
    write_memory_file(room_dir, "work/fresh", "# A new one", created_by="hay")
    digest = wake_digest.build(ROOM, {"handle": "builder"}, [], NOW)
    (line,) = _board_lines(digest)
    assert line.startswith(
        "1 blocked (Waiting on the GitHub token), 1 new, 5 expired (Drained task "
    )
    assert line.endswith(" and 2 more)")
    # Nothing changed, so there is no list and no "open now:" in front of the tally.
    assert "open now:" not in digest


def test_cut_counts_exactly_what_it_leaves_out():
    text = "word " * 100
    out = wake_digest.cut(text, 50)
    kept = out.split("… [+")[0]
    left = int(out.split("[+")[1].split(" ")[0].replace(",", ""))
    assert len(kept) + left == len(text.strip())
    assert wake_digest.cut("short", 50) == "short"
