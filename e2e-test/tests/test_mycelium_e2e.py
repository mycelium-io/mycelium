"""
Pytest suite for Mycelium end-to-end integration tests.

Run from the repo root::

    pytest tests/ -v

Slow / LLM-heavy sections are marked ``@pytest.mark.slow`` / ``@pytest.mark.llm``.
Multi-agent convergence tests are marked ``@pytest.mark.convergence``.
"""

from __future__ import annotations

import pytest

from mycelium_e2e.bundle import (
    TestContext,
    test_consensus_cli_e2e as section_consensus_cli_e2e,
    test_consensus_negotiation as section_consensus_negotiation,
    test_demo_script_negotiation_coverage as section_demo_script_negotiation,
    test_doctor_clean as section_doctor_clean,
    test_ioc_cfn as section_ioc_cfn,
    test_ioc_full_path as section_ioc_full_path,
    test_ioc_negotiation_path as section_ioc_negotiation_path,
    test_matrix_communication as section_matrix_communication,
    test_memory_reads as section_memory_reads,
    test_multi_agent_memory as section_multi_agent_memory,
    test_reindex as section_reindex,
    test_room_lifecycle as section_room_lifecycle,
    test_semantic_search as section_semantic_search,
    test_session_join_idempotency as section_session_join_idempotency,
    test_shared_memory_cli_e2e as section_shared_memory_cli_e2e,
    test_sync_negotiation_cli_e2e as section_sync_negotiation_cli_e2e,
    test_synthesis as section_synthesis,
    # New convergence scenario tests
    test_three_agent_negotiation as section_three_agent_negotiation,
    test_architecture_decision as section_architecture_decision,
    test_resource_allocation as section_resource_allocation,
    test_asymmetric_stakes as section_asymmetric_stakes,
    test_preexisting_context as section_preexisting_context,
    test_feature_prioritization as section_feature_prioritization,
    test_consensus_stability as section_consensus_stability,
    # OpenClaw skill verification
    test_openclaw_mycelium_skill as section_openclaw_mycelium_skill,
    test_openclaw_agent_mycelium_execution as section_openclaw_agent_execution,
)


def _assert_new_checks(ctx: TestContext, start: int) -> None:
    new = ctx.results[start:]
    failed = [r for r in new if not r.passed and not r.skipped]
    if failed:
        msg = "\n".join(f"{r.name}: {r.error}" for r in failed)
        pytest.fail(msg)


def test_00_environment_detected(bundle_ctx: TestContext) -> None:
    """Environment probe runs in the session fixture; assert minimal signals."""
    assert bundle_ctx.env_info.get("backend_status") is not None


def test_01_room_lifecycle(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_room_lifecycle(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_02_multi_agent_memory(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_multi_agent_memory(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_03_memory_reads(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_memory_reads(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_04_semantic_search(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_semantic_search(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
def test_05_synthesis(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_synthesis(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.slow
def test_06_consensus_negotiation(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_consensus_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_06b_session_join_idempotency(bundle_ctx: TestContext) -> None:
    """Regression: PR #286 — session join is idempotent (#280, #284).

    Two simultaneous first-joins to a new room must produce exactly one
    CoordinationSession (no fork); a handle joining twice must produce one
    Participant row (no duplicate that breaks NegMAS quorum at 2N).
    """
    n = len(bundle_ctx.results)
    section_session_join_idempotency(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_06c_doctor_clean(bundle_ctx: TestContext) -> None:
    """`mycelium doctor` reports no error-level checks.

    Catches stale alembic migrations (PR #273) and adapter drift before
    downstream tests start failing in confusing ways.
    """
    n = len(bundle_ctx.results)
    section_doctor_clean(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.matrix
def test_07_matrix_communication(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_matrix_communication(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.cfn
def test_08_ioc_cfn(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_ioc_cfn(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.cfn
def test_09_ioc_full_path(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_ioc_full_path(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.cfn
@pytest.mark.llm
@pytest.mark.slow
def test_10_ioc_negotiation_path(bundle_ctx: TestContext) -> None:
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_ioc_negotiation_path(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_11_shared_memory_cli_e2e(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_shared_memory_cli_e2e(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
def test_12_consensus_cli_e2e(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_consensus_cli_e2e(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
def test_13_sync_negotiation_cli_e2e(bundle_ctx: TestContext) -> None:
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_sync_negotiation_cli_e2e(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
def test_14_demo_script_negotiation(bundle_ctx: TestContext) -> None:
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_demo_script_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_15_three_agent_negotiation(bundle_ctx: TestContext) -> None:
    """Three agents with different priorities (speed/quality/cost) negotiate release planning."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_three_agent_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_16_architecture_decision(bundle_ctx: TestContext) -> None:
    """Technical architecture decision: PostgreSQL vs MongoDB advocacy."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_architecture_decision(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_17_resource_allocation(bundle_ctx: TestContext) -> None:
    """Resource allocation: sprint capacity split between features and bugs."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_resource_allocation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_18_asymmetric_stakes(bundle_ctx: TestContext) -> None:
    """Asymmetric stakes: one agent has hard deadline, other is flexible."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_asymmetric_stakes(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_19_preexisting_context(bundle_ctx: TestContext) -> None:
    """Pre-existing context: negotiation with prior decisions in memory."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_preexisting_context(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_20_feature_prioritization(bundle_ctx: TestContext) -> None:
    """Feature prioritization: sales vs engineering priorities for roadmap."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_feature_prioritization(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
def test_21_consensus_stability(bundle_ctx: TestContext) -> None:
    """Consensus stability: verify agreement persists and new agents see it."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    section_consensus_stability(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


def test_22_reindex(bundle_ctx: TestContext) -> None:
    n = len(bundle_ctx.results)
    section_reindex(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


# ─────────────────────────────────────────────────────────────────────────────
# Matrix E2E Tests (true end-to-end via Element/Matrix)
# ─────────────────────────────────────────────────────────────────────────────

from mycelium_e2e.matrix_e2e import (
    matrix_two_agent_negotiation,
    matrix_three_agent_negotiation,
    matrix_architecture_decision,
)

from mycelium_e2e.distributed_e2e import (
    distributed_two_agent_negotiation,
    distributed_three_agent_negotiation,
    distributed_architecture_decision,
    distributed_resource_allocation,
    distributed_asymmetric_stakes,
    distributed_preexisting_context,
    distributed_feature_prioritization,
    distributed_backend_resolved_cfn_ids,
    skill_cross_channel_return_trip,
)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.matrix_e2e
def test_30_matrix_two_agent_negotiation(bundle_ctx: TestContext) -> None:
    """Two OpenClaw agents negotiate through Matrix (true E2E via OpenClaw hooks)."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    matrix_two_agent_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.matrix_e2e
def test_31_matrix_three_agent_negotiation(bundle_ctx: TestContext) -> None:
    """Three OpenClaw agents negotiate release planning through Matrix (true E2E)."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    matrix_three_agent_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.matrix_e2e
def test_32_matrix_architecture_decision(bundle_ctx: TestContext) -> None:
    """Technical architecture decision through Matrix with OpenClaw agents (true E2E)."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    matrix_architecture_decision(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


# ─────────────────────────────────────────────────────────────────────────────
# Distributed E2E Tests (real agents on oclw3, oclw4, oclw5)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_40_distributed_two_agent(bundle_ctx: TestContext) -> None:
    """Two agents on different devices (oclw4 + oclw3) negotiate via Matrix + Mycelium."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_two_agent_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_41_distributed_three_agent(bundle_ctx: TestContext) -> None:
    """Three agents on three devices (oclw4 + oclw3 + oclw5) negotiate."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_three_agent_negotiation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_42_distributed_architecture(bundle_ctx: TestContext) -> None:
    """Architecture decision with agents on oclw4 + oclw5."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_architecture_decision(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_43_distributed_resource_allocation(bundle_ctx: TestContext) -> None:
    """Three agents negotiate budget/resource allocation across devices."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_resource_allocation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_44_distributed_asymmetric_stakes(bundle_ctx: TestContext) -> None:
    """Negotiation where one agent has higher stakes than the other."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_asymmetric_stakes(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_45_distributed_preexisting_context(bundle_ctx: TestContext) -> None:
    """Agents negotiate with reference to prior decisions/context."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_preexisting_context(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
def test_46_distributed_feature_prioritization(bundle_ctx: TestContext) -> None:
    """Three agents prioritize a backlog of features."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    distributed_feature_prioritization(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.convergence
@pytest.mark.distributed
@pytest.mark.cfn
def test_47_distributed_cross_device_only(bundle_ctx: TestContext) -> None:
    """
    Two remote agents (oclw3 + oclw5) negotiate using IOC backend on oclw4.
    
    This validates that agents on machines WITHOUT the IOC stack can coordinate
    through the centralized backend. No agent from oclw4 participates.
    """
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    from mycelium_e2e.distributed_e2e import distributed_cross_device_only
    distributed_cross_device_only(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


# ─────────────────────────────────────────────────────────────────────────────
# OpenClaw Skill Verification Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.distributed
@pytest.mark.cfn
def test_48_distributed_backend_resolved_cfn_ids(bundle_ctx: TestContext) -> None:
    """
    Verify leaf nodes can ingest knowledge without workspace_id/mas_id (Issue #139).
    
    Tests the backend-resolved CFN IDs feature: leaf nodes only send room_name,
    and the backend resolves workspace_id + mas_id from the room's DB record
    or falls back to system settings.
    """
    n = len(bundle_ctx.results)
    distributed_backend_resolved_cfn_ids(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.distributed
@pytest.mark.cross_channel
def test_49_skill_cross_channel_return_trip(bundle_ctx: TestContext) -> None:
    """
    SKILL.md faithful reproduction: 3 agents on 3 devices, individual DMs,
    dynamic room, full return-trip verification (PR #221).
    """
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    skill_cross_channel_return_trip(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.openclaw
def test_50_openclaw_mycelium_skill(bundle_ctx: TestContext) -> None:
    """Verify the mycelium skill is properly configured in OpenClaw."""
    n = len(bundle_ctx.results)
    section_openclaw_mycelium_skill(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


@pytest.mark.openclaw
@pytest.mark.llm
@pytest.mark.slow
def test_51_openclaw_agent_mycelium_execution(bundle_ctx: TestContext) -> None:
    """Verify an OpenClaw agent can execute mycelium commands via the skill."""
    n = len(bundle_ctx.results)
    section_openclaw_agent_execution(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-Channel Memory Isolation Tests
# ─────────────────────────────────────────────────────────────────────────────

from mycelium_e2e.cross_channel_e2e import (
    cross_channel_memory_isolation,
)


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.matrix_e2e
@pytest.mark.cross_channel
def test_60_cross_channel_memory_isolation(bundle_ctx: TestContext) -> None:
    """Prove cross-channel memory is isolated and show how to bridge the gap."""
    if bundle_ctx.coordination_blocked_reason:
        pytest.skip(bundle_ctx.coordination_blocked_reason)
    n = len(bundle_ctx.results)
    cross_channel_memory_isolation(bundle_ctx)
    _assert_new_checks(bundle_ctx, n)
