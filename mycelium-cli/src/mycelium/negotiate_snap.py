# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Fuzzy issue/option snap for CLI-side negotiation pre-flight.

Mirrors the validation logic that ships in CFN engines (Akanksha's
``offer_validation.py`` in ``outshift-open/ioc-cfn-cognition-engines``).
Engines runs the same five-tier snap server-side on the counter_offer and
sends an ``offer_validation_failure`` payload back in the *next* broadcast
when it can't match — a 20-30s round-trip the agent has to wait through.

This module runs tiers 1-4 of that same snap client-side at
``mycelium negotiate propose`` time, so the agent sees the correction (or
the failure with did-you-mean hints) instantly and can re-issue in the same
turn. Tier 5 (Granite-30M embedding fallback) is intentionally skipped here
— the engine still has it as a server-side backstop, and pulling an ONNX
runtime into a CLI is not worth ~50MB on disk + cold-start latency.

Stay aligned with engines: keep the public surface (``snap_issue``,
``snap_option``) and default thresholds (80/80) identical so future tweaks
upstream can port mechanically.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz as _fuzz

_NORMALISE_RE = re.compile(r"[\s_\-]+")


def _normalise(text: str) -> str:
    """Lowercase, strip, and collapse whitespace/underscores/hyphens to a single space."""
    return _NORMALISE_RE.sub(" ", str(text).strip().lower())


def snap_issue(
    raw_key: str,
    valid_issues: list[str],
    threshold: float = 80.0,
) -> str | None:
    """Return the best-matching valid issue for *raw_key*, or ``None``.

    Tiers (first match wins):
      1. Exact match.
      2. Case-insensitive exact match.
      3. Normalised match (strip, lower, collapse whitespace/_/-).
      4. ``rapidfuzz.fuzz.token_set_ratio`` ≥ *threshold*. Token-set handles
         word-order and partial containment — appropriate for multi-word
         issue identifiers ("price tier" vs "tier price").
    """
    if raw_key in valid_issues:
        return raw_key
    raw_lower = raw_key.lower()
    for v in valid_issues:
        if raw_lower == v.lower():
            return v
    raw_norm = _normalise(raw_key)
    for v in valid_issues:
        if raw_norm == _normalise(v):
            return v
    best_score, best_match = 0.0, None
    for v in valid_issues:
        score = _fuzz.token_set_ratio(raw_key, v)
        if score > best_score:
            best_score, best_match = score, v
    return best_match if best_score >= threshold else None


def snap_option(
    raw_value: str,
    valid_options: list[str],
    threshold: float = 80.0,
) -> str | None:
    """Return the best-matching valid option for *raw_value*, or ``None``.

    Same tiers as ``snap_issue`` but tier 4 uses ``fuzz.ratio`` (character-
    level Levenshtein) instead of ``token_set_ratio``. Option values tend
    to be short single tokens where typo distance matters more than word
    order; matches the engine-side asymmetry intentionally.
    """
    if raw_value in valid_options:
        return raw_value
    raw_lower = raw_value.lower()
    for v in valid_options:
        if raw_lower == v.lower():
            return v
    raw_norm = _normalise(raw_value)
    for v in valid_options:
        if raw_norm == _normalise(v):
            return v
    best_score, best_match = 0.0, None
    for v in valid_options:
        score = _fuzz.ratio(raw_value, v)
        if score > best_score:
            best_score, best_match = score, v
    return best_match if best_score >= threshold else None
