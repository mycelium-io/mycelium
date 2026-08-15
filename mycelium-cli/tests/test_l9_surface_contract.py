# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the shared L9 "raise-up" whitelist (CLI side).

The frontend (mycelium-frontend/src/components/event-stream.tsx) carries its
own copy of this list so its Docker build (context: mycelium-frontend/ only)
need not reach outside its own tree. This test freezes the shared whitelist in
``contracts/l9-surface.json`` at the repo root and asserts the **CLI**
primitive reproduces it exactly. The frontend suite asserts its own copy
against the same file
(``mycelium-frontend/src/components/event-stream.contract.test.ts``). One
frozen source, two asserters — so neither copy can drift without turning a
fast unit gate red.
"""

import json
from pathlib import Path

from mycelium.commands.room import L9_RAISE_UP_TYPES

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "l9-surface.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_raise_up_types_match_contract():
    """The CLI's raise-up whitelist matches the frozen contract byte-for-byte."""
    g = _contract()
    assert frozenset(g["raise_up_types"]) == L9_RAISE_UP_TYPES
