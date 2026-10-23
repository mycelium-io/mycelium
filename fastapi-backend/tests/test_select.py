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
    # With no reference ratings, a rating is placed on its raw 0-100 scale.
    assert record["lowest"] == 0.72


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


def test_a_pick_missing_a_rating_is_not_agreed_and_goes_on_to_a_repair():
    """No agreement over silence: the pick goes to the member who rates it
    lowest for a repair, until the repairs allowed are used up."""
    options = _options("one option")
    ratings = {"success": {"A": 90}, "finance": {"A": 80}}
    record = choosing.pick(options, CAST, ratings, 0.7)
    assert record["outcome"] == "infeasible"
    assert record["least_happy"] == "finance"
    assert record["missing"] == ["legal"]
    record = choosing.pick(options, CAST, ratings, 0.7, repairs_done=2, max_repairs=2)
    assert record["outcome"] == "stuck"
    assert record["least_happy"] is None


def test_a_rating_still_missing_after_its_retry_blocks_agreement_anywhere():
    """Everyone rated the pick at the bar, but a rating of another option is
    missing: CONCORD agrees nothing while any is."""
    options = _options("first", "second")
    ratings = {h: {"A": 90} for h in CAST} | {"success": {"A": 90, "B": 50}}
    record = choosing.pick(options, CAST, ratings, 0.7, unrated={"legal": {"B"}})
    assert record["pick"] == "A"
    assert record["outcome"] == "infeasible"
    assert record["unrated"] == {"legal": ["B"]}


def test_the_pick_is_made_among_the_options_everyone_rated_at_the_bar():
    """A is the better leximin, but finance never rated it; B everyone rated
    at the bar, so B is the pick."""
    options = _options("A text", "B text")
    ratings = {
        "success": {"A": 95, "B": 75},
        "finance": {"B": 72},
        "legal": {"A": 90, "B": 71},
    }
    record = choosing.pick(options, CAST, ratings, 0.7)
    assert record["feasible"] == ["B"]
    assert (record["pick"], record["outcome"]) == ("B", "feasible")


def test_a_new_best_replaces_the_incumbent_only_when_better_by_eps():
    options = _options("held", "a little better", "much better")
    ratings = {
        "success": {"A": 50, "B": 52, "C": 65},
        "finance": {"A": 80, "B": 80, "C": 80},
        "legal": {"A": 80, "B": 80, "C": 80},
    }
    without_c = {h: {k: v for k, v in r.items() if k != "C"} for h, r in ratings.items()}
    held = choosing.pick(options[:2], CAST, without_c, 0.7, incumbent="A", eps=0.05)
    # B's lowest is 0.02 higher, under eps: A stays.
    assert (held["selected"], held["pick"], held["accepted"]) == ("B", "A", False)
    record = choosing.pick(options, CAST, ratings, 0.7, incumbent="A", eps=0.05)
    assert (record["selected"], record["pick"], record["accepted"]) == ("C", "C", True)


def test_after_the_fixes_allowed_the_next_short_pick_is_stuck():
    options = _options("one option")
    ratings = {"success": {"A": 90}, "finance": {"A": 30}, "legal": {"A": 90}}
    assert (
        choosing.pick(options, CAST, ratings, 0.7, repairs_done=1, max_repairs=2)["outcome"]
        == "infeasible"
    )
    assert (
        choosing.pick(options, CAST, ratings, 0.7, repairs_done=2, max_repairs=2)["outcome"]
        == "stuck"
    )


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


def test_ratings_are_placed_between_each_members_own_reference_outcomes():
    """Legal rates everything high and finance low; placed between their own
    bad and ideal ratings, legal's 80 and finance's 40 both sit halfway."""
    anchors = {"success": (0, 100), "finance": (20, 60), "legal": (60, 100)}
    assert choosing.placed(40, anchors["finance"]) == 0.5
    assert choosing.placed(80, anchors["legal"]) == 0.5
    # Outside a member's own range says no more than that end does.
    assert choosing.placed(10, anchors["finance"]) == 0.0
    assert choosing.placed(99, anchors["finance"]) == 1.0
    options = _options("one option")
    ratings = {"success": {"A": 50}, "finance": {"A": 40}, "legal": {"A": 80}}
    record = choosing.pick(options, CAST, ratings, 0.5, anchors=anchors)
    assert record["standing"] == {"success": 0.5, "finance": 0.5, "legal": 0.5}
    assert record["outcome"] == "feasible"
    # Raw, legal's 80 would have hidden that it's only halfway to its ideal.
    assert choosing.pick(options, CAST, ratings, 0.6, anchors=anchors)["outcome"] == "infeasible"


def test_a_rating_is_said_in_words_against_the_bar():
    assert choosing.verdict(None, 0.6) == "gave no rating"
    assert choosing.verdict(0.0, 0.6) == "no better than the bad outcome"
    assert choosing.verdict(0.3, 0.6) == "short of the bar"
    assert choosing.verdict(0.6, 0.6) == "meets the bar"
    assert choosing.verdict(0.95, 0.6) == "close to the ideal"


def test_an_option_is_named_by_its_first_words_so_a_letter_can_be_followed():
    assert choosing.named("B", "10% off") == "B (10% off)"
    assert choosing.short_name("Ship at once, and cancel the delivery if the payment fails.") == (
        "Ship at once, and cancel…"
    )
    # Cut at the end of the first sentence, and brackets dropped.
    assert choosing.short_name("Hold it. Then ship (maybe).") == "Hold it…"
    assert (
        choosing.short_name("Three-year renewal at list price")
        == "Three-year renewal at list price"
    )


def test_options_that_start_alike_are_named_by_what_tells_them_apart():
    names = choosing.option_names(
        [
            ("A", "Three-year renewal at 15% off list price, with an expansion review."),
            ("B", "Three-year renewal at list price, with a dedicated success manager."),
            ("C", "Three-year renewal at list price with standard liability caps."),
            ("D", "10% off"),
        ]
    )
    assert names == {
        "A": "Three-year renewal at 15% off…",
        "B": "…a dedicated success manager",
        "C": "…standard liability caps",
        "D": "10% off",
    }
    assert len(set(names.values())) == 4


def test_a_reason_reads_mid_sentence_without_mangling_i_or_acronyms():
    assert choosing.mid_sentence("Too slow") == "too slow"
    assert (
        choosing.mid_sentence("I can't refund big orders blind")
        == "I can't refund big orders blind"
    )
    assert choosing.mid_sentence("I'd sign off") == "I'd sign off"
    assert choosing.mid_sentence("SLA is too loose") == "SLA is too loose"
    assert choosing.mid_sentence("iOS breaks") == "iOS breaks"


def test_who_is_short_is_said_with_their_reason():
    options = _options("Ship on Friday")
    ratings = {"success": {"A": 90}, "finance": {"A": 70}, "legal": {"A": 20}}
    reasons = {"legal": {"A": "The Friday window breaks certification"}}
    record = choosing.pick(options, CAST, ratings, 0.6, reasons=reasons)
    assert record["short"] == [
        {"member": "legal", "placed": 0.2, "why": "The Friday window breaks certification"}
    ]
    assert choosing.summary(record) == (
        "legal is short of the bar, because the Friday window breaks certification."
    )


def test_the_scorecard_leads_with_reasons_and_puts_the_numbers_last():
    options = _options("A text", "B text")
    ratings = {"success": {"A": 90, "B": 40}, "finance": {"A": 50}}
    reasons = {"success": {"A": "Fits the plan", "B": "Too slow"}, "finance": {"A": "Over budget"}}
    card = choosing.scorecard(choosing.pick(options, CAST, ratings, 0.7, reasons=reasons))
    assert card.startswith(
        "**A** (best so far): A text\n- success: close to the ideal, because fits the plan"
    )
    assert "- finance: short of the bar, because over budget" in card
    assert "- legal: gave no rating" in card
    assert (
        "Where A (A text) stands: finance is short of the bar, because over budget; "
        "no rating from legal." in card
    )
    # The numbers come last, behind what they mean.
    assert card.index("The numbers, for anyone checking") > card.index("Where A (A text) stands")
    assert "| A | 90 (90%) | 50 (50%) | ? |" in card
    assert "| B | 40 (40%) | ? | ? |" in card
    # Posted into the thread, so it names members without summoning them.
    assert "@" not in card
