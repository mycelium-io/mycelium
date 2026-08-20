# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for L9 episode tracking, epistemic reply fields, and consensus metrics."""

from typing import Any

import pytest

from app.services import l9_episode


def _open() -> l9_episode.EpisodeState:
    return l9_episode.open_episode(
        parent_room="sprint",
        short_id="abc123",
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["a1", "a2"],
        joined_intents="- a1: ship it\n- a2: test it",
    )


# ── episode recording ─────────────────────────────────────────────────────────


def test_open_episode_records_intent():
    ep = _open()
    assert ep.episode == "urn:ioc:mycelium:episode:sprint:abc123"
    assert ep.topic == "urn:concept:mycelium:sprint"
    assert len(ep.messages) == 1
    intent = ep.messages[0]
    assert intent["header"]["kind"] == "intent"
    assert intent["header"]["subkind"] == "mission"
    assert intent["header"]["participants"]["groups"] == {
        "workspace_id": "ws-1",
        "mas_id": "mas-1",
    }
    assert ep.intent_id == intent["header"]["message"]["id"]


def test_engine_handle_signs_episode_envelopes():
    """A registered engine signs the intent/tick/consensus it authors, so the
    wire carries the engine's real identity (e.g. "aligner") rather than the
    generic system actor. The agents' own replies still carry their handles."""
    ep = l9_episode.open_episode(
        parent_room="sprint",
        short_id="abc123",
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["a1", "a2"],
        joined_intents="- a1: ship it\n- a2: test it",
        engine_handle="aligner",
    )
    assert ep.engine_handle == "aligner"
    # Intent is engine-authored.
    assert ep.messages[0]["header"]["participants"]["actors"][0]["id"] == "aligner"

    tick = l9_episode.record_tick(ep, handle="a1", round_n=1, payload={"action": "respond"})
    assert tick["header"]["participants"]["actors"][0]["id"] == "aligner"
    # The agent replies *to* the engine, so the engine is the recipient.
    l9_episode.record_reply(ep, handle="a1", reply={"action": "accept"}, round_n=1)
    reply = ep.messages[-1]
    assert reply["header"]["participants"]["actors"][0]["id"] == "a1"
    assert reply["header"]["participants"]["actors"][1]["id"] == "aligner"

    consensus = l9_episode.build_consensus_envelope(
        ep, broken=False, assignments={"budget": "high"}, metrics=None
    )
    assert consensus["header"]["participants"]["actors"][0]["id"] == "aligner"


def test_episode_without_engine_falls_back_to_system_actor():
    """No engine context → the system actor signs (the pre-engine default)."""
    ep = _open()
    assert ep.engine_handle == ""
    assert ep.messages[0]["header"]["participants"]["actors"][0]["id"] == "system"
    consensus = l9_episode.build_consensus_envelope(ep, broken=True, assignments={}, metrics=None)
    assert consensus["header"]["participants"]["actors"][0]["id"] == "system"


def test_causal_threading_tick_reply_consensus():
    ep = _open()
    tick1 = l9_episode.record_tick(ep, handle="a1", round_n=1, payload={"action": "respond"})
    # First tick parents the intent.
    assert tick1["header"]["message"]["parents"] == [ep.intent_id]

    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.8}, round_n=1
    )
    reply1 = ep.messages[-1]
    # Reply parents the tick it answers, sender is the agent.
    assert reply1["header"]["message"]["parents"] == [tick1["header"]["message"]["id"]]
    assert reply1["header"]["participants"]["actors"][0]["id"] == "a1"

    # Second-round tick parents the agent's reply.
    tick2 = l9_episode.record_tick(ep, handle="a1", round_n=2, payload={"action": "respond"})
    assert tick2["header"]["message"]["parents"] == [reply1["header"]["message"]["id"]]

    l9_episode.record_reply(ep, handle="a2", reply={"action": "accept"}, round_n=2)
    consensus = l9_episode.build_consensus_envelope(
        ep, broken=False, assignments={"budget": "high"}, metrics=None
    )
    assert consensus["header"]["kind"] == "commit"
    assert consensus["header"]["subkind"] == "converged"
    # Consensus parents every agent's final reply.
    assert sorted(consensus["header"]["message"]["parents"]) == sorted(ep.last_reply_ids.values())


def test_broken_consensus_commits_as_rejected():
    ep = _open()
    consensus = l9_episode.build_consensus_envelope(ep, broken=True, assignments={}, metrics=None)
    assert consensus["header"]["subkind"] == "rejected"
    # No replies recorded: falls back to parenting the intent.
    assert consensus["header"]["message"]["parents"] == [ep.intent_id]


def test_synthesised_reply_marked():
    ep = _open()
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "reject"}, round_n=1, synthesised=True
    )
    assert ep.messages[-1]["payload"]["data"]["synthesised"] is True


# ── epistemic tracking + metrics ──────────────────────────────────────────────


def test_prior_is_first_confidence_and_posterior_is_last():
    ep = _open()
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "reject", "confidence": 0.3}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.9}, round_n=2
    )
    assert ep.priors["a1"] == 0.3
    assert ep.last_confidence["a1"] == 0.9


def test_deferred_accept_tracked_and_cleared():
    ep = _open()
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "deferred_to": "a2"}, round_n=1
    )
    assert ep.deferred["a1"] == "a2"
    # A later genuine accept clears the deference.
    l9_episode.record_reply(ep, handle="a1", reply={"action": "accept"}, round_n=2)
    assert "a1" not in ep.deferred


def test_metrics_none_when_participation_thin():
    ep = _open()
    # Only one of two agents reported confidence.
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.8}, round_n=1
    )
    assert l9_episode.compute_metrics(ep) is None


def test_metrics_genuine_agreement():
    ep = _open()
    # Both agents' confidence rose toward a confident outcome (MPC > 0.5).
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "reject", "confidence": 0.5}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.6}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.8}, round_n=2
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "accept", "confidence": 0.9}, round_n=2
    )
    m = l9_episode.compute_metrics(ep)
    assert m is not None
    assert m["mpc"] == pytest.approx(0.85)
    assert m["gar"] == 1.0
    # Both moved without deference or failed grounding → genuine, so SCR stays 0.
    assert m["scr"] == 0.0
    assert m["provenance_weight"] == 1.0
    assert m["participants"] == 2


def test_metrics_social_compliance():
    ep = _open()
    # a2 accepts only by deference; its confidence *fell* against a confident outcome.
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.9}, round_n=1
    )
    l9_episode.record_reply(
        ep,
        handle="a2",
        reply={"action": "accept", "confidence": 0.4, "deferred_to": "a1"},
        round_n=1,
    )
    # SCR is over agents that actually revised: a2 deferred (compliance), a1
    # stated once and never moved (not a reviser), so 1/1 revisions was compliance.
    m = l9_episode.compute_metrics(ep)
    assert m is not None
    assert m["scr"] == 1.0
    assert m["provenance_weight"] == pytest.approx((1 - 1.0) * m["gar"])


def test_metrics_gar_detects_dragged_agent():
    ep = _open()
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "reject", "confidence": 0.9}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.8}, round_n=1
    )
    # a2's confidence falls while the team outcome stays confident → not genuine.
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "accept", "confidence": 0.6}, round_n=2
    )
    m = l9_episode.compute_metrics(ep)
    assert m is not None
    assert m["gar"] == 0.5


def test_grounding_yields_genuine_revision_cause():
    ep = _open()
    # a1 seeds the evidence pool; a2 states a prior, then moves while engaging it.
    l9_episode.record_reply(
        ep,
        handle="a1",
        reply={"action": "reject", "confidence": 0.5, "supporting_evidence": ["e1", "e2"]},
        round_n=1,
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.3}, round_n=1
    )
    l9_episode.record_reply(
        ep,
        handle="a2",
        reply={"action": "accept", "confidence": 0.8, "addresses": ["e1", "e2"]},
        round_n=2,
    )
    assert ep.revision_cause["a2"] == "grounded_argument"


def test_weak_grounding_yields_social_compliance():
    ep = _open()
    l9_episode.record_reply(
        ep,
        handle="a1",
        reply={"action": "reject", "confidence": 0.5, "supporting_evidence": ["e1", "e2"]},
        round_n=1,
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.3}, round_n=1
    )
    # a2 moves but its addresses don't overlap the pool → weak grounding → compliance.
    l9_episode.record_reply(
        ep,
        handle="a2",
        reply={"action": "accept", "confidence": 0.8, "addresses": ["unrelated"]},
        round_n=2,
    )
    assert ep.revision_cause["a2"] == "social_compliance"


def test_movement_without_addresses_is_genuine():
    ep = _open()
    # No grounding flags at all: an agent that moves must not be scored as complying.
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.3}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "accept", "confidence": 0.9}, round_n=2
    )
    assert ep.revision_cause["a2"] == "grounded_argument"


def test_explicit_revision_cause_overrides_derivation():
    ep = _open()
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.3}, round_n=1
    )
    l9_episode.record_reply(
        ep,
        handle="a2",
        reply={"action": "accept", "confidence": 0.9, "revision_cause": "new_evidence"},
        round_n=2,
    )
    assert ep.revision_cause["a2"] == "new_evidence"


def test_gar_guard_at_mpc_half():
    ep = _open()
    # Two agents move in opposite directions and land at mean 0.5. The direction
    # term vanishes; the guard must NOT score this maximal disagreement as gar=1.
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "reject", "confidence": 0.6}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "reject", "confidence": 0.4}, round_n=1
    )
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.4}, round_n=2
    )
    l9_episode.record_reply(
        ep, handle="a2", reply={"action": "accept", "confidence": 0.6}, round_n=2
    )
    m = l9_episode.compute_metrics(ep)
    assert m is not None
    assert m["mpc"] == pytest.approx(0.5)
    assert m["gar"] == 0.0


# ── epistemic field sanitisation ──────────────────────────────────────────────


def test_sanitize_rejects_bool_confidence():
    result: dict[str, Any] = {"action": "accept"}
    l9_episode.sanitize_epistemic_fields({"confidence": True}, result)
    assert "confidence" not in result


# ── episode record persistence ────────────────────────────────────────────────


def test_write_episode_record(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.config import settings

    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    ep = _open()
    l9_episode.record_tick(ep, handle="a1", round_n=1, payload={"action": "respond"})
    l9_episode.record_reply(
        ep, handle="a1", reply={"action": "accept", "confidence": 0.8}, round_n=1
    )
    l9_episode.write_episode_record(
        ep,
        outcome="converged",
        metrics={"mpc": 0.8, "gar": 1.0, "scr": 0.0, "provenance_weight": 1.0, "participants": 2},
        plan_file="plan/tasks.md",
    )
    record = tmp_path / "rooms" / "sprint" / "log" / "episodes" / "abc123.md"
    assert record.exists()
    body = record.read_text()
    assert "urn:ioc:mycelium:episode:sprint:abc123" in body
    assert "MPC 0.80" in body
    # One JSONL line per envelope: intent + tick + reply.
    jsonl_lines = [ln for ln in body.splitlines() if ln.startswith('{"header"')]
    assert len(jsonl_lines) == 3


def test_rule_update_writeback_and_local_team_prior(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.config import settings

    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    ep = _open()
    metrics = {"mpc": 0.72, "gar": 0.8, "scr": 0.1, "provenance_weight": 0.72, "participants": 2}
    l9_episode.write_rule_update(ep, metrics)

    rule_file = tmp_path / "rooms" / "sprint" / "l9" / "rule_update" / "topic.md"
    assert rule_file.exists()

    prior = l9_episode.read_team_prior_local("sprint")
    assert prior == {
        "confidence": 0.72,
        "provenance_weight": 0.72,
        "episode_count": 1,
        "source": "mycelium-memory",
    }


def test_rule_update_episode_count_increments(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.config import settings

    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    ep = _open()
    metrics = {"mpc": 0.6, "gar": 0.5, "scr": 0.2, "provenance_weight": 0.4, "participants": 2}
    l9_episode.write_rule_update(ep, metrics)
    l9_episode.write_rule_update(ep, metrics)

    prior = l9_episode.read_team_prior_local("sprint")
    assert prior is not None
    assert prior["episode_count"] == 2


def test_read_team_prior_local_absent_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.config import settings

    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    assert l9_episode.read_team_prior_local("never-negotiated") is None


# ── move subkind on the wire (#681) ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("move", "expected"),
    [("counter", "counter"), ("accept", "accept"), ("reject", "reject")],
)
def test_reply_stamps_move_subkind(move: str, expected: str):
    """A recognized move rides the exchange reply's header.subkind, so a
    negotiation move is explicit on the wire instead of inferred from prose."""
    ep = _open()
    l9_episode.record_reply(ep, handle="a1", reply={"action": "accept", "move": move}, round_n=1)
    reply = ep.messages[-1]
    assert reply["header"]["kind"] == "exchange"
    assert reply["header"]["subkind"] == expected


def test_reply_without_move_has_no_subkind():
    """Replies predating the move vocabulary carry no subkind and round-trip
    unchanged (an absent subkind is always valid)."""
    ep = _open()
    l9_episode.record_reply(ep, handle="a1", reply={"action": "accept"}, round_n=1)
    reply = ep.messages[-1]
    assert reply["header"]["kind"] == "exchange"
    assert "subkind" not in reply["header"]


def test_reply_ignores_unknown_move():
    """A move outside the closed vocabulary is dropped, never stamped as an
    invalid subkind (faithful, never fabricated)."""
    ep = _open()
    l9_episode.record_reply(ep, handle="a1", reply={"action": "accept", "move": "bogus"}, round_n=1)
    assert "subkind" not in ep.messages[-1]["header"]
