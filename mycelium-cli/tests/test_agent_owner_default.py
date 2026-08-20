# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`agent create` defaults --owner to the caller's --as handle."""

from __future__ import annotations

from mycelium.commands.agent import _default_owner


def test_explicit_owner_wins_over_as() -> None:
    assert _default_owner("bob", "julia") == "bob"


def test_owner_defaults_to_as_handle() -> None:
    assert _default_owner(None, "julia") == "julia"


def test_cli_user_sentinel_stamps_no_owner() -> None:
    # The default --as sentinel names no real principal, so nothing is owned.
    assert _default_owner(None, "cli-user") is None


def test_explicit_owner_wins_even_over_sentinel_as() -> None:
    assert _default_owner("bob", "cli-user") == "bob"
