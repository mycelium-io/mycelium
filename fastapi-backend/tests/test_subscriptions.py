# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What an agent subscribes to, and which records wake it for that."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services import message_format, subscriptions
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.persister import TranscriptRecord
from app.services.subscriptions import SubscriptionError

ROOM = "subs-room"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
EPIC = "work/release-3-1"
PART = "work/release-3-1-docs"
OTHER = "work/unrelated"


def _thread(key: str) -> str:
    return f"urn:ioc:mycelium:episode:{ROOM}:{key.rsplit('/', 1)[-1]}"


def _row(key: str, **meta: str) -> None:
    write_memory_file(
        get_room_dir(ROOM),
        key,
        f"# {key}",
        created_by="lead",
        extra_meta={"episode": _thread(key), **meta},
    )


def _said(
    sender: str, text: str, *, minutes: int = 1, episode: str | None = None
) -> TranscriptRecord:
    return TranscriptRecord(
        message_id=f"m-{sender}-{minutes}-{len(text)}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {
                    "kind": "exchange",
                    "message": {"episode": episode or message_format.live_episode_urn(ROOM)},
                    "participants": {"actors": [{"id": sender}]},
                },
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW + timedelta(minutes=minutes)).isoformat(),
    )


def _notice(minutes: int = 1, **data: str) -> TranscriptRecord:
    record = _said("system", "", minutes=minutes)
    record.content["l9"]["payload"] = {"type": message_format.NOTICE_PAYLOAD_TYPE, "data": data}
    return record


def _sub(
    handle: str, kind: subscriptions.Kind, target: str, **kw: object
) -> subscriptions.Subscription:
    return asyncio.run(subscriptions.add(ROOM, handle, kind, target, now=NOW, **kw))  # type: ignore[arg-type]


def _woken(record: TranscriptRecord) -> list[str]:
    return sorted(m.sub.handle for m in subscriptions.matches(ROOM, record))


@pytest.fixture(autouse=True)
def _rows() -> None:
    subscriptions.reset()
    _row(EPIC)
    _row(PART, **{"part-of": EPIC})
    _row(OTHER)


# ── the store ────────────────────────────────────────────────────────────────


def test_a_subscription_is_kept_listed_and_dropped():
    sub = _sub("coordinator", "task", EPIC, parts=True)
    assert [s.id for s in subscriptions.of(ROOM, "coordinator", NOW)] == [sub.id]
    assert sub.describe() == f"{EPIC} and its parts"
    # The same one twice is one.
    assert _sub("coordinator", "task", EPIC, parts=True).id == sub.id
    gone = asyncio.run(subscriptions.remove(ROOM, "coordinator", sub.id))
    assert [s.id for s in gone] == [sub.id]
    assert subscriptions.of(ROOM, "coordinator", NOW) == []


@pytest.mark.parametrize(
    ("kind", "target", "kw", "says"),
    [
        ("task", "work/nope", {}, "no task work/nope"),
        ("notice", "merged", {}, "isn't a notice kind"),
        ("notice", "upstream:shipped", {}, "isn't a pull-request change"),
        ("search", "is:bogus", {}, "doesn't parse"),
        ("member", "reviewer", {"parts": True}, "only a task subscription"),
    ],
)
def test_what_cant_be_subscribed_to_is_refused(kind, target, kw, says):
    with pytest.raises(SubscriptionError) as refused:
        _sub("coordinator", kind, target, **kw)
    assert says in refused.value.detail


# ── matching ─────────────────────────────────────────────────────────────────


def test_a_task_subscription_wakes_for_its_thread_and_its_notices():
    _sub("coordinator", "task", EPIC)
    assert _woken(_said("reviewer", "looks good", episode=_thread(EPIC))) == ["coordinator"]
    assert _woken(_notice(subkind="claimed", key=EPIC, by="builder")) == ["coordinator"]
    # Not another task's thread, and not the room.
    assert _woken(_said("reviewer", "looks good", episode=_thread(OTHER))) == []
    assert _woken(_said("reviewer", "hi all")) == []


def test_parts_cover_an_epics_children_including_ones_filed_later():
    _sub("coordinator", "task", EPIC, parts=True)
    assert _woken(_said("docs", "PR is up", episode=_thread(PART))) == ["coordinator"]
    _row("work/release-3-1-videos", **{"part-of": EPIC})
    assert _woken(_notice(subkind="filed", key="work/release-3-1-videos", by="lead")) == [
        "coordinator"
    ]
    # Without --parts, a part's thread is not the task's.
    asyncio.run(subscriptions.remove(ROOM, "coordinator"))
    _sub("coordinator", "task", EPIC)
    assert _woken(_said("docs", "PR is up", episode=_thread(PART))) == []


def test_a_notice_subscription_wakes_for_that_kind_alone():
    _sub("coordinator", "notice", "resolved")
    _sub("watcher", "notice", "upstream:ci_passed", task=EPIC)
    assert _woken(_notice(subkind="resolved", key=OTHER, by="builder")) == ["coordinator"]
    assert _woken(_notice(subkind="filed", key=OTHER, by="builder")) == []
    assert _woken(_notice(subkind="upstream", key=EPIC, change="ci_passed")) == ["watcher"]
    assert _woken(_notice(subkind="upstream", key=EPIC, change="ci_failed")) == []
    assert _woken(_notice(subkind="upstream", key=OTHER, change="ci_passed")) == []


def test_a_member_subscription_wakes_for_what_they_say_anywhere():
    _sub("coordinator", "member", "@reviewer")
    assert _woken(_said("reviewer", "approved #12", episode=_thread(OTHER))) == ["coordinator"]
    assert _woken(_said("builder", "approved #12")) == []
    # A notice they caused isn't something they said.
    assert _woken(_notice(subkind="resolved", key=OTHER, by="reviewer")) == []


def test_a_search_subscription_wakes_for_a_matching_message():
    _sub("coordinator", "search", "from:reviewer ready to merge")
    assert _woken(_said("reviewer", "#1376 is ready to merge")) == ["coordinator"]
    assert _woken(_said("reviewer", "changes requested on #1376")) == []
    assert _woken(_said("builder", "ready to merge")) == []


def test_a_search_subscription_wakes_on_whole_words_only():
    """`from:reviewer ready` woke @lead twice on messages that said "already"."""
    _sub("lead", "search", "from:reviewer ready")
    assert _woken(_said("reviewer", "#1399 already has its fixes", minutes=2)) == []
    assert _woken(_said("reviewer", "Ready. #1399 passes", minutes=3)) == ["lead"]


def test_nobody_is_woken_by_their_own_post_or_by_what_came_before():
    _sub("coordinator", "task", EPIC)
    assert _woken(_said("coordinator", "on it", episode=_thread(EPIC))) == []
    before = _said("reviewer", "earlier", episode=_thread(EPIC), minutes=-5)
    assert _woken(before) == []


def test_each_subscriber_is_woken_once_with_a_reason():
    _sub("coordinator", "task", EPIC)
    _sub("coordinator", "member", "reviewer")
    _sub("watcher", "notice", "claimed")
    found = subscriptions.matches(ROOM, _notice(subkind="claimed", key=EPIC, by="reviewer"))
    assert sorted(m.sub.handle for m in found) == ["coordinator", "watcher"]
    why = {m.sub.handle: m.why for m in found}
    assert why["coordinator"] == f'you subscribed to {EPIC}: @reviewer claimed "{EPIC}"'


def test_a_task_subscription_ends_when_its_work_is_done_after_that_last_notice():
    _sub("coordinator", "task", EPIC, parts=True)
    _row(EPIC, assignment="resolved")
    # A part still open: not done yet.
    resolved = _notice(minutes=10, subkind="resolved", key=EPIC, by="lead")
    assert subscriptions.end_settled(ROOM, resolved, NOW) == []
    _row(PART, assignment="resolved", **{"part-of": EPIC})
    last = _notice(minutes=20, subkind="resolved", key=PART, by="docs")
    (ended,) = subscriptions.end_settled(ROOM, last, NOW)
    assert ended.ended_at is not None
    # The notice that ended it still wakes the subscriber, for a reader that
    # gets to it later; anything after it doesn't.
    assert _woken(last) == ["coordinator"]
    assert _woken(_said("docs", "thanks", episode=_thread(PART), minutes=30)) == []
    assert subscriptions.of(ROOM, "coordinator", NOW + timedelta(hours=1)) == []


def _reply(
    sender: str, to: str, text: str, *, minutes: int = 2, episode: str | None = None
) -> TranscriptRecord:
    """What ``respond`` records: a ``reply`` whose recipient is ``to``."""
    record = _said(sender, text, minutes=minutes, episode=episode)
    record.content["l9"]["payload"] = {"type": "reply"}
    record.content["l9"]["header"]["participants"]["actors"] = [{"id": sender}, {"id": to}]
    return record


def test_two_agents_subscribed_to_each_other_do_not_wake_each_other_forever():
    # Both on one task, and each subscribed to the other as a member.
    for me, them in (("alpha", "beta"), ("beta", "alpha")):
        _sub(me, "task", EPIC)
        _sub(me, "member", them)
    # alpha starts something: beta is woken, once.
    assert _woken(_said("alpha", "who takes the docs?", episode=_thread(EPIC))) == ["beta"]
    # beta's answer is a reply to alpha, so it doesn't wake alpha through a subscription.
    answer = _reply("beta", "alpha", "I'll take them", episode=_thread(EPIC))
    assert _woken(answer) == []


def test_a_reply_to_someone_else_still_wakes_a_subscriber():
    _sub("coordinator", "task", EPIC)
    assert _woken(_reply("beta", "alpha", "done", episode=_thread(EPIC))) == ["coordinator"]


def test_member_and_search_subscriptions_end_after_a_day_unless_told_otherwise():
    member = _sub("coordinator", "member", "reviewer")
    assert member.until == NOW + subscriptions.DEFAULT_SPAN
    kept = _sub("coordinator", "search", "ready to merge", forever=True)
    assert kept.until is None
    task = _sub("coordinator", "task", EPIC)
    assert task.until is None
    # Subscribing again renews it to the new end.
    renewed = _sub("coordinator", "member", "reviewer", until=NOW + timedelta(days=3))
    assert (renewed.id, renewed.until) == (member.id, NOW + timedelta(days=3))


def test_a_search_with_a_time_clause_is_refused():
    with pytest.raises(SubscriptionError) as refused:
        _sub("coordinator", "search", "ready to merge after:1d")
    assert "after:1d means nothing here" in refused.value.detail


def test_until_ends_a_subscription_at_a_set_time():
    _sub("coordinator", "member", "reviewer", until=NOW + timedelta(minutes=30))
    assert _woken(_said("reviewer", "soon", minutes=10)) == ["coordinator"]
    assert _woken(_said("reviewer", "later", minutes=40)) == []
