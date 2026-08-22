# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The summon-filter contract: what the room calls, independent of any engine.

These use plain async functions as filters rather than a real guard — the point
is the seam's own behaviour: an unguarded room, the merge across several
filters, an open verdict vocabulary, and what happens to cached decisions when
the filter set changes.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import summon_filter
from app.services.engine_events import lifecycle
from app.services.summon_filter import ABSTAIN, MENTION, WAKE, SummonContext, SummonVerdict


@pytest.fixture(autouse=True)
def _reset_seam_state():
    """The bus and the verdict store are process-wide; isolate each test."""
    lifecycle.clear()
    summon_filter.verdicts.clear()
    yield
    lifecycle.clear()
    summon_filter.verdicts.clear()


def _ctx(text: str, *handles: str, room: str = "r", message_id: str = "m1") -> SummonContext:
    return SummonContext(
        room=room, message_id=message_id, sender="avery", text=text, handles=handles
    )


def _answering(decisions: dict[str, str]):
    """A filter that always answers ``decisions``."""

    async def _filter(_ctx):
        return decisions

    return _filter


# ── an unguarded room is the pre-guard room ──────────────────────────────────


@pytest.mark.asyncio
async def test_no_filter_installed_wakes_everything():
    assert summon_filter.guarded("r") is False
    assert await summon_filter.decide(_ctx("credit to @alice", "alice")) == {"alice": WAKE}


@pytest.mark.asyncio
async def test_wakes_is_true_in_an_unguarded_room_without_waiting():
    assert await summon_filter.wakes("r", "m1", "alice") is True


# ── the merge, including verdicts this version has never heard of ────────────


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ([WAKE], WAKE),
        ([MENTION], MENTION),
        ([WAKE, MENTION], WAKE),  # any wake beats a suppression
        ([MENTION, MENTION], MENTION),  # suppress only when every opinion agrees
        ([], WAKE),  # nobody had an opinion
        ([ABSTAIN], WAKE),  # an abstention is not an opinion
        ([ABSTAIN, MENTION], MENTION),  # …so it doesn't dilute a real one
        (["defer"], WAKE),  # a verdict from a later engine: unknown, so no weight
        (["escalate", MENTION], MENTION),
    ],
)
def test_merge_policy_is_fail_open_over_opinions_only(answers, expected):
    assert summon_filter._merge(answers) == expected


@pytest.mark.asyncio
async def test_an_unknown_verdict_does_not_crash_the_room():
    """The contract must survive an engine answering in a vocabulary it added."""
    summon_filter.install("r", "future-guard", _answering({"alice": "defer"}))
    assert await summon_filter.decide(_ctx("thanks @alice", "alice")) == {"alice": WAKE}


@pytest.mark.asyncio
async def test_an_abstaining_filter_leaves_the_decision_to_the_others():
    summon_filter.install("r", "shy", _answering({"alice": ABSTAIN}))
    summon_filter.install("r", "opinionated", _answering({"alice": MENTION}))
    assert await summon_filter.decide(_ctx("thanks @alice", "alice")) == {"alice": MENTION}


@pytest.mark.asyncio
async def test_two_filters_suppress_only_when_both_agree():
    summon_filter.install("r", "one", _answering({"alice": MENTION}))
    summon_filter.install("r", "two", _answering({"alice": MENTION}))
    assert await summon_filter.decide(_ctx("thanks @alice", "alice")) == {"alice": MENTION}

    summon_filter.install("r", "two", _answering({"alice": WAKE}))
    assert await summon_filter.decide(_ctx("thanks @alice", "alice", message_id="m2")) == {
        "alice": WAKE
    }


@pytest.mark.asyncio
async def test_a_filter_that_raises_fails_the_whole_room_open():
    async def _broken(_ctx):
        raise RuntimeError("guard is broken")

    summon_filter.install("r", "one", _broken)
    summon_filter.install("r", "two", _answering({"alice": MENTION}))
    assert await summon_filter.decide(_ctx("thanks @alice", "alice")) == {"alice": WAKE}


@pytest.mark.asyncio
async def test_a_handle_no_filter_answered_for_still_wakes():
    summon_filter.install("r", "one", _answering({"alice": MENTION}))
    decisions = await summon_filter.decide(_ctx("per @alice, ask @bob", "alice", "bob"))
    assert decisions == {"alice": MENTION, "bob": WAKE}


# ── the await-side gate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wakes_reads_the_verdict_the_ingest_side_published():
    async def _filter(ctx):
        summon_filter.verdicts.put(
            SummonVerdict(
                room=ctx.room,
                message_id=ctx.message_id,
                sender=ctx.sender,
                text=ctx.text,
                decisions={"alice": MENTION},
            )
        )
        return {"alice": MENTION}

    summon_filter.install("r", "watcher", _filter)
    await summon_filter.decide(_ctx("shipped, thanks @alice", "alice"))
    assert await summon_filter.wakes("r", "m1", "alice") is False
    # A handle that message never mentioned is unaffected.
    assert await summon_filter.wakes("r", "m1", "bob") is True


@pytest.mark.asyncio
async def test_a_judgement_that_overruns_the_wait_wakes(monkeypatch):
    monkeypatch.setattr(summon_filter.settings, "SUMMON_FILTER_WAIT_S", 0.05)
    summon_filter.install("r", "watcher", _answering({}))
    summon_filter.verdicts.begin("r", "m1")
    assert await summon_filter.wakes("r", "m1", "alice") is True


# ── a verdict never outlives the filter set that produced it ─────────────────


@pytest.mark.asyncio
async def test_removing_a_filter_drops_the_verdicts_it_produced():
    """Otherwise a dead engine keeps suppressing wakes from the cache."""
    summon_filter.install("r", "watcher", _answering({"alice": MENTION}))
    summon_filter.verdicts.put(
        SummonVerdict(
            room="r", message_id="m1", sender="avery", text="", decisions={"alice": MENTION}
        )
    )
    assert summon_filter.verdicts.get("r", "m1") is not None

    summon_filter.uninstall("r", "watcher")
    assert summon_filter.verdicts.get("r", "m1") is None
    # …and with no filter left, the room is unguarded again.
    assert await summon_filter.wakes("r", "m1", "alice") is True


@pytest.mark.asyncio
async def test_adding_a_filter_drops_verdicts_decided_without_it():
    summon_filter.verdicts.put(
        SummonVerdict(
            room="r", message_id="m1", sender="avery", text="", decisions={"alice": MENTION}
        )
    )
    summon_filter.install("r", "watcher", _answering({}))
    assert summon_filter.verdicts.get("r", "m1") is None


@pytest.mark.asyncio
async def test_a_sweep_releases_a_waiter_instead_of_stranding_it():
    """Nothing is going to publish the answer it is waiting for, so it should
    reach the fail-open default now rather than at the timeout."""
    summon_filter.install("r", "watcher", _answering({}))
    summon_filter.verdicts.begin("r", "m1")
    waiter = asyncio.create_task(summon_filter.verdicts.wait("r", "m1", timeout_s=30.0))
    await asyncio.sleep(0)

    summon_filter.uninstall("r", "watcher")
    assert await asyncio.wait_for(waiter, timeout=1.0) is None


def test_uninstalling_an_owner_that_never_installed_is_a_no_op():
    summon_filter.install("r", "watcher", _answering({}))
    summon_filter.uninstall("r", "ghost")
    assert summon_filter.owners("r") == ["watcher"]


def test_a_verdict_that_never_saw_a_handle_wakes_it():
    verdict = SummonVerdict(
        room="r", message_id="m1", sender="avery", text="", decisions={"alice": MENTION}
    )
    assert verdict.wakes("alice") is False
    assert verdict.wakes("bob") is True
