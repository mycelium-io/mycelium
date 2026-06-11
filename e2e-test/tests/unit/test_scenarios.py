"""Unit tests for :mod:`testcases.scenarios`.

These tests don't run pyATS — they only exercise the factory plumbing
(row parsing, tier gating, class naming, timeout calculation). The
actual ``aetest.Testcase`` execution path is covered by the collection
smoke test under tests/unit/test_scenarios_collection.py.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from testcases.scenarios import (
    _ADAPTER_ROUND_BUDGET_SECONDS,
    _DEFAULT_TIMEOUT_FLOOR,
    active_tiers,
    class_name_for,
    compute_timeout_seconds,
    filter_by_tier,
    groups_for,
    load_rows,
    make_scenarios,
    validate_row,
)

# ── load_rows / validate_row ────────────────────────────────────────


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "scenarios.yaml"
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_load_rows_parses_minimal_row(tmp_path: Path):
    p = _write_yaml(
        tmp_path,
        """
        scenarios:
          - name: t1
            tier: pr
            category: core
            agents:
              - {handle: a, adapter: openclaw, host: hub}
              - {handle: b, adapter: openclaw, host: spoke1}
    """,
    )
    rows = load_rows(p)
    assert len(rows) == 1
    assert rows[0]["name"] == "t1"


def test_load_rows_rejects_unknown_tier(tmp_path: Path):
    p = _write_yaml(
        tmp_path,
        """
        scenarios:
          - name: t2
            tier: yearly
            agents:
              - {handle: a, adapter: openclaw, host: hub}
              - {handle: b, adapter: openclaw, host: spoke1}
    """,
    )
    with pytest.raises(ValueError, match="tier"):
        load_rows(p)


def test_load_rows_rejects_unknown_adapter(tmp_path: Path):
    p = _write_yaml(
        tmp_path,
        """
        scenarios:
          - name: t3
            tier: pr
            agents:
              - {handle: a, adapter: matrix, host: hub}
              - {handle: b, adapter: openclaw, host: spoke1}
    """,
    )
    with pytest.raises(ValueError, match="adapter"):
        load_rows(p)


def test_load_rows_rejects_single_agent(tmp_path: Path):
    p = _write_yaml(
        tmp_path,
        """
        scenarios:
          - name: t4
            tier: pr
            agents:
              - {handle: a, adapter: openclaw, host: hub}
    """,
    )
    with pytest.raises(ValueError, match="at least two"):
        load_rows(p)


def test_load_rows_rejects_missing_required_fields(tmp_path: Path):
    p = _write_yaml(
        tmp_path,
        """
        scenarios:
          - name: t5
            tier: pr
            agents:
              - {adapter: openclaw, host: hub}
              - {handle: b, adapter: openclaw, host: spoke1}
    """,
    )
    with pytest.raises(ValueError, match="handle"):
        load_rows(p)


def test_load_rows_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_rows(tmp_path / "nope.yaml")


# ── active_tiers / filter_by_tier ───────────────────────────────────


def test_active_tiers_unset_means_all():
    assert active_tiers(None) == frozenset({"pr", "nightly", "weekly"})


def test_active_tiers_empty_means_all():
    assert active_tiers("") == frozenset({"pr", "nightly", "weekly"})


def test_active_tiers_all_literal():
    assert active_tiers("all") == frozenset({"pr", "nightly", "weekly"})


def test_active_tiers_comma_separated():
    assert active_tiers("pr,nightly") == frozenset({"pr", "nightly"})


def test_active_tiers_drops_unknown_tokens():
    # "weekend" is invalid; only `pr` survives.
    assert active_tiers("pr,weekend") == frozenset({"pr"})


def test_active_tiers_invalid_only_means_empty():
    # All tokens invalid → empty set so misconfigured CI fails loudly.
    assert active_tiers("foo,bar") == frozenset()


def test_filter_by_tier_excludes_other_tiers():
    rows = [
        {"name": "a", "tier": "pr"},
        {"name": "b", "tier": "nightly"},
        {"name": "c", "tier": "weekly"},
    ]
    filtered = filter_by_tier(rows, frozenset({"pr"}))
    assert [r["name"] for r in filtered] == ["a"]


# ── class_name_for ──────────────────────────────────────────────────


def test_class_name_explicit_base():
    row = {
        "name": "anything",
        "base_name": "TwoAgentConsensus",
        "agents": [
            {"handle": "a", "adapter": "openclaw", "host": "hub"},
            {"handle": "b", "adapter": "cursor", "host": "spoke1"},
        ],
    }
    assert class_name_for(row) == "TwoAgentConsensus_oc_cu"


def test_class_name_derived_from_name():
    row = {
        "name": "two-agent-consensus-oc-cu",
        "agents": [
            {"handle": "a", "adapter": "openclaw", "host": "hub"},
            {"handle": "b", "adapter": "cursor", "host": "spoke1"},
        ],
    }
    # Adapter shortcodes are stripped from the camel-case prefix and
    # then re-appended as the deterministic suffix.
    assert class_name_for(row) == "TwoAgentConsensus_oc_cu"


def test_class_name_three_agent_combo():
    row = {
        "name": "three-agent-consensus",
        "agents": [
            {"handle": "a", "adapter": "openclaw", "host": "hub"},
            {"handle": "b", "adapter": "cursor", "host": "spoke1"},
            {"handle": "c", "adapter": "hermes", "host": "spoke2"},
        ],
    }
    assert class_name_for(row) == "ThreeAgentConsensus_oc_cu_he"


# ── groups_for ──────────────────────────────────────────────────────


def test_groups_for_single_adapter():
    row = {
        "tier": "pr",
        "category": "core",
        "agents": [
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
        ],
    }
    groups = groups_for(row)
    assert "pr" in groups
    assert "core" in groups
    assert "openclaw" in groups
    assert "cross_family" not in groups


def test_groups_for_cross_family():
    row = {
        "tier": "nightly",
        "category": "cross_channel",
        "agents": [
            {"adapter": "openclaw"},
            {"adapter": "cursor"},
            {"adapter": "hermes"},
        ],
    }
    groups = groups_for(row)
    assert "cross_family" in groups
    assert {"openclaw", "cursor", "hermes"}.issubset(set(groups))


# ── compute_timeout_seconds ─────────────────────────────────────────


def test_timeout_explicit_override_wins():
    row = {
        "timeout_seconds": 42,
        "agents": [{"adapter": "cursor"}, {"adapter": "cursor"}],
    }
    assert compute_timeout_seconds(row) == 42


def test_timeout_uses_worst_case_adapter():
    """cu > he > oc — cursor inflation should set the budget."""
    row = {
        "n_steps_total": 10,
        "agents": [
            {"adapter": "openclaw"},
            {"adapter": "cursor"},  # worst (60s/round)
        ],
    }
    # 2 agents → no multi-agent tax; 10 rounds × 60s = 600s.
    expected = 10 * _ADAPTER_ROUND_BUDGET_SECONDS["cursor"]
    assert compute_timeout_seconds(row) == expected


def test_timeout_respects_floor_for_fast_combos():
    row = {
        "n_steps_total": 2,
        "agents": [{"adapter": "openclaw"}, {"adapter": "openclaw"}],
    }
    # 2 × 25 = 50s, well under the floor — floor wins.
    assert compute_timeout_seconds(row) == _DEFAULT_TIMEOUT_FLOOR


def test_timeout_adds_multi_agent_tax_for_n_gt_2():
    """3+ agents add a 15% per-extra-agent overhead.

    Models the lab-observed reality that round trips wait on the
    *slowest* reply and the proposer rotation lengthens the wait
    queue. Without this, ThreeAgentReturnTrip false-fails before
    the CFN finishes a 10-round bicker session.
    """
    row = {
        "n_steps_total": 10,
        "agents": [
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
        ],
    }
    # 10 × 25 × (1 + 0.15 * 1) = 287 → floor (360) wins.
    assert compute_timeout_seconds(row) == _DEFAULT_TIMEOUT_FLOOR

    big_row = {
        "n_steps_total": 20,
        "agents": [
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
            {"adapter": "openclaw"},
        ],
    }
    # 20 × 25 × (1 + 0.15 * 2) = 650; above the floor.
    assert compute_timeout_seconds(big_row) == int(20 * 25 * 1.30)


# ── make_scenarios ──────────────────────────────────────────────────


def test_make_scenarios_generates_one_class_per_row():
    rows = [
        {
            "name": "two-agent-consensus-oc-oc",
            "tier": "pr",
            "category": "core",
            "agents": [
                {"handle": "a", "adapter": "openclaw", "host": "hub"},
                {"handle": "b", "adapter": "openclaw", "host": "spoke1"},
            ],
        },
        {
            "name": "two-agent-consensus-oc-cu",
            "tier": "nightly",
            "category": "cross_channel",
            "agents": [
                {"handle": "a", "adapter": "openclaw", "host": "hub"},
                {"handle": "b", "adapter": "cursor", "host": "spoke1"},
            ],
        },
    ]
    cls_dict = make_scenarios(rows)
    assert "TwoAgentConsensus_oc_oc" in cls_dict
    assert "TwoAgentConsensus_oc_cu" in cls_dict

    oc_oc = cls_dict["TwoAgentConsensus_oc_oc"]
    # Generated class carries the row + groups
    assert oc_oc._row["name"] == "two-agent-consensus-oc-oc"
    assert "pr" in oc_oc.groups
    assert "openclaw" in oc_oc.groups


def test_make_scenarios_duplicate_class_names_raise():
    rows = [
        {
            "name": "two-agent-consensus-oc-oc",
            "tier": "pr",
            "category": "core",
            "agents": [
                {"handle": "a", "adapter": "openclaw", "host": "hub"},
                {"handle": "b", "adapter": "openclaw", "host": "spoke1"},
            ],
        },
        {
            # Same base_name + same adapter combo → same class name
            "name": "duplicate-oops",
            "base_name": "TwoAgentConsensus",
            "tier": "weekly",
            "category": "core",
            "agents": [
                {"handle": "a", "adapter": "openclaw", "host": "hub"},
                {"handle": "b", "adapter": "openclaw", "host": "spoke2"},
            ],
        },
    ]
    with pytest.raises(ValueError, match="duplicate"):
        make_scenarios(rows)


# ── shipped scenarios.yaml is valid ────────────────────────────────


def test_shipped_scenarios_yaml_loads():
    """Sanity check: ship matrix must parse + materialise classes cleanly.

    This is the first line of defence against malformed YAML edits —
    if the file can't be loaded, the suite collection import will
    blow up at CI runtime; we catch it here instead.
    """
    p = Path(__file__).resolve().parent.parent.parent / "data" / "scenarios.yaml"
    rows = load_rows(p)
    assert len(rows) >= 6  # PR canaries + a few nightly rows
    cls_dict = make_scenarios(rows)
    assert len(cls_dict) == len(rows)


def test_shipped_scenarios_yaml_has_pr_canaries():
    """PR tier must include at least one broad-coverage row + the shakedown."""
    p = Path(__file__).resolve().parent.parent.parent / "data" / "scenarios.yaml"
    rows = load_rows(p)
    pr_rows = [r for r in rows if r.get("tier") == "pr"]
    assert pr_rows, "no PR-tier scenarios in data/scenarios.yaml"

    # The broad canary should have both memory_writes and search_queries
    broad = [r for r in pr_rows if r.get("memory_writes") and r.get("search_queries")]
    assert broad, "expected at least one PR row with broad-coverage asserts"

    # The shakedown should explicitly allow timeouts.
    shakedowns = [r for r in pr_rows if r.get("require_consensus") is False]
    assert shakedowns, "expected at least one cross-family shakedown row in PR tier"


def test_validate_row_passes_for_minimal_valid_row():
    row = {
        "name": "x",
        "tier": "pr",
        "agents": [
            {"handle": "a", "adapter": "openclaw", "host": "hub"},
            {"handle": "b", "adapter": "openclaw", "host": "spoke1"},
        ],
    }
    validate_row(row, position=0, source="<test>")  # no raise
