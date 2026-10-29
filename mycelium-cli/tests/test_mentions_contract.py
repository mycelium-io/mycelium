# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for ``@``-mentions (CLI side).

``mycelium room export`` lists each message's mentions, and the CLI can't
import the hub's parser, so it asserts the same ``contracts/mentions.json`` the
hub and the app do: an export never lists a handle the hub didn't take as a
mention (one quoted in code, say), or misses one it did.
"""

import json
from pathlib import Path

import pytest

from mycelium.room_export import mentions

_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "mentions.json").read_text()
)


def test_group_names_match_contract() -> None:
    from mycelium.room_export import _GROUPS

    assert set(_CONTRACT["group_names"]) == _GROUPS


def _handles(found: list[dict[str, str]], modes: set[str]) -> list[str]:
    return list(dict.fromkeys(m["handle"] for m in found if m["mode"] in modes))


@pytest.mark.parametrize("case", _CONTRACT["cases"], ids=lambda c: c["text"])
def test_case_exports_as_the_contract_says(case: dict) -> None:
    found = mentions(case["text"])
    assert _handles(found, {"plain", "urgent"}) == case["mentions"]
    assert _handles(found, {"silent"}) == case["silent"]
    assert _handles(found, {"urgent"}) == case["interrupt"]
