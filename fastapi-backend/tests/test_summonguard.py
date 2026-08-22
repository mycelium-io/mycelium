# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The summonguard: which ``@``-mentions are summons.

Node-free and Pi-free — the one-shot classification is patched, so these cover
the decision logic rather than a model's judgement:

* the cheap pre-pass may confirm a wake but never suppress one,
* every failure mode (no Pi, timeout, unreadable answer, a handle the classifier
  skipped, the kill switch) resolves to ``wake``,
* an unguarded room is the old behaviour, byte for byte,
* and the persister's summon seam and ``await``'s wake read the same verdict.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import summon_filter, summonguard
from app.services.engine_events import lifecycle
from app.services.summon_filter import MENTION, WAKE, SummonContext
from app.services.summonguard import SummonGuardEngine


@pytest.fixture(autouse=True)
def _reset_guard_state():
    """The lifecycle bus and verdict store are process-wide; isolate each test."""
    lifecycle.clear()
    summon_filter.verdicts.clear()
    yield
    lifecycle.clear()
    summon_filter.verdicts.clear()


@pytest.fixture
def engine() -> SummonGuardEngine:
    return SummonGuardEngine(manager=None, timeout_s=1.0)  # ty: ignore[invalid-argument-type]


def _ctx(text: str, *handles: str, room: str = "r", message_id: str = "m1") -> SummonContext:
    return SummonContext(
        room=room, message_id=message_id, sender="avery", text=text, handles=handles
    )


def _classifier(answer: str):
    """Stand in for the one-shot Pi turn, returning a fixed raw answer."""

    def _fake(_prompt: str, _timeout: float) -> str:
        return answer

    return _fake


def _install(engine: SummonGuardEngine, room: str = "r", owner: str = "watcher") -> None:
    summon_filter.install(room, owner, engine.classify)


def _verdict(room: str = "r", message_id: str = "m1") -> summon_filter.SummonVerdict:
    """The published verdict for a message; fails the test if none landed."""
    verdict = summon_filter.verdicts.get(room, message_id)
    assert verdict is not None, f"no verdict published for {room}/{message_id}"
    return verdict


# ── the pre-pass ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "handle", "expected"),
    [
        ("@alice can you cost this out?", "alice", True),
        ("@alice @bob let's settle this", "bob", True),
        ("@alice, thoughts?", "alice", True),
        ("  @alice: ping", "alice", True),
        ("we shipped it, credit to @alice", "alice", False),
        ("as @alice said, the budget is fixed", "alice", False),
        ("@bob what did @alice mean?", "alice", False),
        ("", "alice", False),
    ],
)
def test_leading_mention_confirms_only_the_plain_summon_shape(text, handle, expected):
    assert summonguard._leading_mention_is_wake(text, handle) is expected


@pytest.mark.asyncio
async def test_a_leading_mention_never_reaches_the_classifier(engine, monkeypatch):
    """The hot path — ``@alice do X`` — costs no cognition turn."""

    def _explode(_prompt, _timeout):
        raise AssertionError("the classifier was called for a leading mention")

    monkeypatch.setattr(summonguard, "_pi_complete", _explode)
    decisions = await engine.classify(_ctx("@alice ship it", "alice"))
    assert decisions == {"alice": WAKE}
    assert _verdict().source == "leading-mention"


# ── the classifier's answer ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_provenance_mention_is_suppressed(engine, monkeypatch):
    monkeypatch.setattr(
        summonguard,
        "_pi_complete",
        _classifier('{"alice": {"decision": "mention", "reason": "credited, not asked"}}'),
    )
    decisions = await engine.classify(_ctx("we shipped it, credit to @alice", "alice"))
    assert decisions == {"alice": MENTION}
    verdict = _verdict()
    assert verdict.reasons["alice"] == "credited, not asked"
    assert verdict.wakes("alice") is False


@pytest.mark.asyncio
async def test_one_message_can_summon_one_handle_and_only_name_another(engine, monkeypatch):
    monkeypatch.setattr(
        summonguard,
        "_pi_complete",
        _classifier('{"bob": "wake", "alice": "mention"}'),
    )
    decisions = await engine.classify(
        _ctx("hey @bob, does @alice's number still hold?", "bob", "alice")
    )
    assert decisions == {"bob": WAKE, "alice": MENTION}


@pytest.mark.asyncio
async def test_a_fenced_answer_with_prose_around_it_still_parses(engine, monkeypatch):
    monkeypatch.setattr(
        summonguard,
        "_pi_complete",
        _classifier('Sure!\n```json\n{"alice": "mention"}\n```\nHope that helps.'),
    )
    assert await engine.classify(_ctx("nice work @alice", "alice")) == {"alice": MENTION}


# ── every failure resolves to a wake ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_pi_binary_fails_open_to_a_wake(engine, monkeypatch):
    def _missing(_prompt, _timeout):
        raise RuntimeError("`pi` not found on PATH")

    monkeypatch.setattr(summonguard, "_pi_complete", _missing)
    assert await engine.classify(_ctx("thanks @alice", "alice")) == {"alice": WAKE}
    assert _verdict().source == "fail-open"


@pytest.mark.asyncio
async def test_an_unreadable_answer_fails_open_to_a_wake(engine, monkeypatch):
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier("I think alice is fine?"))
    assert await engine.classify(_ctx("thanks @alice", "alice")) == {"alice": WAKE}


@pytest.mark.asyncio
async def test_a_handle_the_classifier_skipped_still_wakes(engine, monkeypatch):
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier('{"alice": "mention"}'))
    decisions = await engine.classify(_ctx("per @alice, ask @bob", "alice", "bob"))
    assert decisions == {"alice": MENTION, "bob": WAKE}


@pytest.mark.asyncio
async def test_the_kill_switch_disarms_a_registered_guard(engine, monkeypatch):
    monkeypatch.setattr(summonguard.settings, "SUMMONGUARD_DISABLE", True)
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier('{"alice": "mention"}'))
    ctx = _ctx("thanks @alice", "alice")
    assert await engine.classify(ctx) == {"alice": WAKE}
    assert _verdict().source == "disabled"


def test_a_verdict_that_never_saw_a_handle_wakes_it():
    verdict = summon_filter.SummonVerdict(
        room="r", message_id="m1", sender="avery", text="", decisions={"alice": MENTION}
    )
    assert verdict.wakes("alice") is False
    assert verdict.wakes("bob") is True


# ── parsing (pure) ───────────────────────────────────────────────────────────


def test_parse_decisions_ignores_unknown_handles_and_bad_verdicts():
    raw = '{"alice": "mention", "carol": "mention", "bob": "maybe"}'
    decisions, _ = summonguard.parse_decisions(raw, ("alice", "bob"))
    assert decisions == {"alice": MENTION}


def test_parse_decisions_accepts_both_shapes_and_normalizes_the_handle():
    raw = '{"@Alice": {"decision": "WAKE", "reason": "asked directly"}, "bob": "mention"}'
    decisions, reasons = summonguard.parse_decisions(raw, ("alice", "bob"))
    assert decisions == {"alice": WAKE, "bob": MENTION}
    assert reasons == {"alice": "asked directly"}


def test_the_prompt_carries_the_message_and_every_candidate():
    prompt = summonguard.build_prompt(_ctx("credit to @alice and @bob", "alice", "bob"))
    assert "credit to @alice and @bob" in prompt
    assert "- @alice" in prompt and "- @bob" in prompt


# ── registration installs the filter ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_registering_a_guard_installs_the_rooms_summon_filter(client, engine):
    engine.wire()
    await client.post("/api/rooms", json={"name": "portfolio"})
    assert summon_filter.guarded("portfolio") is False

    resp = await client.post(
        "/api/rooms/portfolio/engines",
        json={"handle": "watcher", "kind": "summonguard", "description": "guard our summons"},
    )
    assert resp.status_code == 201
    assert summon_filter.guarded("portfolio") is True
    assert summon_filter.owners("portfolio") == ["watcher"]
    # …and only that room's.
    assert summon_filter.guarded("other") is False


@pytest.mark.asyncio
async def test_registering_a_different_engine_kind_installs_nothing(client, engine):
    engine.wire()
    await client.post("/api/rooms", json={"name": "portfolio"})
    await client.post("/api/rooms/portfolio/engines", json={"handle": "med", "kind": "aligner"})
    assert summon_filter.guarded("portfolio") is False


@pytest.mark.asyncio
async def test_a_removed_guard_drops_its_filter_on_the_next_sync(client, engine):
    engine.wire()
    await client.post("/api/rooms", json={"name": "portfolio"})
    await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "watcher", "kind": "summonguard"}
    )
    assert summon_filter.guarded("portfolio") is True

    await client.delete("/api/rooms/portfolio/memory/agents/watcher")
    engine.sync_room("portfolio")
    assert summon_filter.guarded("portfolio") is False


@pytest.mark.asyncio
async def test_status_route_reports_the_guard_and_its_verdicts(client, engine, monkeypatch):
    engine.wire()
    await client.post("/api/rooms", json={"name": "portfolio"})
    await client.post(
        "/api/rooms/portfolio/engines", json={"handle": "watcher", "kind": "summonguard"}
    )
    monkeypatch.setattr(
        summonguard,
        "_pi_complete",
        _classifier('{"alice": {"decision": "mention", "reason": "credited only"}}'),
    )
    await summon_filter.decide(_ctx("shipped, credit to @alice", "alice", room="portfolio"))

    body = (await client.get("/api/rooms/portfolio/summonguard")).json()
    assert body["installed"] is True
    assert body["guards"] == ["watcher"]
    assert body["verdicts"][0]["decisions"] == {"alice": MENTION}
    assert body["verdicts"][0]["reasons"]["alice"] == "credited only"


@pytest.mark.asyncio
async def test_status_route_on_an_unguarded_room(client):
    await client.post("/api/rooms", json={"name": "portfolio"})
    body = (await client.get("/api/rooms/portfolio/summonguard")).json()
    assert body == {
        "room": "portfolio",
        "installed": False,
        "guards": [],
        "disabled": False,
        "verdicts": [],
    }


@pytest.mark.asyncio
async def test_status_route_404s_for_an_unknown_room(client):
    assert (await client.get("/api/rooms/ghost/summonguard")).status_code == 404


# ── the persister's summon seam ──────────────────────────────────────────────


def _exchange(message_id: str, text: str, *, sender: str = "avery"):
    from app.services import l9
    from app.services.l9_models import Kind

    return l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn("r", "live"),
        sender=sender,
        sender_role="human",
        topic=l9.topic_urn("r"),
        message_id=message_id,
        payload_type="message",
    )


def _persister(room: str, summoned: list[str]):
    from app.services import persister as persister_mod

    return persister_mod.RoomPersister(
        room,
        channel=None,  # ty: ignore[invalid-argument-type]  # _ingest is called directly
        members_provider=lambda: set(),
        on_summon=lambda handle, env, co, msg="": summoned.append(handle),
        feed_bus=False,
    )


async def _ingest(p, message_id: str, text: str):
    from app.services.l9_slim import serialize_content

    env = _exchange(message_id, text)
    p._ingest(env, serialize_content(env, extra={"content": text}))
    if p._summon_tasks:
        await asyncio.gather(*list(p._summon_tasks))


@pytest.mark.asyncio
async def test_an_unguarded_room_fires_the_summon_hook_inline(monkeypatch, tmp_path):
    """No guard registered → the seam is exactly what it was, no task, no wait."""
    summoned: list[str] = []
    p = _persister("r", summoned)
    await _ingest(p, "m1", "shipped it, credit to @alice")
    assert summoned == ["alice"]
    assert p._summon_tasks == set()


@pytest.mark.asyncio
async def test_a_guarded_room_withholds_the_summon_for_a_provenance_mention(engine, monkeypatch):
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier('{"alice": "mention"}'))
    _install(engine)
    summoned: list[str] = []
    await _ingest(_persister("r", summoned), "m1", "shipped it, credit to @alice")
    assert summoned == []
    # …and the same verdict is what await will read.
    assert await summon_filter.wakes("r", "m1", "alice") is False


@pytest.mark.asyncio
async def test_a_guarded_room_still_fires_a_real_summon(engine, monkeypatch):
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier('{"alice": "wake"}'))
    _install(engine)
    summoned: list[str] = []
    await _ingest(_persister("r", summoned), "m1", "hey @alice can you cost this out?")
    assert summoned == ["alice"]


@pytest.mark.asyncio
async def test_a_scoped_summon_keeps_the_full_mention_list(engine, monkeypatch):
    """``@aligner @a @b`` scopes the negotiation to @a/@b — so the co-mention list
    stays whole even when a co-mention was judged provenance."""
    monkeypatch.setattr(summonguard, "_pi_complete", _classifier('{"bob": "mention"}'))
    _install(engine)
    co: list[list[str]] = []
    from app.services import persister as persister_mod

    p = persister_mod.RoomPersister(
        "r",
        channel=None,  # ty: ignore[invalid-argument-type]
        members_provider=lambda: set(),
        on_summon=lambda handle, env, seen, msg="": co.append(list(seen)),
        feed_bus=False,
    )
    await _ingest(p, "m1", "@mediator settle this, @bob raised it")
    assert co == [["mediator", "bob"]]
