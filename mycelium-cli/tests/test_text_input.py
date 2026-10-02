# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Text a command takes, given one of three ways: the argument, --body, --file.

An agent writes a long message the way it writes a PR body, so every command
that takes text takes it the same way, and a multi-line markdown body arrives
exactly as written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from mycelium.text_input import takes_text

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
BODY = "Two options:\n\n- ship today, refunds manual\n- wait a day for automatic ones\n"


def _app() -> tuple[typer.Typer, list[dict]]:
    app = typer.Typer()
    seen: list[dict] = []

    @app.command()
    @takes_text("content", "What to say.", noun="message")
    def send(
        thread: str = typer.Argument(..., help="Where"),
        content: str = typer.Argument(..., help="What"),
        room: str | None = typer.Option(None, "--room", "-r"),
    ) -> None:
        seen.append({"thread": thread, "content": content, "room": room})

    return app, seen


@pytest.mark.parametrize(
    "args",
    [
        ["t3", BODY],
        ["t3", "--body", BODY],
        ["t3", "-b", BODY, "--room", "r"],
    ],
)
def test_the_text_arrives_as_written_whichever_way_it_came(args: list[str]) -> None:
    app, seen = _app()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert seen[0]["content"] == BODY
    assert seen[0]["thread"] == "t3"


def test_a_file_or_stdin_carries_it_too(tmp_path: Path) -> None:
    app, seen = _app()
    reply = tmp_path / "reply.md"
    reply.write_text(BODY, encoding="utf-8")
    assert runner.invoke(app, ["t3", "--file", str(reply)]).exit_code == 0
    assert runner.invoke(app, ["t3", "-f", "-"], input=BODY).exit_code == 0
    assert [s["content"] for s in seen] == [BODY, BODY]


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["t3"], "no message"),
        (["t3", "hi", "--body", "there"], "once"),
        (["t3", "--file", "/nonexistent/reply.md"], "cannot read"),
    ],
)
def test_none_two_or_an_unreadable_file_is_a_usage_mistake(args: list[str], said: str) -> None:
    app, seen = _app()
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert said in result.output
    assert seen == []


def test_help_names_all_three() -> None:
    app, _ = _app()
    out = runner.invoke(app, ["--help"], env={"NO_COLOR": "1", "COLUMNS": "200"}).output
    assert "--body" in out
    assert "--file" in out


def test_a_command_that_already_has_the_flags_is_refused_at_import() -> None:
    with pytest.raises(TypeError, match="already uses"):

        @takes_text("content", "What.")
        def clash(
            content: str = typer.Argument(...),
            file: str | None = typer.Option(None, "--file"),
        ) -> None: ...

    with pytest.raises(TypeError, match="no parameter"):

        @takes_text("text", "What.")
        def missing(content: str = typer.Argument(...)) -> None: ...


def test_every_command_that_takes_text_takes_it_the_same_way() -> None:
    from mycelium.cli import app

    names = {
        ("respond",),
        ("room", "send"),
        ("room", "amend"),
        ("board", "send"),
        ("agent", "invoke"),
        ("memory", "set"),
        ("skill", "set"),
    }
    for path in names:
        out = runner.invoke(app, [*path, "--help"], env={"NO_COLOR": "1", "COLUMNS": "200"}).output
        assert "--body" in out, path
        assert "--file" in out, path
