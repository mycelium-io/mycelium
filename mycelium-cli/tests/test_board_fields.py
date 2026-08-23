# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Field writes: the board's verbs, and where each one is allowed to land.

The property under test is that a verb never reports a change the room was not
told about. A CLI that printed what it *would* write was honest about it; a CLI
that printed a write it did not make would not be.
"""

import json
from pathlib import Path

import pytest

from mycelium.board import fields as board_fields
from mycelium.board.custody import COMPANION_FIELDS, FIELD
from mycelium.board.model import ItemSource, LiveItem

VOCAB = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "board-vocabulary.json").read_text()
)
CONTRACT = VOCAB["fields"]


def row(kind: str, label: str = "work/auth-spike", **fields) -> LiveItem:
    return LiveItem(
        id=f"{kind}:{label}",
        title=label,
        source=ItemSource(kind, label),
        fields=fields,
    )


class TestContract:
    """The GUI carries its own copy of every constant here."""

    def test_refusals_match_the_contract_word_for_word(self):
        assert CONTRACT["refusals"] == board_fields.REFUSALS

    def test_writable_kinds_match_the_contract(self):
        assert CONTRACT["writable_source_kinds"] == board_fields.WRITABLE_SOURCE_KINDS

    def test_reserved_is_derived_from_custody_not_restated(self):
        # The contract deliberately carries no second copy: a lease owns these,
        # so they are read out of the custody block.
        assert [FIELD, "owner", *COMPANION_FIELDS] == board_fields.RESERVED_FIELDS
        assert [
            VOCAB["custody"]["field"],
            "owner",
            *VOCAB["custody"]["companion_fields"],
        ] == board_fields.RESERVED_FIELDS


class TestWhereAWriteMayLand:
    def test_a_memory_row_takes_a_write(self):
        item = row("memory")
        assert board_fields.refusal_for(item) is None
        assert board_fields.memory_key_of(item) == "work/auth-spike"

    def test_it_writes_outside_the_leasable_namespaces(self):
        # Custody is restricted to work/; a status change is not. A decision
        # nobody can move is the overlay problem with extra steps.
        item = row("memory", "decisions/ttl")
        assert board_fields.refusal_for(item) is None
        assert board_fields.memory_key_of(item) == "decisions/ttl"

    @pytest.mark.parametrize("kind", ["plan", "episode", "agent", "capture", "github"])
    def test_every_other_kind_is_refused_in_its_own_terms(self, kind: str):
        item = row(kind, "x")
        assert board_fields.refusal_for(item) == board_fields.REFUSALS[kind]
        assert board_fields.memory_key_of(item) is None

    def test_an_unknown_kind_is_refused_rather_than_written_somewhere(self):
        # A new source kind added without a refusal must not fall through.
        assert board_fields.refusal_for(row("wormhole", "x")) is not None
        assert board_fields.memory_key_of(row("wormhole", "x")) is None


class TestWhatALeaseOwns:
    @pytest.mark.parametrize("name", board_fields.RESERVED_FIELDS)
    def test_each_reserved_key_is_reported(self, name: str):
        assert board_fields.reserved_in([name]) == [name]

    def test_an_ordinary_field_passes(self):
        assert board_fields.reserved_in(["status", "priority", "blocked_by", "assignee"]) == []

    def test_every_clash_is_named_not_just_the_first(self):
        assert board_fields.reserved_in(["status", "owner", FIELD]) == sorted([FIELD, "owner"])
