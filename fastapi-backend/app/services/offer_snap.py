# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Fuzzy snapping of interpreted SAO offers onto the canonical issue/option set.

The mediator's ``interpret`` stage asks an LLM to map an agent's prose into an
offer ``{issue: option}``. LLMs routinely return keys/values that are *almost*
the canonical ones registered at issue-discovery time — ``"Tech"`` for
``tech_allocation``, ``"30%"`` for ``"30"``, ``"express delivery"`` for
``"express"``. Left alone, ``to_outcome`` rejects the whole offer (a value not
exactly in the option list), which downgrades a real move to a reject and — over
a live negotiation — cascades into timeouts and misreported agreements.

This snaps such near-misses to the nearest canonical value before rejecting,
mirroring the good part of the sibling `ioc-scale-cf-cognition-engines`
`offer_validation.py` (their 5-tier rapidfuzz/embedding version). We keep it
**stdlib-only** (`difflib`) deliberately: option lists here are tiny (a handful
per issue) and snapping runs once per agent turn, so a heavy fuzzy dep buys
nothing. Order: exact → case-insensitive → normalised → `difflib` ratio.

**Numbers are snapped numerically, not by string ratio.** `difflib` is meaningless
on digits — "28" vs "30" scores 0, "32" vs "35" scores 50 — so a real numeric
counter that lands *between* grid points ("offer 28" against a {20,25,30,35,40}
grid) would score below threshold and be dropped, which downstream fabricates a
phantom position (the proposer silently recorded as holding the standing offer).
For an issue whose options are all numeric, we instead snap to the *nearest*
option within one grid-step, so "28"→"30" faithfully, and refuse (return `None`)
only for a value genuinely off the grid ("1000"), never fabricating.

**What snapping does NOT fix:** a value with no near-match at all (the agents
agreed 30% but the grid only has {25, 35}, more than a step away). That is an
issue-*discovery* problem — the grid must contain the meeting point — not a
snapping one, and numeric snapping correctly refuses it rather than forcing it.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import pairwise

#: Minimum `difflib` similarity (0-100) for a fuzzy (non-exact) snap. 80 rescues
#: typos / formatting / word-order noise while refusing to collapse genuinely
#: distinct options (e.g. two different numbers).
_SNAP_THRESHOLD = 80.0

#: A numeric value snaps to the nearest option only if it lands within this many
#: grid-steps of it. 1.0 accepts anything inside the range (always within half a
#: step of some option) plus reasonable clamping just outside; it refuses a value
#: several steps off the grid rather than fabricate one.
_NUMERIC_STEP_TOLERANCE = 1.0


def _as_float(text: str) -> float | None:
    """Parse a numeric token, tolerating a trailing ``%`` or surrounding space."""
    try:
        return float(str(text).strip().rstrip("%").strip())
    except (ValueError, AttributeError):
        return None


def _numeric_snap(raw: str, valid: list[str]) -> str | None | bool:
    """Nearest-numeric snap for a numeric issue.

    Returns the matching option token if *raw* and every option parse as numbers,
    *raw* has one unambiguous nearest option (not an exact tie between two — a true
    midpoint like 30 in {25,35} is a grid-discovery gap, not a snap), and that
    nearest is within :data:`_NUMERIC_STEP_TOLERANCE` grid-steps. Returns ``None``
    when it *is* a numeric issue but *raw* is off-grid or ambiguous (an
    authoritative refusal — do NOT fall through to `difflib`, which would mis-score
    digits). Returns ``False`` when this is not a numeric issue at all, signalling
    the caller to keep going with the string tiers.
    """
    raw_val = _as_float(raw)
    if raw_val is None:
        return False
    parsed: list[tuple[float, str]] = []
    for v in valid:
        f = _as_float(v)
        if f is None:
            return False  # not a numeric issue — let the string tiers handle it
        parsed.append((f, v))
    if not parsed:
        return False
    nums = sorted(f for f, _ in parsed)
    gaps = [b - a for a, b in pairwise(nums) if b > a]
    step = min(gaps) if gaps else max(abs(nums[0]), 1.0)
    dists = sorted((abs(raw_val - f), v) for f, v in parsed)
    best_dist, best_token = dists[0]
    if best_dist > step * _NUMERIC_STEP_TOLERANCE:
        return None  # genuinely off the grid — refuse, never fabricate
    if len(dists) > 1 and dists[1][0] == best_dist:
        return None  # exact tie (ambiguous midpoint) — a discovery gap, not a snap
    return best_token


def _normalise(text: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(text).strip().lower())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100.0


def snap(raw: str, valid: list[str], *, threshold: float = _SNAP_THRESHOLD) -> str | None:
    """Return the canonical member of *valid* matching *raw*, or ``None``.

    Tiers, first match wins: exact, case-insensitive, normalised, then a
    ``difflib`` ratio at/above *threshold* (best match). ``None`` means *raw* is
    too far from every option to snap — the caller should treat that as a real
    mismatch, not force it.
    """
    s = str(raw)
    if s in valid:
        return s
    for v in valid:
        if s.lower() == v.lower():
            return v
    s_norm = _normalise(s)
    for v in valid:
        if s_norm == _normalise(v):
            return v
    # Numbers snap numerically, not by string ratio (difflib is meaningless on
    # digits). For a numeric issue this is authoritative: a match, or a refusal —
    # never falling through to difflib. ``False`` means "not numeric, keep going".
    numeric = _numeric_snap(s, valid)
    if numeric is not False:
        return numeric  # type: ignore[return-value]
    # Token containment — "express delivery" ~ "express" (the CE's token_set_ratio
    # intent, done with plain sets so difflib's whole-string ratio doesn't penalise
    # the extra word). Single-token numerics never trigger this (distinct tokens).
    raw_tokens = set(s_norm.split())
    for v in valid:
        v_tokens = set(_normalise(v).split())
        if v_tokens and (v_tokens <= raw_tokens or raw_tokens <= v_tokens):
            return v
    best_score, best_match = 0.0, None
    for v in valid:
        score = _ratio(s_norm, _normalise(v))
        if score > best_score:
            best_score, best_match = score, v
    return best_match if best_score >= threshold else None


def snap_offer(
    offer_raw: dict[str, object],
    issue_names: list[str],
    options_per_issue: dict[str, list[str]],
) -> dict[str, str] | None:
    """Snap *offer_raw* onto the canonical ``{issue: option}`` map.

    Resolves each canonical issue's key (the LLM may have named it loosely) and
    then its value against that issue's options. Returns the fully-snapped offer,
    or ``None`` if *any* issue's key or value can't be resolved — an all-or-
    nothing outcome so ``to_outcome`` never returns a partial tuple.
    """
    if not isinstance(offer_raw, dict):
        return None
    # Case-fold the incoming keys once so issue-key snapping can look them up.
    raw_keys = list(offer_raw.keys())
    snapped: dict[str, str] = {}
    for name in issue_names:
        key = name if name in offer_raw else snap(name, raw_keys)
        if key is None or key not in offer_raw:
            return None
        value = snap(str(offer_raw[key]), options_per_issue.get(name, []))
        if value is None:
            return None
        snapped[name] = value
    return snapped
