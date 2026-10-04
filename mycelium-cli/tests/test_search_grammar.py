# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The CLI's copy of the message search grammar, held to the frozen contract.

The hub owns the grammar (``fastapi-backend/app/services/message_search.py``);
this copy builds queries from flags and checks the queries written in prose.
``contracts/message-search.json`` is the one source both sides assert against.
"""

import json
from pathlib import Path

import pytest
import typer

from mycelium import search_grammar
from mycelium.message_search import build_query

_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "message-search.json").read_text()
)


def test_the_copy_matches_the_frozen_contract() -> None:
    assert list(search_grammar.FIELDS) == _CONTRACT["fields"]
    assert _CONTRACT["aliases"] == search_grammar.ALIASES
    assert _CONTRACT["at_field"] == search_grammar.AT_FIELD
    assert _CONTRACT["time_keys"] == search_grammar.TIME_KEYS
    assert list(search_grammar.SORTS) == _CONTRACT["sorts"]
    assert {k: list(v) for k, v in search_grammar.CLOSED_VALUES.items()} == _CONTRACT[
        "closed_values"
    ]


def test_flags_become_clauses_after_the_words() -> None:
    query = build_query(
        ["apple", "pay"],
        {"from": ["avery"], "task": ["Add Apple Pay"], "after": ["2d"], "in": []},
    )
    assert query == 'apple pay from:avery task:"Add Apple Pay" after:2d'


@pytest.mark.parametrize(
    "flags",
    [{"has": ["links"]}, {"stance": ["maybe"]}, {"after": ["lunchtime"]}],
)
def test_a_flag_value_the_hub_would_not_read_is_refused_before_sending(flags) -> None:
    with pytest.raises(typer.BadParameter):
        build_query([], flags)


def test_problems_name_each_misreading() -> None:
    assert search_grammar.problems('from:avery "a b" https://x.test on:2026-09-03') == []
    assert search_grammar.problems("frm:avery is:new") == [
        "frm:avery: no field 'frm' (fields: " + ", ".join(search_grammar.FIELDS) + ")",
        "is:new: is is one of edited, conductor",
    ]
