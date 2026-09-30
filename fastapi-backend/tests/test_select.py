# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Picking the option everyone can live with: pure, so every rule is checkable by hand."""

from __future__ import annotations

from app.services import select as choosing

CAST = ["success", "finance", "legal"]


def _options(*texts: str) -> list[choosing.Option]:
    options: list[choosing.Option] = []
    for i, text in enumerate(texts):
        choosing.add_option(options, text, CAST[i % len(CAST)])
    return options


def test_the_pick_is_the_option_the_least_happy_likes_best():
    options = _options("20% off", "10% off", "15% off, two years")
    ratings = {
        "success": {"A": 95, "B": 40, "C": 80},
        "finance": {"A": 20, "B": 95, "C": 75},
        "legal": {"A": 90, "B": 90, "C": 72},
    }
    record = choosing.pick(options, CAST, ratings, 0.7)
    assert record["pick"] == "C"
    assert record["outcome"] == "feasible"
    assert record["ratings"] == {"success": 80, "finance": 75, "legal": 72}
    assert record["lowest"] == 72


def test_the_second_lowest_rating_breaks_a_tie_on_the_lowest():
    options = _options("A text", "B text")
    ratings = {
        "success": {"A": 50, "B": 50},
        "finance": {"A": 60, "B": 90},
        "legal": {"A": 99, "B": 60},
    }
    # A sorts to [50, 60, 99] and B to [50, 60, 90]: tied on the lowest two,
    # so the third decides, and A wins.
    assert choosing.pick(options, CAST, ratings, 0.7)["pick"] == "A"
    ratings["legal"]["A"] = 55
    # Now A is [50, 55, 60] and B is [50, 60, 90]: B's second-lowest wins.
    assert choosing.pick(options, CAST, ratings, 0.7)["pick"] == "B"


def test_a_final_tie_goes_to_the_earlier_letter():
    options = _options("first", "second")
    ratings = {h: {"A": 80, "B": 80} for h in CAST}
    assert choosing.pick(options, CAST, ratings, 0.7)["pick"] == "A"


def test_a_missing_rating_counts_as_zero_for_ranking_but_shows_as_missing():
    options = _options("loved by one", "fine for all")
    ratings = {
        "success": {"A": 100, "B": 70},
        "finance": {"B": 71},  # never rated A
        "legal": {"B": 72},
    }
    record = choosing.pick(options, CAST, ratings, 0.7)
    # A can't win just because the people who'd dislike it didn't answer.
    assert record["pick"] == "B"
    assert record["outcome"] == "feasible"

    ratings = {"success": {"A": 90}, "finance": {"A": 85}}
    record = choosing.pick(_options("only one"), CAST, ratings, 0.7)
    assert record["missing"] == ["legal"]
    assert "legal" not in record["ratings"], "missing is never recorded as 0"


def test_the_fixer_is_the_lowest_rater_of_the_pick_among_those_who_rated():
    options = _options("one option")
    ratings = {"success": {"A": 60}, "finance": {"A": 40}, "legal": {"A": 40}}
    record = choosing.pick(options, CAST, ratings, 0.7)
    assert record["outcome"] == "infeasible"
    # A tie on the lowest goes to the earlier member of the cast.
    assert record["least_happy"] == "finance"


def test_a_pick_failing_only_on_missing_ratings_is_stuck():
    options = _options("one option")
    ratings = {"success": {"A": 90}, "finance": {"A": 80}}
    record = choosing.pick(options, CAST, ratings, 0.7)
    assert record["outcome"] == "stuck"
    assert record["least_happy"] is None
    assert record["missing"] == ["legal"]


def test_after_the_fixes_allowed_the_next_short_pick_is_stuck():
    options = _options("one option")
    ratings = {"success": {"A": 90}, "finance": {"A": 30}, "legal": {"A": 90}}
    assert choosing.pick(options, CAST, ratings, 0.7, repairs_done=1)["outcome"] == "infeasible"
    assert choosing.pick(options, CAST, ratings, 0.7, repairs_done=2)["outcome"] == "stuck"


def test_a_duplicate_suggestion_folds_into_the_earlier_with_both_authors():
    options: list[choosing.Option] = []
    choosing.add_option(options, "Offer 10% off", "finance")
    same = choosing.add_option(options, "  offer 10%   OFF ", "legal")
    assert len(options) == 1
    assert same is options[0]
    assert options[0].authors == ["finance", "legal"]


def test_there_are_at_most_twenty_six_options():
    options: list[choosing.Option] = []
    for i in range(30):
        choosing.add_option(options, f"option {i}", "a")
    assert len(options) == 26
    assert options[-1].label == "Z"


def test_the_scorecard_marks_missing_ratings_and_the_pick():
    options = _options("A text", "B text")
    ratings = {"success": {"A": 90, "B": 40}, "finance": {"A": 50}}
    card = choosing.scorecard(choosing.pick(options, CAST, ratings, 0.7))
    assert "| **A** ◀ | 90 | 50 | ? |" in card
    assert "| **B** | 40 | ? | ? |" in card
    assert "The bar is 70." in card
    assert "@finance at 50" in card and "no rating from @legal" in card
