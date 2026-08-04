# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the dissent compiler.

All tests use the deterministic ``fallback_body`` path — no LLM calls, no
network. The LLM path is tested separately when MYCELIUM_LLM_TESTS=1 is set.
"""

from __future__ import annotations

import pytest

from app.services.dissent_compiler import compile_dissent, fallback_body

# ── fallback_body ────────────────────────────────────────────────────────────


def _full_kwargs(**overrides):
    base = {
        "session": "demo-room:session:abc123",
        "reason": "timeout",
        "issues": ["deploy_window", "test_coverage"],
        "issue_options": {
            "deploy_window": ["24h", "48h", "72h"],
            "test_coverage": ["none", "smoke", "full"],
        },
        "current_offer": {"deploy_window": "48h", "test_coverage": "smoke"},
        "last_actions": {
            "sre-agent": "accept",
            "pm-agent": "reject",
            "eng-lead": "counter_offer",
        },
        "last_round_outcome": "rejected_by_pm-agent",
        "joined_intents": "sre-agent: ship now\npm-agent: 2-week delay\neng-lead: fix-forward",
        "session_handles": ["sre-agent", "pm-agent", "eng-lead"],
        "round_num": 7,
    }
    base.update(overrides)
    return base


def test_fallback_body_contains_heading():
    body = fallback_body(**_full_kwargs())
    assert body.startswith("# Unresolved Tensions")


def test_fallback_body_contains_issues():
    body = fallback_body(**_full_kwargs())
    assert "deploy_window" in body
    assert "test_coverage" in body


def test_fallback_body_contains_last_offer():
    body = fallback_body(**_full_kwargs())
    assert "48h" in body
    assert "smoke" in body


def test_fallback_body_contains_valid_options():
    body = fallback_body(**_full_kwargs())
    assert "24h" in body or "72h" in body  # options listed


def test_fallback_body_contains_agent_actions():
    body = fallback_body(**_full_kwargs())
    assert "sre-agent" in body
    assert "pm-agent" in body
    assert "eng-lead" in body
    # Human-readable action labels
    assert "accepted" in body
    assert "rejected" in body
    assert "counter-offered" in body


def test_fallback_body_blocking_pattern():
    body = fallback_body(**_full_kwargs())
    # last_round_outcome is rendered (underscores → spaces)
    assert "rejected" in body and "pm-agent" in body


def test_fallback_body_includes_opening_intents():
    body = fallback_body(**_full_kwargs())
    assert "fix-forward" in body


def test_fallback_body_human_questions_section():
    body = fallback_body(**_full_kwargs())
    assert "Recommended" in body


def test_fallback_body_session_context():
    body = fallback_body(**_full_kwargs())
    assert "demo-room:session:abc123" in body
    assert "7" in body  # round_num


def test_fallback_body_reason_abort():
    body = fallback_body(**_full_kwargs(reason="abort"))
    assert "aborted" in body.lower()


def test_fallback_body_reason_timeout():
    body = fallback_body(**_full_kwargs(reason="timeout"))
    assert "round budget" in body.lower() or "did not respond" in body.lower()


def test_fallback_body_no_issues():
    """Partial state (impasse before round 1) still produces a valid artifact."""
    body = fallback_body(**_full_kwargs(issues=None, issue_options=None, current_offer=None))
    assert "# Unresolved Tensions" in body
    assert "Recommended" in body


def test_fallback_body_no_last_actions():
    """Empty last_actions produces artifact without the positions section crashing."""
    body = fallback_body(**_full_kwargs(last_actions={}, session_handles=[]))
    assert "# Unresolved Tensions" in body


def test_fallback_body_first_round_outcome_suppressed():
    """first_round outcome should NOT appear as a blocking pattern — it's the default."""
    body = fallback_body(**_full_kwargs(last_round_outcome="first_round"))
    assert "Blocking pattern" not in body


def test_fallback_body_timeout_action_label():
    body = fallback_body(**_full_kwargs(last_actions={"quiet-agent": "timeout"}))
    assert "did not respond" in body


# ── compile_dissent (deterministic path) ────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_dissent_deterministic_returns_body():
    body = await compile_dissent(**_full_kwargs())
    assert "# Unresolved Tensions" in body
    assert "deploy_window" in body


@pytest.mark.asyncio
async def test_compile_dissent_use_llm_false_is_default():
    """compile_dissent() with no use_llm flag behaves identically to fallback_body."""
    deterministic = fallback_body(**_full_kwargs())
    compiled = await compile_dissent(**_full_kwargs())
    assert compiled == deterministic
