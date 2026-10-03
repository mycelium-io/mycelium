# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every command we tell an agent to run with ``--room`` accepts ``--room``.

Agents run the commands in their prompts and in the skill verbatim, so a
flag a command doesn't take is a turn wasted on an error (``room messages
--room hay`` was refused while its prompt said to run exactly that). This
reads the commands out of the text agents are given and asks each one's own
help whether it takes ``--room``, so a new prompt can't drift from the CLI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands.room import _one_room

SRC = Path(__file__).resolve().parents[1] / "src" / "mycelium"
#: What agents are told to run: their wake-up prompts, their briefs, the skill.
AGENT_TEXT = [
    SRC / "integrations" / "herdr" / "bridge.py",
    SRC / "runner" / "daemon.py",
    SRC / "commands" / "swarm.py",
    SRC / "skills" / "mycelium" / "SKILL.md",
    # The digest a woken agent is told is built on the hub, in the same checkout.
    SRC.parents[2] / "fastapi-backend" / "app" / "services" / "wake_digest.py",
]
COMMAND = re.compile(r"mycelium ((?:[a-z][a-z-]* ){1,2})[^`\"'\n]*?--room\b")

runner = CliRunner()


#: Rich colors help on CI, and its escape codes split "--room" apart.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _help(words: list[str]) -> str | None:
    result = runner.invoke(app, [*words, "--help"])
    return ANSI.sub("", result.output) if result.exit_code == 0 else None


def told_to_run_with_room() -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for path in AGENT_TEXT:
        for match in COMMAND.finditer(path.read_text()):
            words = match.group(1).split()
            # "board claim <id> --room" names a subcommand; "await --room" doesn't.
            if len(words) == 2 and _help(words) is None:
                words = words[:1]
            found.add(tuple(words))
    return found


def test_the_agent_text_names_commands_to_check():
    found = told_to_run_with_room()
    assert ("await",) in found
    assert ("board", "claim") in found


@pytest.mark.parametrize("words", sorted(told_to_run_with_room()), ids=" ".join)
def test_each_command_an_agent_is_told_to_run_takes_room(words: tuple[str, ...]):
    help_text = _help(list(words))
    assert help_text is not None, f"mycelium {' '.join(words)} isn't a command"
    assert "--room" in help_text, f"mycelium {' '.join(words)} doesn't take --room"


def test_a_room_can_be_given_either_way_but_not_as_two():
    assert _one_room("hay", None) == "hay"
    assert _one_room(None, "hay") == "hay"
    assert _one_room("hay", "hay") == "hay"
    assert _one_room(None, None) is None
    with pytest.raises(typer.BadParameter, match="two rooms"):
        _one_room("hay", "straw")
