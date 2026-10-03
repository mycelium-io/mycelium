# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The shared options: spelled one way, resolved one way, on every command.

An agent that learns ``--room``, ``--as`` or ``--json`` on one command can use
it on the next. Each decorator is checked on a small app of its own, and with
the others stacked on one command, the way ``board send`` carries them.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import TYPE_CHECKING, Any

import pytest
import typer
from typer.testing import CliRunner

from mycelium.cli_options import acts_as, confirms, emits_json, in_room, paged, rewrite
from mycelium.text_input import takes_text

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture(autouse=True)
def _offline(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No hub to ask who we are, and no room or handle in the environment."""
    monkeypatch.setattr("mycelium.identity._hub_whoami", lambda _config: None)
    for name in ("MYCELIUM_ROOM_ID", "MYCELIUM_ROOM", "MYCELIUM_AGENT_HANDLE"):
        monkeypatch.delenv(name, raising=False)


def _one(decorated: Any) -> typer.Typer:
    """An app whose one command is ``decorated``, under a group so it has a name."""
    app = typer.Typer()

    @app.callback()
    def main(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
        ctx.ensure_object(dict)["json"] = json_output

    app.command("cmd")(decorated)
    return app


def _plain(out: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", out)


# ── --room ───────────────────────────────────────────────────────────────────


def test_room_resolves_from_the_flag_then_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    @in_room()
    def cmd(room: str | None = None) -> None:
        seen.append(room or "")

    app = _one(cmd)
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "from-env")
    assert runner.invoke(app, ["cmd"]).exit_code == 0
    assert runner.invoke(app, ["cmd", "-r", "from-flag"]).exit_code == 0
    assert seen == ["from-env", "from-flag"]


def test_no_room_anywhere_is_said_once() -> None:
    @in_room()
    def cmd(room: str | None = None) -> None:
        raise AssertionError("ran without a room")

    result = runner.invoke(_one(cmd), ["cmd"])
    assert result.exit_code == 1
    assert "No room context found" in result.output


def test_a_room_filter_stays_unset() -> None:
    seen: list[Any] = []

    @in_room(resolve=False)
    def cmd(room: str | None = None) -> None:
        seen.append(room)

    assert runner.invoke(_one(cmd), ["cmd"]).exit_code == 0
    assert seen == [None]


# ── --as ─────────────────────────────────────────────────────────────────────


def test_acting_as_resolves_from_the_environment_and_is_never_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    @acts_as()
    def cmd(handle: str | None = None) -> None:
        seen.append(handle or "")

    app = _one(cmd)
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    assert runner.invoke(app, ["cmd"]).exit_code == 0
    assert runner.invoke(app, ["cmd", "-H", "reviewer"]).exit_code == 0
    assert runner.invoke(app, ["cmd", "--handle", "operator"]).exit_code == 0
    assert seen == ["builder", "reviewer", "operator"]


def test_with_no_fallback_a_missing_sender_is_a_usage_error() -> None:
    @acts_as(fallback=None)
    def cmd(handle: str | None = None) -> None:
        raise AssertionError("ran with no sender")

    result = runner.invoke(_one(cmd), ["cmd"])
    assert result.exit_code == 2
    assert "--as <handle>" in result.output


def test_with_the_default_fallback_a_placeholder_is_used() -> None:
    seen: list[str] = []

    @acts_as()
    def cmd(handle: str | None = None) -> None:
        seen.append(handle or "")

    assert runner.invoke(_one(cmd), ["cmd"]).exit_code == 0
    assert seen == ["cli-user"]


# ── --json ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("args", [["--json", "cmd"], ["cmd", "--json"]])
def test_json_works_before_or_after_the_command(args: list[str]) -> None:
    @emits_json()
    def cmd(ctx: typer.Context) -> None:
        typer.echo(json.dumps({"json": ctx.obj["json"]}))

    result = runner.invoke(_one(cmd), args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"json": True}


def test_json_fills_a_commands_own_parameter() -> None:
    seen: list[bool] = []

    @emits_json("as_json")
    def cmd(as_json: bool = False) -> None:
        seen.append(as_json)

    app = _one(cmd)
    runner.invoke(app, ["cmd"])
    runner.invoke(app, ["cmd", "--json"])
    runner.invoke(app, ["--json", "cmd"])
    assert seen == [False, True, True]


# ── --limit and --yes ────────────────────────────────────────────────────────


def test_limit_takes_every_spelling_and_keeps_the_default() -> None:
    seen: list[int] = []

    @paged()
    def cmd(limit: int = typer.Option(7)) -> None:
        seen.append(limit)

    app = _one(cmd)
    for args in (["cmd"], ["cmd", "--limit", "3"], ["cmd", "-n", "4"], ["cmd", "-l", "5"]):
        assert runner.invoke(app, args).exit_code == 0
    assert seen == [7, 3, 4, 5]


def test_yes_and_its_old_force_spelling() -> None:
    seen: list[bool] = []

    @confirms("force", also_force=True)
    def cmd(force: bool = False) -> None:
        seen.append(force)

    app = _one(cmd)
    for args in (["cmd"], ["cmd", "-y"], ["cmd", "--yes"], ["cmd", "-f"], ["cmd", "--force"]):
        runner.invoke(app, args)
    assert seen == [False, True, True, True, True]


# ── together ─────────────────────────────────────────────────────────────────


def test_they_stack_on_one_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    @takes_text("content", "What to say.")
    @in_room()
    @acts_as()
    @emits_json()
    def cmd(
        ctx: typer.Context,
        content: str = typer.Argument(...),
        room: str | None = None,
        handle: str | None = None,
    ) -> None:
        seen.append({"content": content, "room": room, "handle": handle, "json": ctx.obj["json"]})

    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    result = runner.invoke(_one(cmd), ["cmd", "-r", "checkout", "--body", "two\n\nlines", "--json"])
    assert result.exit_code == 0, result.output
    assert seen == [
        {"content": "two\n\nlines", "room": "checkout", "handle": "builder", "json": True}
    ]
    out = _plain(runner.invoke(_one(cmd), ["cmd", "--help"], env={"COLUMNS": "200"}).output)
    for flag in ("--room", "-r", "--as", "--handle", "-H", "--json", "--body", "--file"):
        assert flag in out, flag


def test_a_flag_the_command_already_uses_is_refused_at_import() -> None:
    def cmd(room: str | None = None, other: str | None = typer.Option(None, "-r")) -> None: ...

    with pytest.raises(TypeError, match="already uses -r"):
        in_room()(cmd)
    with pytest.raises(TypeError, match="no parameter"):
        rewrite(
            cmd,
            replace={"missing": inspect.Parameter("missing", inspect.Parameter.KEYWORD_ONLY)},
            before=lambda *_: None,
        )
