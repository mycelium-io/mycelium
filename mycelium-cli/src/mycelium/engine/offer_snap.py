# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Fuzzy snapping of interpreted SAO offers onto the canonical issue/option set.

The mediator's ``interpret`` stage asks an LLM to map an agent's prose into an
offer ``{issue: option}``. LLMs routinely return keys/values that are *almost*
the canonical ones registered at issue-discovery time: ``"Tech"`` for
``tech_allocation``, ``"30%"`` for ``"30"``, ``"express delivery"`` for
``"express"``. Left alone, ``to_outcome`` rejects the whole offer (a value not
exactly in the option list), which downgrades a real move to a reject and (over
a live negotiation) cascades into timeouts and misreported agreements.

This snaps such near-misses to the nearest canonical value before rejecting,
mirroring the good part of the sibling `ioc-scale-cf-cognition-engines`
`offer_validation.py` (their 5-tier rapidfuzz/embedding version). We keep it
**stdlib-only** (`difflib`) deliberately: option lists here are tiny (a handful
per issue) and snapping runs once per agent turn, so a heavy fuzzy dep buys
nothing. Order: exact → case-insensitive → normalised → `difflib` ratio.

**What snapping does NOT fix:** a value that has no near-match in the set at all
(the agents agreed 30% but the discovered grid only has {25, 35}). That is an
issue-*discovery* problem (the grid must contain the meeting point), not a
snapping one. `difflib` correctly refuses to snap "30"→"25" (ratio ≈ 50, below
threshold), so this never fabricates a numeric value; it only rescues genuine
surface-form near-misses.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

#: Minimum `difflib` similarity (0-100) for a fuzzy (non-exact) snap. 80 rescues
#: typos / formatting / word-order noise while refusing to collapse genuinely
#: distinct options (e.g. two different numbers).
_SNAP_THRESHOLD = 80.0


def _normalise(text: str) -> str:
    """Lowercase; collapse whitespace, underscores, hyphens to a single space."""
    return re.sub(r"[\s_\-]+", " ", str(text).strip().lower())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100.0


def snap(raw: str, valid: list[str], *, threshold: float = _SNAP_THRESHOLD) -> str | None:
    """Return the canonical member of *valid* matching *raw*, or ``None``.

    Tiers, first match wins: exact, case-insensitive, normalised, then a
    ``difflib`` ratio at/above *threshold* (best match). ``None`` means *raw* is
    too far from every option to snap; the caller should treat that as a real
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
    # Token containment: "express delivery" ~ "express" (the CE's token_set_ratio
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
    or ``None`` if *any* issue's key or value can't be resolved; an all-or-
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
