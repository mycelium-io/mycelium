# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for ``@``-mentions (backend side).

The frontend parses message text for mentions too (``lib/mentions.ts``) and
can't import this backend, so both assert the cases in
``contracts/mentions.json``. A silent ``@~handle`` the UI drew as a mention, or
one the hub woke someone for, is the drift this catches.
"""

import json
from pathlib import Path

import pytest

from app.services.persister import find_summons, parse_mentions, parse_silent_mentions

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "mentions.json"
_CONTRACT = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_sigils_match_contract():
    assert _CONTRACT["sigils"] == {"mention": "@", "silent": "@~"}


@pytest.mark.parametrize("case", _CONTRACT["cases"], ids=lambda c: c["text"])
def test_case_parses_as_the_contract_says(case):
    assert parse_mentions(case["text"]) == case["mentions"]
    assert parse_silent_mentions(case["text"]) == case["silent"]


@pytest.mark.parametrize("case", _CONTRACT["cases"], ids=lambda c: c["text"])
def test_only_a_loud_mention_summons(case):
    assert find_summons({"content": case["text"]}) == case["mentions"]
