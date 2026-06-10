# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for CLI-side fuzzy snap.

Mirrors the engines-side tests in
``outshift-open/ioc-cfn-cognition-engines`` so behavior stays aligned.
"""

from mycelium.negotiate_snap import snap_issue, snap_option


class TestSnapIssue:
    def test_exact_match(self):
        assert snap_issue("price", ["price", "delivery"]) == "price"

    def test_case_insensitive(self):
        assert snap_issue("Price", ["price"]) == "price"
        assert snap_issue("PRICE", ["price"]) == "price"

    def test_normalised_whitespace_underscore_hyphen(self):
        assert snap_issue("price_tier", ["price tier"]) == "price tier"
        assert snap_issue("price-tier", ["price tier"]) == "price tier"
        assert snap_issue("  Price  Tier ", ["price_tier"]) == "price_tier"

    def test_token_set_ratio(self):
        # token_set_ratio handles word-order
        assert snap_issue("tier price", ["price tier"]) == "price tier"

    def test_no_match_below_threshold(self):
        # 'name' vs 'Bloom' shares no tokens; should not match
        assert snap_issue("name", ["Bloom", "sprout"]) is None

    def test_threshold_override(self):
        # Force a weak match through by lowering threshold
        assert snap_issue("nme", ["name"], threshold=50.0) == "name"

    def test_empty_valid_list(self):
        assert snap_issue("anything", []) is None


class TestSnapOption:
    def test_exact_match(self):
        assert snap_option("high", ["low", "medium", "high"]) == "high"

    def test_case_insensitive(self):
        assert snap_option("HIGH", ["high"]) == "high"

    def test_normalised(self):
        assert snap_option("express_delivery", ["express delivery"]) == "express delivery"

    def test_typo_via_ratio(self):
        # fuzz.ratio (char-level) catches single-char typos at threshold=80
        assert snap_option("mediun", ["low", "medium", "high"]) == "medium"

    def test_no_match(self):
        assert snap_option("expensive", ["low", "high"]) is None

    def test_empty_valid_list(self):
        assert snap_option("anything", []) is None
