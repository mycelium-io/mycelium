# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The whole CLI against the shared shapes (``mycelium.cli_audit``).

A new command that spells ``--room`` without ``-r``, requires ``--as``, reads
something without ``--json``, or takes text without ``--body``/``--file``
fails here, with the line ``python -m mycelium.cli_audit`` would print.
"""

from __future__ import annotations

from mycelium.cli_audit import Command, commands, findings, table


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


def test_the_table_lists_every_command() -> None:
    cmds = commands()
    out = table(cmds)
    assert len(out.splitlines()) == len(cmds) + 1
