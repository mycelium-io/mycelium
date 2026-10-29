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

from app.services.persister import (
    blank_code,
    parse_interrupt_mentions,
    parse_mentions,
    parse_silent_mentions,
)

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "mentions.json"
_CONTRACT = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_sigils_match_contract():
    assert _CONTRACT["sigils"] == {"mention": "@", "silent": "@~", "interrupt": "@!"}


def test_group_names_match_contract():
    from app.services import groups
    from app.services.persister import _GROUP_NAMES

    assert list(groups.GROUPS) == _CONTRACT["group_names"]
    assert set(_CONTRACT["group_names"]) == _GROUP_NAMES


@pytest.mark.parametrize("case", _CONTRACT["cases"], ids=lambda c: c["text"])
def test_case_parses_as_the_contract_says(case):
    from app.services import groups

    assert parse_interrupt_mentions(case["text"]) == case["interrupt"]
    assert parse_mentions(case["text"]) == case["mentions"]
    assert parse_silent_mentions(case["text"]) == case["silent"]
    assert groups.parse(case["text"]) == case.get("groups", {})


@pytest.mark.parametrize("case", _CONTRACT["cases"], ids=lambda c: c["text"])
def test_only_a_loud_mention_asks(case):
    # Who a message asks (and so summons, when it's an engine): every loud
    # mention, never a silent one (``asks.py``).
    from app.services import message_format
    from app.services.asks import asked
    from app.services.message_models import Kind
    from app.services.message_slim import serialize_content

    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=message_format.live_episode_urn("r"),
        sender="someone-else",
        topic=message_format.topic_urn("r"),
        payload_type="message",
    )
    content = serialize_content(env, extra={"content": case["text"]})
    assert list(asked(content)) == [m.lower() for m in case["mentions"]]


def test_blank_code_keeps_length_lines_and_prose():
    text = "see `@a` and\n```\n@b\n```\nthen @c"
    blanked = blank_code(text)
    assert len(blanked) == len(text)
    assert blanked.split("\n")[0].startswith("see ") and blanked.endswith("then @c")
    assert blanked.count("\n") == text.count("\n")
    assert "@a" not in blanked and "@b" not in blanked
