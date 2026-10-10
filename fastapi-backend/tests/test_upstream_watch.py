# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A linked pull request changing, said on its row's timeline and in the digest.

The watcher compares each answer with the last one the room saw and raises an
``upstream`` notice for what changed. These cover what makes that honest: the
first answer is a baseline, the last answer survives a restart, a change is
told once on one row, and nothing about it wakes anyone.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.services import message_format, wake_digest
from app.services.persister import TranscriptRecord
from app.services.status import watch
from app.services.status.providers.github import changes, first
from app.services.status.runtime import StatusRuntime
from app.services.status.types import (
    FetchOutcome,
    FetchSucceeded,
    Ref,
    UpstreamChange,
    UpstreamState,
)

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
ROOM = "shop"
THREAD = "urn:ioc:mycelium:episode:shop:t1"


# ── what GitHub changes read as ──────────────────────────────────────────────


def _pr(**over: Any) -> dict[str, Any]:
    base = {"pr": "OPEN", "ci": "PENDING", "review": "REVIEW_REQUIRED", "requested": []}
    return {**base, **over}


def test_only_crossings_count():
    assert changes(_pr(ci="FAILURE"), _pr(ci="FAILURE")) == []
    assert changes(_pr(ci="PENDING"), _pr(ci="FAILURE")) == [UpstreamChange("ci_failed")]
    assert changes(_pr(ci="FAILURE"), _pr(ci="SUCCESS")) == [UpstreamChange("ci_passed")]
    assert changes(_pr(ci="PENDING"), _pr(ci="SUCCESS")) == [UpstreamChange("ci_passed")]
    assert changes(_pr(), _pr(review="APPROVED")) == [UpstreamChange("approved")]
    assert changes(_pr(), _pr(review="CHANGES_REQUESTED")) == [UpstreamChange("changes_requested")]


def test_a_review_asked_names_who_it_was_asked_of():
    before, after = _pr(requested=["ana"]), _pr(requested=["ana", "bo", "core-team"])
    assert changes(before, after) == [UpstreamChange("review_requested", ("bo", "core-team"))]


def test_a_merge_says_all_there_is_to_say():
    assert changes(_pr(), _pr(pr="MERGED", ci="SUCCESS", review="APPROVED")) == [
        UpstreamChange("merged")
    ]
    assert changes(_pr(), _pr(pr="CLOSED")) == [UpstreamChange("closed")]
    # A closed one that stays closed, or a reading from before `pr` was kept, is not news.
    assert changes(_pr(pr="CLOSED"), _pr(pr="CLOSED")) == []
    assert changes({"ci": "PENDING"}, _pr(pr="MERGED")) == []


def test_a_reading_from_before_requested_was_kept_is_not_a_request():
    assert changes({"pr": "OPEN", "ci": "PENDING"}, _pr(requested=["ana"])) == []


def _created(ago: timedelta) -> str:
    return (NOW - ago).isoformat()


def test_only_a_pull_request_just_opened_is_news_the_first_time():
    just = _created(timedelta(minutes=5))
    assert first(_pr(created=just), NOW) == [UpstreamChange("opened")]
    # Opened a day ago and linked now is a late link, not an opening.
    assert first(_pr(created=_created(timedelta(days=1))), NOW) == []
    assert first(_pr(pr="MERGED", created=just), NOW) == []
    assert first(_pr(pr="CLOSED", created=just), NOW) == []
    # A reading from before `created` was kept can't tell, so it says nothing.
    assert first(_pr(), NOW) == []


def test_every_change_is_one_the_contract_knows():
    assert {"opened", "review_requested", "approved", "changes_requested", "ci_failed",
            "ci_passed", "merged", "closed"} == set(message_format.UPSTREAM_CHANGES)  # fmt: skip
    assert set(wake_digest.UPSTREAM_LINES) == set(message_format.UPSTREAM_CHANGES)


# ── the watcher ──────────────────────────────────────────────────────────────


class Pulls:
    """A GitHub-shaped provider whose answers a test sets, ref by ref."""

    name = "toy"
    base_url = "https://toy.example"
    auth = None
    max_batch = 10
    ttl = timedelta(seconds=0)
    swr = timedelta(minutes=30)

    def __init__(self) -> None:
        self.answers: dict[str, dict[str, Any]] = {}

    def claims(self, text: str) -> list[Ref]:
        return [
            Ref(provider=self.name, kind="pull_request", id=w, url=f"https://toy.example/{w}")
            for w in text.replace(",", " ").replace(".", " ").split()
            if w.startswith("PR-")
        ]

    def changes(self, before: dict[str, Any], after: dict[str, Any]) -> list[UpstreamChange]:
        return changes(before, after)

    async def fetch(self, refs: list[Ref], ctx: object) -> list[FetchOutcome]:
        return [
            FetchSucceeded(
                ref=r,
                upstream=UpstreamState(
                    state="pending",
                    label="CI running",
                    url=f"https://toy.example/{r.id}",
                    source_updated_at=NOW,
                    detail=self.answers.get(r.id, _pr()),
                ),
            )
            for r in refs
        ]


@pytest.fixture
def shop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A room with two rows linking PR-1, one of them resolved, and the
    notices the watcher raises, captured rather than sent."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.services.filesystem import ensure_room_structure, get_room_dir, write_memory_file
    from app.services.room_channels import manager

    room_dir = get_room_dir(ROOM)
    ensure_room_structure(room_dir)
    write_memory_file(
        room_dir,
        "work/old-checkout",
        "# Old checkout\n\nWas PR-1.",
        created_by="hay",
        extra_meta={"status": "done", "assignment": "resolved"},
    )
    write_memory_file(
        room_dir,
        "work/apple-pay",
        "# Turn on Apple Pay\n\nThe PR is PR-1.",
        created_by="hay",
        extra_meta={"episode": THREAD, "assignee": "builder"},
    )
    raised: list[dict[str, Any]] = []

    async def capture(room: str, **notice: Any) -> None:
        raised.append({"room": room, **notice})

    monkeypatch.setattr(manager, "raise_notice", capture)
    return raised


def _sweep(provider: Pulls) -> list[tuple[str, str, str]]:
    runtime = StatusRuntime(providers={provider.name: provider})
    return asyncio.run(watch.sweep(NOW, runtime))


def test_the_first_answer_is_a_baseline_then_a_change_is_told_on_the_open_row(shop):
    pulls = Pulls()
    assert _sweep(pulls) == []
    assert shop == []

    pulls.answers["PR-1"] = _pr(ci="FAILURE")
    assert _sweep(pulls) == [(ROOM, "work/apple-pay", "ci_failed")]
    (notice,) = shop
    assert notice["subkind"] == "upstream"
    assert notice["change"] == "ci_failed"
    assert notice["title"] == "Turn on Apple Pay"
    assert notice["episode"] == THREAD
    assert notice["ref"] == "PR-1"
    assert notice["url"] == "https://toy.example/PR-1"

    # The same answer again is not news.
    assert _sweep(pulls) == []


class OpeningPulls(Pulls):
    """The toy provider, saying what a first reading is worth, as GitHub does."""

    def first(self, after: dict[str, Any], now: datetime) -> list[UpstreamChange]:
        return first(after, now)


def _swept_before() -> None:
    """The room has been swept already, so a ref new to it can be news."""
    watch._save_seen(ROOM, {})


def test_a_pull_request_just_opened_and_seen_first_is_told_once(shop):
    _swept_before()
    pulls = OpeningPulls()
    pulls.answers["PR-1"] = _pr(created=_created(timedelta(minutes=5)))
    assert _sweep(pulls) == [(ROOM, "work/apple-pay", "opened")]
    (notice,) = shop
    assert notice["change"] == "opened"
    assert notice["title"] == "Turn on Apple Pay"
    # Seen once, it is a baseline like any other.
    assert _sweep(pulls) == []


def test_a_rooms_first_sweep_tells_nothing_however_new(shop):
    # A hub just given its token: every open pull request is a first sighting,
    # and none of them was just opened as far as the room is concerned.
    pulls = OpeningPulls()
    pulls.answers["PR-1"] = _pr(created=_created(timedelta(minutes=5)))
    assert _sweep(pulls) == []
    assert shop == []


def test_a_room_linking_nothing_yet_still_counts_as_swept(shop):
    from app.services.filesystem import get_room_dir

    for name in ("old-checkout", "apple-pay"):
        (get_room_dir(ROOM) / "work" / f"{name}.md").unlink()
    pulls = OpeningPulls()
    assert _sweep(pulls) == []
    # The first pull request linked after that is news, not a first sweep.
    from app.services.filesystem import write_memory_file

    write_memory_file(get_room_dir(ROOM), "work/refunds", "# Refunds\n\nPR-4", created_by="hay")
    pulls.answers["PR-4"] = _pr(created=_created(timedelta(minutes=2)))
    assert _sweep(pulls) == [(ROOM, "work/refunds", "opened")]


def test_a_pull_request_opened_a_day_before_it_was_linked_says_nothing(shop):
    _swept_before()
    pulls = OpeningPulls()
    pulls.answers["PR-1"] = _pr(created=_created(timedelta(days=1)))
    assert _sweep(pulls) == []
    assert shop == []


def test_a_pull_request_already_merged_when_first_seen_says_nothing(shop):
    _swept_before()
    pulls = OpeningPulls()
    pulls.answers["PR-1"] = _pr(pr="MERGED", ci="SUCCESS", created=_created(timedelta(minutes=5)))
    assert _sweep(pulls) == []
    assert shop == []


def test_the_last_answer_survives_a_restart(shop):
    pulls = Pulls()
    _sweep(pulls)
    # A fresh runtime is a hub that restarted: its cache is empty, the room's
    # last answer is on disk, and a merge while it was down is still said.
    pulls.answers["PR-1"] = _pr(pr="MERGED", ci="SUCCESS")
    assert _sweep(pulls) == [(ROOM, "work/apple-pay", "merged")]
    assert shop[0]["at"] == NOW.isoformat()


def test_a_ref_no_row_mentions_is_forgotten(shop):
    from app.services.filesystem import get_room_dir

    pulls = Pulls()
    _sweep(pulls)
    assert "toy:pull_request:PR-1" in watch.load_seen(ROOM)
    for name in ("old-checkout", "apple-pay"):
        (get_room_dir(ROOM) / "work" / f"{name}.md").unlink()
    _sweep(pulls)
    assert watch.load_seen(ROOM) == {}


def test_a_link_said_in_the_rows_thread_counts(shop, monkeypatch):
    from types import SimpleNamespace

    from app.services.filesystem import get_room_dir, write_memory_file
    from app.services.room_channels import manager

    write_memory_file(
        get_room_dir(ROOM),
        "work/refunds",
        "# Refunds\n\nNo link here.",
        created_by="hay",
        extra_meta={"episode": "urn:ioc:mycelium:episode:shop:t2"},
    )
    said = _record("builder", "PR is up: PR-7", "urn:ioc:mycelium:episode:shop:t2")
    log = SimpleNamespace(records=[said])
    monkeypatch.setattr(
        manager, "get", lambda room: SimpleNamespace(persister=SimpleNamespace(log=log))
    )

    from app.services.status import discovery

    found = {
        str(d.ref): d.origins for d in discovery.discover(ROOM, StatusRuntime({"toy": Pulls()}))
    }
    assert found["toy:pull_request:PR-7"] == ("memory:work/refunds",)


def test_a_link_written_as_code_in_the_thread_does_not_count(shop, monkeypatch):
    from types import SimpleNamespace

    from app.services.filesystem import get_room_dir, write_memory_file
    from app.services.room_channels import manager

    write_memory_file(
        get_room_dir(ROOM),
        "work/refunds",
        "# Refunds\n\nShipped in `see PR-3 here`",
        created_by="hay",
        extra_meta={"episode": "urn:ioc:mycelium:episode:shop:t2"},
    )
    said = _record(
        "reviewer",
        "Rendered as `CI went red on PR-8 4m ago`\n\n```\nPR-9\n```\nPR is up: PR-7",
        "urn:ioc:mycelium:episode:shop:t2",
    )
    log = SimpleNamespace(records=[said])
    monkeypatch.setattr(
        manager, "get", lambda room: SimpleNamespace(persister=SimpleNamespace(log=log))
    )

    from app.services.status import discovery

    found = {str(d.ref) for d in discovery.discover(ROOM, StatusRuntime({"toy": Pulls()}))}
    # Prose in the thread counts; code in it doesn't. The row's own text is
    # read whole, code and all.
    assert "toy:pull_request:PR-7" in found
    assert "toy:pull_request:PR-8" not in found
    assert "toy:pull_request:PR-9" not in found
    assert "toy:pull_request:PR-3" in found


# ── the digest ───────────────────────────────────────────────────────────────


def _record(sender: str, text: str, episode: str, minutes_ago: int = 1) -> TranscriptRecord:
    return TranscriptRecord(
        message_id=f"m-{sender}-{minutes_ago}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {"kind": "exchange", "message": {"episode": episode}},
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
    )


def _upstream(
    key: str, title: str, change: str, minutes_ago: int, **extra: str
) -> TranscriptRecord:
    record = _record("system", "", message_format.live_episode_urn(ROOM), minutes_ago)
    record.content["l9"]["payload"] = {
        "type": message_format.NOTICE_PAYLOAD_TYPE,
        "data": {"subkind": "upstream", "key": key, "title": title, "change": change,
                 "ref": "acme/shop#12", **extra},
    }  # fmt: skip
    return record


def test_an_upstream_notice_wakes_nobody():
    from app.routes.participate import _addressed_to

    record = _upstream("work/apple-pay", "Turn on Apple Pay", "review_requested", 1, who="builder")
    assert not _addressed_to(record.content, "builder")
