# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the L9 epistemic reply fields and config plumbing.

Covers the fixed wire contract for propose/respond replies (optional
``confidence`` / ``evidence`` / ``reasoning`` / ``deferred_to`` — omitted keys
MUST be absent from the serialized JSON so legacy requests stay byte-identical),
tick/consensus parsing of ``team_prior`` / ``metrics`` / ``cfn_persisted``,
and the ``.env`` generation surface.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mycelium.commands import negotiate as negotiate_cmd
from mycelium.config import MyceliumConfig
from mycelium.docker_utils import generate_env_file
from mycelium.protocol import (
    ConsensusContent,
    InboundTick,
    NegotiatePayload,
    ProposeReply,
    RespondReply,
)

# ── wire-format serialization (protocol models) ──────────────────────────────


def test_propose_reply_legacy_wire_shape_is_byte_identical() -> None:
    """A plain offer serializes exactly as before — no new keys, not even null."""
    reply = ProposeReply(offer={"budget": "high"})
    assert json.dumps(reply.model_dump(exclude_none=True)) == '{"offer": {"budget": "high"}}'


def test_respond_reply_legacy_wire_shape_is_byte_identical() -> None:
    reply = RespondReply(action="accept")
    assert json.dumps(reply.model_dump(exclude_none=True)) == '{"action": "accept"}'


def test_propose_reply_carries_epistemic_fields_when_set() -> None:
    reply = ProposeReply(
        offer={"budget": "high"},
        confidence=0.8,
        evidence=["Q3 revenue up 12%"],
        reasoning="growth justifies spend",
    )
    wire = reply.model_dump(exclude_none=True)
    assert wire == {
        "offer": {"budget": "high"},
        "confidence": 0.8,
        "evidence": ["Q3 revenue up 12%"],
        "reasoning": "growth justifies spend",
    }


def test_respond_reply_carries_epistemic_fields_when_set() -> None:
    reply = RespondReply(
        action="accept",
        confidence=0.7,
        evidence=["prior episode agreed"],
        deferred_to="julia-agent",
        reasoning="yielding to domain owner",
    )
    wire = reply.model_dump(exclude_none=True)
    assert wire == {
        "action": "accept",
        "confidence": 0.7,
        "evidence": ["prior episode agreed"],
        "deferred_to": "julia-agent",
        "reasoning": "yielding to domain owner",
    }


def test_respond_reply_offer_allowed_only_for_counter_offer() -> None:
    reply = RespondReply(action="counter_offer", offer={"budget": "low"})
    assert reply.model_dump(exclude_none=True) == {
        "action": "counter_offer",
        "offer": {"budget": "low"},
    }
    with pytest.raises(ValidationError, match="counter_offer"):
        RespondReply(action="accept", offer={"budget": "low"})


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.1, 2.0])
def test_confidence_range_validated_on_both_replies(bad_confidence: float) -> None:
    with pytest.raises(ValidationError):
        ProposeReply(offer={"a": "b"}, confidence=bad_confidence)
    with pytest.raises(ValidationError):
        RespondReply(action="accept", confidence=bad_confidence)


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_boundaries_accepted(boundary: float) -> None:
    assert ProposeReply(offer={"a": "b"}, confidence=boundary).confidence == boundary
    assert RespondReply(action="reject", confidence=boundary).confidence == boundary


def test_evidence_items_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        ProposeReply(offer={"a": "b"}, evidence=["ok", ""])
    with pytest.raises(ValidationError, match="non-empty"):
        RespondReply(action="accept", evidence=["   "])


def test_deferred_to_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        RespondReply(action="accept", deferred_to="")


# ── tick / consensus parsing ─────────────────────────────────────────────────


def _tick_payload(**extra) -> dict:
    return {
        "action": "propose",
        "session_id": "s1",
        "participant_id": "agent-a",
        "round": 1,
        **extra,
    }


def test_negotiate_payload_parses_team_prior() -> None:
    payload = NegotiatePayload.model_validate(
        _tick_payload(
            team_prior={
                "confidence": 0.72,
                "provenance_weight": 0.85,
                "episode_count": 3,
                "source": "knowledge-ce",
            }
        )
    )
    assert payload.team_prior is not None
    assert payload.team_prior.confidence == 0.72
    assert payload.team_prior.provenance_weight == 0.85
    assert payload.team_prior.episode_count == 3
    assert payload.team_prior.source == "knowledge-ce"


def test_negotiate_payload_team_prior_optional_and_source_optional() -> None:
    assert NegotiatePayload.model_validate(_tick_payload()).team_prior is None
    payload = NegotiatePayload.model_validate(
        _tick_payload(team_prior={"confidence": 0.5, "provenance_weight": 1.0, "episode_count": 1})
    )
    assert payload.team_prior is not None
    assert payload.team_prior.source is None


def test_inbound_tick_envelope_round_trips_team_prior() -> None:
    tick = InboundTick.model_validate(
        {
            "kind": "negotiate",
            "payload": _tick_payload(
                team_prior={"confidence": 0.6, "provenance_weight": 0.9, "episode_count": 2}
            ),
        }
    )
    assert tick.payload.team_prior is not None
    assert tick.payload.team_prior.episode_count == 2


def test_consensus_content_parses_metrics_and_cfn_persisted() -> None:
    content = ConsensusContent.model_validate(
        {
            "plan": "do the thing",
            "assignments": {"agent-a": "task"},
            "metrics": {
                "mpc": 0.82,
                "gar": 0.75,
                "scr": 0.25,
                "provenance_weight": 0.56,
                "participants": 3,
            },
            "cfn_persisted": True,
        }
    )
    assert content.metrics is not None
    assert content.metrics.mpc == 0.82
    assert content.metrics.participants == 3
    assert content.cfn_persisted is True


def test_consensus_content_legacy_shape_still_parses() -> None:
    content = ConsensusContent.model_validate({"plan": "p", "broken": False})
    assert content.metrics is None
    assert content.cfn_persisted is None


# ── CLI flag → wire-format serialization ─────────────────────────────────────


def _patch_propose_plumbing(monkeypatch: pytest.MonkeyPatch, posts: list[str]) -> None:
    """Stub config/room/snap plumbing so `negotiate propose` reaches _post."""
    fake_config = SimpleNamespace(
        server=SimpleNamespace(api_url="http://localhost:8000"),
        get_current_identity=lambda: "agent-a",
    )
    monkeypatch.setattr(negotiate_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr("mycelium.commands.room._resolve_room", lambda _c, _r: "test-room")
    monkeypatch.setattr(negotiate_cmd, "_resolve_active_session_room", lambda _c, r: r)
    # 404 from the negotiation endpoint → snap step is skipped entirely.
    monkeypatch.setattr(
        negotiate_cmd.httpx, "get", lambda *_a, **_kw: SimpleNamespace(status_code=404)
    )
    monkeypatch.setattr(
        negotiate_cmd, "_post", lambda _ctx, _room, _handle, content: posts.append(content)
    )


def _patch_respond_plumbing(monkeypatch: pytest.MonkeyPatch, posts: list[str]) -> None:
    monkeypatch.setattr(
        negotiate_cmd, "_post", lambda _ctx, _room, _handle, content: posts.append(content)
    )


def test_propose_without_flags_posts_legacy_wire_json(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_propose_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(negotiate_cmd.app, ["propose", "budget=high"])

    assert result.exit_code == 0, result.output
    assert posts == ['{"offer": {"budget": "high"}}']


def test_propose_with_flags_posts_epistemic_wire_json(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_propose_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(
        negotiate_cmd.app,
        [
            "propose",
            "budget=high",
            "--confidence",
            "0.8",
            "--evidence",
            "Q3 revenue up 12%",
            "--evidence",
            "prior sprint under budget",
            "--reasoning",
            "growth justifies spend",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(posts[0]) == {
        "offer": {"budget": "high"},
        "confidence": 0.8,
        "evidence": ["Q3 revenue up 12%", "prior sprint under budget"],
        "reasoning": "growth justifies spend",
    }


def test_propose_rejects_out_of_range_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_propose_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(
        negotiate_cmd.app, ["propose", "budget=high", "--confidence", "1.5"]
    )

    assert result.exit_code == 1
    assert "--confidence must be between 0.0 and 1.0" in result.output
    assert posts == []


def test_respond_without_flags_posts_legacy_wire_json(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_respond_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(negotiate_cmd.app, ["respond", "accept"])

    assert result.exit_code == 0, result.output
    assert posts == ['{"action": "accept"}']


def test_respond_with_flags_posts_epistemic_wire_json(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_respond_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(
        negotiate_cmd.app,
        [
            "respond",
            "accept",
            "--confidence",
            "0.7",
            "--evidence",
            "prior episode agreed",
            "--reasoning",
            "yielding to domain owner",
            "--defer-to",
            "julia-agent",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(posts[0]) == {
        "action": "accept",
        "confidence": 0.7,
        "evidence": ["prior episode agreed"],
        "deferred_to": "julia-agent",
        "reasoning": "yielding to domain owner",
    }


@pytest.mark.parametrize("action", ["reject", "end"])
def test_respond_defer_to_only_valid_with_accept(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    posts: list[str] = []
    _patch_respond_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(negotiate_cmd.app, ["respond", action, "--defer-to", "julia-agent"])

    assert result.exit_code == 1
    assert "--defer-to is only valid with 'accept'" in result.output
    assert posts == []


def test_respond_rejects_out_of_range_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []
    _patch_respond_plumbing(monkeypatch, posts)

    result = CliRunner().invoke(negotiate_cmd.app, ["respond", "accept", "--confidence", "-0.2"])

    assert result.exit_code == 1
    assert "--confidence must be between 0.0 and 1.0" in result.output
    assert posts == []


# ── session await output helpers ─────────────────────────────────────────────


def test_tick_output_includes_team_prior_only_when_present() -> None:
    from mycelium.commands.session import _tick_output

    legacy = _tick_output("room-a", {"round": 1, "action": "propose"})
    assert "team_prior" not in legacy

    prior = {"confidence": 0.72, "provenance_weight": 0.85, "episode_count": 3}
    enriched = _tick_output("room-a", {"round": 1, "action": "propose", "team_prior": prior})
    assert enriched["team_prior"] == prior


def test_consensus_output_includes_metrics_only_when_present() -> None:
    from mycelium.commands.session import _consensus_output

    legacy = _consensus_output("room-a", {"plan": "p"})
    assert "metrics" not in legacy
    assert "cfn_persisted" not in legacy

    metrics = {"mpc": 0.82, "gar": 0.75, "scr": 0.25, "provenance_weight": 0.56, "participants": 3}
    enriched = _consensus_output("room-a", {"plan": "p", "metrics": metrics, "cfn_persisted": True})
    assert enriched["metrics"] == metrics
    assert enriched["cfn_persisted"] is True


# ── .env emission ────────────────────────────────────────────────────────────


def _parse_env(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_env_omits_cfn_api_flavor() -> None:
    """The 2.0.0 cutover removed the dual-stack flavor flag entirely."""
    env = _parse_env(generate_env_file(MyceliumConfig()))
    assert "CFN_API_FLAVOR" not in env
