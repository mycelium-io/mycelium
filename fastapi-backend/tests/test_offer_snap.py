# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for fuzzy offer snapping (app/services/offer_snap.py).

Covers the tiers that rescue LLM near-misses onto canonical options, the
all-or-nothing ``snap_offer`` contract, and — crucially — that snapping
*refuses* to fabricate a value that has no near-match (the numeric out-of-grid
case that must stay a real reject, not get forced to a wrong number).
"""

from __future__ import annotations

from app.services.offer_snap import snap, snap_offer


def test_snap_exact_and_case_insensitive() -> None:
    assert snap("30", ["25", "30", "35"]) == "30"
    assert snap("EXPRESS", ["express", "standard"]) == "express"


def test_snap_normalized_key_form() -> None:
    # underscores / hyphens / spacing collapse to the same normalized form
    assert snap("tech-allocation", ["tech_allocation", "cap"]) == "tech_allocation"
    assert snap("Tech Allocation", ["tech_allocation", "cap"]) == "tech_allocation"


def test_snap_fuzzy_format_near_miss() -> None:
    # "30%" vs "30" — a formatting near-miss the interpreter LLM commonly emits
    assert snap("30%", ["25", "30", "35"]) == "30"
    assert snap("express delivery", ["express", "standard"]) == "express"


def test_snap_refuses_distinct_numbers() -> None:
    # THE important one: 30 is not near 25 or 35 — snap must NOT force it to a
    # wrong number (that out-of-grid case is a discovery problem, not snapping).
    assert snap("30", ["25", "35"]) is None
    assert snap("blue", ["red", "green"]) is None


def test_snap_numeric_between_grid_points_to_nearest() -> None:
    """THE phantom-convergence fix: a real counter that lands between grid points
    ('28' against {20,25,30,35,40}) snaps to the nearest option ('30'), not dropped.
    difflib scores '28' vs '30' at 0, so string-tier snapping would have refused it
    → the proposer would be recorded as holding the standing offer (fabricated)."""
    grid = ["20", "25", "30", "35", "40"]
    assert snap("28", grid) == "30"  # 0.4 steps from 30 — clear nearest
    assert snap("32", grid) == "30"  # nearest is 30, not 35
    assert snap("33", grid) == "35"
    assert snap("27", grid) == "25"


def test_snap_numeric_refuses_off_grid_and_ties() -> None:
    """Numeric snapping still refuses to fabricate: a value far off the grid, and a
    genuine midpoint tie (equidistant from two options → a discovery gap, not a
    snap), both yield None rather than an arbitrary wrong number."""
    grid = ["20", "25", "30", "35", "40"]
    assert snap("100", grid) is None  # >1 step past the top → off-grid
    assert snap("5", grid) is None  # >1 step below the bottom → off-grid
    assert snap("30", ["25", "35"]) is None  # exact midpoint, ambiguous → refuse
    assert snap("22.5", ["20", "25"]) is None  # tie between 20 and 25


def test_snap_offer_resolves_key_and_value() -> None:
    got = snap_offer(
        {"tech-allocation": "30%"},
        ["tech_allocation"],
        {"tech_allocation": ["25", "30", "35"]},
    )
    assert got == {"tech_allocation": "30"}


def test_snap_offer_all_or_nothing() -> None:
    opts = {"tech_allocation": ["25", "35"], "cap": ["on", "off"]}
    names = ["tech_allocation", "cap"]
    # tech value 30 has no near-match in {25,35} → whole offer fails (no partial)
    assert snap_offer({"tech_allocation": "30", "cap": "on"}, names, opts) is None
    # a missing issue also fails all-or-nothing
    assert snap_offer({"tech_allocation": "25"}, names, opts) is None
    # both resolvable → snapped map
    assert snap_offer({"tech_allocation": "35", "cap": "ON"}, names, opts) == {
        "tech_allocation": "35",
        "cap": "on",
    }


def test_snap_offer_rejects_non_dict() -> None:
    assert snap_offer("nope", ["x"], {"x": ["a"]}) is None  # type: ignore[arg-type]
