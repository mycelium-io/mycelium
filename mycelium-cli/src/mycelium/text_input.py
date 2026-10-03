# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One way to hand a command its text, on every command that takes some.

A reply, a thread message, a memory, a skill: each is text a person reads, and
an agent writes it however it is used to writing one elsewhere. As the last
argument, as ``--body`` the way ``gh pr create`` takes one, or from a file it
wrote with ``--file`` (``-`` is stdin). A command that took its text only one of
those ways taught agents to cram it onto one line, so the shape lives here and
a command opts in with one decorator::

    @app.command("send")
    @takes_text("content", "What to say. @handle mentions address agents.")
    def send(content: str, room: str | None = typer.Option(None, "--room")): ...

The command still receives ``content`` as one string; the argument, ``--body``
and ``--file`` are folded into it before it runs. Exactly one of them is given.
"""

from __future__ import annotations

import functools
import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from collections.abc import Callable


def _refuse(msg: str) -> typer.Exit:
    """Say what was wrong with the text given, as a usage mistake (exit 2)."""
    typer.echo(f"Error: {msg}", err=True)
    return typer.Exit(2)


#: The names the added options take inside the wrapper, out of the way of a
#: command's own parameters.
_BODY = "text_body"
_FILE = "text_file"


def read_text_source(path: str) -> str:
    """The text in ``path``, or stdin for ``-``, verbatim."""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise _refuse(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise _refuse(f"{path} is not UTF-8 text.") from exc


def resolve_text(text: str | None, body: str | None, file: str | None, *, noun: str) -> str:
    """Fold the three ways of giving text into one, refusing none or two."""
    given = [s for s in (text, body, file) if s is not None]
    if len(given) > 1:
        raise _refuse(
            f"give the {noun} once: as the argument, --body, or --file, not more than one."
        )
    if file is not None:
        return read_text_source(file)
    if not given:
        raise _refuse(
            f'no {noun}: give it as the argument, --body "...", or --file <path> (- for stdin).'
        )
    return given[0]


def takes_text(
    param: str, help: str, *, noun: str = "text"
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:  # noqa: A002 - typer's own word
    """Let a command take ``param`` as an argument, ``--body`` or ``--file``.

    Put it under ``@app.command``. ``param`` must be one of the command's
    parameters; its argument becomes optional, and ``--body``/``-b`` and
    ``--file``/``-f`` are added. ``noun`` names the text in an error.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn, eval_str=True)
        name = getattr(fn, "__name__", repr(fn))
        if param not in signature.parameters:
            msg = f"{name} has no parameter {param!r} to take text into"
            raise TypeError(msg)
        taken = {"--body", "-b", "--file", "-f"} & _declared(signature)
        if taken:
            msg = f"{name} already uses {', '.join(sorted(taken))}"
            raise TypeError(msg)

        params = []
        for p in signature.parameters.values():
            if p.name == param:
                p = p.replace(  # noqa: PLW2901
                    annotation=str | None,
                    default=typer.Argument(
                        None, help=f"{help} Or give it as --body or --file.", show_default=False
                    ),
                )
            params.append(p)
        options = [
            inspect.Parameter(
                _BODY,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=typer.Option(
                    None,
                    "--body",
                    "-b",
                    help="The same text as an option; markdown, and it can span lines.",
                    show_default=False,
                ),
            ),
            inspect.Parameter(
                _FILE,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=typer.Option(
                    None,
                    "--file",
                    "-f",
                    help="Read the text from a file (- for stdin).",
                    show_default=False,
                ),
            ),
        ]
        # Keyword-only parameters go last; a command's own **kwargs stays after them.
        tail = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
        head = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
        new_signature = signature.replace(parameters=[*_as_keywords(head), *options, *tail])

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            body = kwargs.pop(_BODY, None)
            file = kwargs.pop(_FILE, None)
            bound = new_signature.bind_partial(*args, **kwargs)
            bound.arguments[param] = resolve_text(bound.arguments.get(param), body, file, noun=noun)
            return fn(**bound.arguments)

        # What Typer reads to build the command (inspect.signature honors it).
        wrapper.__signature__ = new_signature  # ty: ignore[unresolved-attribute]
        wrapper.__annotations__ = {p.name: p.annotation for p in new_signature.parameters.values()}
        return wrapper

    return decorate


def _as_keywords(params: list[inspect.Parameter]) -> list[inspect.Parameter]:
    """Typer calls a command with keywords only, so every parameter can be one;
    that is what lets the added options follow a command's own."""
    return [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in params]


def _declared(signature: inspect.Signature) -> set[str]:
    """Every flag a command already declares."""
    out: set[str] = set()
    for p in signature.parameters.values():
        decls = getattr(p.default, "param_decls", None) or ()
        default = getattr(p.default, "default", None)
        if isinstance(default, str) and default.startswith("-"):
            out.add(default)
        out.update(d for d in decls if isinstance(d, str))
    return out
