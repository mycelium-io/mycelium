# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for L9 episode tracking, epistemic reply fields, consensus metrics,
and the dual-stack (alignment) CFN client mapping."""

import json
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from app.services import l9_episode
from app.services.coordination import _normalize_cfn_decide_response, _parse_agent_reply


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


def test_broken_consensus_commits_as_abort():
    ep = _open()
    consensus = l9_episode.build_consensus_envelope(ep, broken=True, assignments={}, metrics=None)
    assert consensus["header"]["subkind"] == "abort"
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
    assert l9_episode.compute_metrics(ep, {"a1": "accept", "a2": "accept"}) is None


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
    m = l9_episode.compute_metrics(ep, {"a1": "accept", "a2": "accept"})
    assert m is not None
    assert m["mpc"] == pytest.approx(0.85)
    assert m["gar"] == 1.0
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
    # a2's prior was also 0.4 (single round): direction*delta == 0 counts as
    # non-opposing, so GAR stays 1.0; SCR catches the deference instead.
    m = l9_episode.compute_metrics(ep, {"a1": "accept", "a2": "accept"})
    assert m is not None
    assert m["scr"] == 0.5
    assert m["provenance_weight"] == pytest.approx((1 - 0.5) * m["gar"])


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
    m = l9_episode.compute_metrics(ep, {"a1": "accept", "a2": "accept"})
    assert m is not None
    assert m["gar"] == 0.5


# ── reply parsing (coordination.py integration) ───────────────────────────────


def test_parse_agent_reply_carries_epistemic_fields():
    content = json.dumps(
        {
            "action": "accept",
            "confidence": 0.75,
            "evidence": ["decisions/api-style", "  ", 42],
            "deferred_to": "lead-agent",
            "reasoning": "prior art in the decisions namespace",
        }
    )
    reply = _parse_agent_reply("a1", content)
    assert reply["action"] == "accept"
    assert reply["confidence"] == 0.75
    assert reply["evidence"] == ["decisions/api-style"]
    assert reply["deferred_to"] == "lead-agent"
    assert reply["reasoning"] == "prior art in the decisions namespace"


def test_parse_agent_reply_drops_invalid_epistemic_fields():
    content = json.dumps(
        {
            "action": "reject",
            "confidence": 1.7,  # out of range
            "evidence": "not-a-list",
            "deferred_to": "someone",  # invalid on non-accept
        }
    )
    reply = _parse_agent_reply("a1", content)
    assert reply["action"] == "reject"
    assert "confidence" not in reply
    assert "evidence" not in reply
    assert "deferred_to" not in reply


def test_parse_agent_reply_legacy_unchanged():
    reply = _parse_agent_reply("a1", json.dumps({"action": "accept"}))
    assert reply == {"agent_id": "a1", "participant_id": "a1", "action": "accept"}


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


# ── alignment-flavor CFN client ───────────────────────────────────────────────


class _CapturingEndpoint:
    """Stands in for a generated endpoint module: captures the typed request
    body and returns a canned typed response, so we assert on request mapping
    without a live CFN."""

    captured: ClassVar[dict[str, Any]] = {}
    parsed: ClassVar[Any] = None

    @staticmethod
    async def asyncio_detailed(*, workspace_id: str, mas_id: str, client: Any, body: Any) -> Any:
        _CapturingEndpoint.captured = {"workspace_id": workspace_id, "mas_id": mas_id, "body": body}
        return SimpleNamespace(
            content=b"{}", headers={}, status_code=200, parsed=_CapturingEndpoint.parsed
        )


@pytest.mark.asyncio
async def test_alignment_decide_maps_participant_id(monkeypatch):
    from app.config import settings
    from app.services import cfn_negotiation
    from ioc_cfn_svc_api_client.models import SemanticalignmentDecideResponse

    monkeypatch.setattr(settings, "CFN_SVC_URL", "http://cfn:9002")
    monkeypatch.setattr(cfn_negotiation, "decide_api", _CapturingEndpoint)
    _CapturingEndpoint.parsed = SemanticalignmentDecideResponse(status="agreed")

    await cfn_negotiation.decide_negotiation(
        session_id="s1",
        agent_replies=[
            {"agent_id": "a1", "participant_id": "a1", "action": "accept", "confidence": 0.9},
            {
                "agent_id": "a2",
                "participant_id": "a2",
                "action": "counter_offer",
                "offer": {"k": "v"},
            },
        ],
        workspace_id="ws",
        mas_id="mas",
    )
    cap = _CapturingEndpoint.captured
    assert cap["workspace_id"] == "ws" and cap["mas_id"] == "mas"
    # Typed request body: agent_id → participant_id; epistemic extras (confidence)
    # are NOT forwarded to CFN.
    assert cap["body"].to_dict()["agent_replies"] == [
        {"participant_id": "a1", "action": "accept"},
        {"participant_id": "a2", "action": "counter_offer", "offer": {"k": "v"}},
    ]


@pytest.mark.asyncio
async def test_alignment_start_request_shape(monkeypatch):
    from app.config import settings
    from app.services import cfn_negotiation
    from ioc_cfn_svc_api_client.models import SemanticalignmentStartResponse

    monkeypatch.setattr(settings, "CFN_SVC_URL", "http://cfn:9002")
    monkeypatch.setattr(cfn_negotiation, "start_api", _CapturingEndpoint)
    _CapturingEndpoint.parsed = SemanticalignmentStartResponse(status="initiated")

    await cfn_negotiation.start_negotiation(
        session_id="s1",
        content_text="- a1: ship",
        agents=[{"id": "a1", "name": "a1"}],
        workspace_id="ws",
        mas_id="mas",
        n_steps=10,
    )
    body = _CapturingEndpoint.captured["body"].to_dict()
    assert body == {
        "session_id": "s1",
        "content_text": "- a1: ship",
        "agents": [{"id": "a1", "name": "a1"}],
        "n_steps": 10,
    }


@pytest.mark.asyncio
async def test_decide_raises_on_missing_status(monkeypatch):
    """Presence-assertion: a response missing the depended-on ``status`` field
    (swaggo marks everything optional, so a rename becomes UNSET) is a loud
    CfnNegotiationError, not a silent empty agreement."""
    from app.config import settings
    from app.services import cfn_negotiation
    from ioc_cfn_svc_api_client.models import SemanticalignmentDecideResponse

    monkeypatch.setattr(settings, "CFN_SVC_URL", "http://cfn:9002")
    monkeypatch.setattr(cfn_negotiation, "decide_api", _CapturingEndpoint)
    _CapturingEndpoint.parsed = SemanticalignmentDecideResponse()  # no status

    with pytest.raises(
        cfn_negotiation.CfnNegotiationError, match="missing required field 'status'"
    ):
        await cfn_negotiation.decide_negotiation(
            session_id="s1",
            agent_replies=[{"agent_id": "a1", "action": "accept"}],
            workspace_id="ws",
            mas_id="mas",
        )


def test_normalize_decide_handles_alignment_final_result():
    """The Go CFN's terminal decide response: top-level status + final_result
    SSTP envelope. The normalizer must surface the agreement."""
    result = {
        "status": "agreed",
        "session_id": "s1",
        "round": 3,
        "final_result": {
            "kind": "commit",
            "semantic_context": {
                "final_agreement": [
                    {"issue_id": "budget", "chosen_option": "high"},
                ]
            },
        },
        "shared_memory": {"persisted": True},
    }
    normalized = _normalize_cfn_decide_response(result)
    assert normalized["semantic_context"]["final_agreement"][0]["issue_id"] == "budget"
    # Top-level extras survive the merge.
    assert normalized["shared_memory"] == {"persisted": True}
