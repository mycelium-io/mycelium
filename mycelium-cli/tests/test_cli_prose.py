# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Commands written in the docs, skills and prompts, against the CLI itself.

What an agent is shown is what it types, so a command written anywhere it can
read (the skill, a wake prompt, a doc) must be one the CLI takes. The repo is
scanned whole; the rest checks how a command is found and read in each kind of
text.
"""

from __future__ import annotations

import pytest

from mycelium.cli_prose import Node, check, from_markdown, from_python, repo_root, scan

CLI = Node(
    "mycelium",
    {
        "board": Node(
            "board",
            {
                "send": Node(
                    "send", {}, {"--room": True, "-r": True, "--body": True, "--help": False}
                )
            },
            {"--help": False},
        ),
        "docs": Node("docs", {"ls": Node("ls", {}, {})}, {"--json": False}, takes_words=True),
    },
    {"--json": False, "--help": False},
)


def test_the_repository_writes_only_commands_the_cli_takes() -> None:
    found = scan(repo_root())
    assert found == [], "\n".join(str(f) for f in found)


@pytest.mark.parametrize(
    ("command", "problem"),
    [
        ("mycelium board send t3 --room r --body hi", None),
        ('mycelium board send <id> -r {room} --body "..."', None),
        ("mycelium board send t3 --to bob", "mycelium board send takes no --to"),
        ("mycelium board shout t3", "mycelium board has no command 'shout'"),
        ("mycelium plan tasks", "mycelium has no command 'plan'"),
        ("mycelium docs rooms", None),  # docs takes a topic of its own
        ('mycelium board send t3 --body "--all of it"', None),  # quoted text is text
        ("mycelium --json board send t3", None),
    ],
)
def test_a_command_is_read_against_the_tree(command: str, problem: str | None) -> None:
    assert check(command, CLI, code=True) == problem


def test_loose_prose_that_mentions_mycelium_is_not_a_command() -> None:
    assert check("mycelium board, and sync it", CLI, code=False) is None
    assert check("mycelium is where the room lives", CLI, code=False) is None
    # A flag on a command it does recognise is still checked.
    assert check("mycelium board send t3 --to bob", CLI, code=False) is not None


def test_markdown_reads_code_and_not_prose() -> None:
    text = "\n".join(
        [
            "Run `mycelium board send t3 --body hi` in the thread.",
            "The mycelium board is where work lives.",
            "```bash",
            'echo "mycelium skill present"',
            "mycelium board send t3 -r r  # posts it",
            "mycelium board send t3 2>&1 | grep -A 2 x",
            "X=1 mycelium docs ls",
            "```",
        ]
    )
    found = [c for _, c, _ in from_markdown(text)]
    assert found == [
        "mycelium board send t3 --body hi",
        "mycelium board send t3 -r r",
        "mycelium board send t3",
        "mycelium docs ls",
    ]


def test_python_reads_strings_and_f_strings_but_not_docstrings() -> None:
    source = '''
"""Module notes: `mycelium plan tasks` was the old way."""

def f(room):
    """Run `mycelium plan tasks` here."""
    return (
        f"Reply:  mycelium board send t3 --room {room} --body \\"...\\""
        f" then `mycelium docs ls`. [/dim]"
    )
'''
    found = [(c, code) for _, c, code in from_python(source)]
    assert ("mycelium docs ls", True) in found
    assert any(c.startswith("mycelium board send t3 --room <value>") for c, _ in found)
    assert not any("plan" in c for c, _ in found)
