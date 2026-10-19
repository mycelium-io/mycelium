# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The whole CLI against the shared shapes (``mycelium.cli_audit``).

A new command that spells ``--room`` without ``-r``, requires ``--as``, reads
something without ``--json``, or takes text without ``--body``/``--file``
fails here, with the line ``python -m mycelium.cli_audit`` would print.
"""

from __future__ import annotations

from typing import Any

from mycelium.cli_audit import Command, _asks_who_acts, commands, findings, table


def test_every_command_takes_the_shared_flags_the_same_way() -> None:
    assert findings() == []


def test_the_audit_catches_each_kind_of_drift() -> None:
    drifted = [
        Command("x get", {"room": {"--room"}}),
        Command("x send", {"handle": {"--as", "--handle", "-H"}}, required={"handle"}),
        Command("x log", {"limit": {"--limit", "-n"}, "json": {"--json"}}),
        Command("respond", {}),
    ]
    found = findings(drifted)
    assert any("x get: --room should be spelled" in f for f in found)
    assert any("x get: reads something" in f for f in found)
    assert any("x send: --as should not be required" in f for f in found)
    assert any("x log: --limit should be spelled" in f for f in found)
    assert any("respond: takes text" in f for f in found)


def test_a_command_that_writes_as_someone_must_take_as() -> None:
    found = findings(
        [
            Command("x new", {"room": {"--room", "-r"}}, acts=True),
            Command("x ls", {"json": {"--json"}}, acts=True),
            Command("x send", {"handle": {"--as", "--handle", "-H"}}, acts=True),
        ]
    )
    assert "x new: writes as someone, so it should take --as" in found
    assert not any(f.startswith(("x ls:", "x send:")) for f in found)


def _files_as(cfg: Any) -> dict[str, str]:
    return {"handle": cfg.get_current_identity()}


def test_the_audit_sees_a_command_ask_who_acts_through_its_helpers() -> None:
    def files_directly(cfg: Any) -> str:
        return cfg.get_current_identity()

    def files_through_a_helper(cfg: Any) -> dict[str, str]:
        return _files_as(cfg)

    def files_as_given(handle: str) -> dict[str, str]:
        return {"handle": handle}

    assert _asks_who_acts(files_directly)
    assert _asks_who_acts(files_through_a_helper)
    assert not _asks_who_acts(files_as_given)
    assert not {c.path: c for c in commands()}["docs ls"].acts


def test_the_table_lists_every_command() -> None:
    cmds = commands()
    out = table(cmds)
    assert len(out.splitlines()) == len(cmds) + 1
