# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Options every command spells, defaults and resolves the same way.

Agents type a CLI the way they type every other one, so a flag that is spelled
one way here and another way there, or required on one command and optional on
the next, is a command that fails for no reason they can see. Each shared
option is one decorator, put under ``@app.command``::

    @app.command("send")
    @in_room()
    @acts_as()
    @emits_json()
    def send(room: str, handle: str, ...): ...

A decorator rewrites the command's signature, so Typer shows the option the
same way everywhere, and resolves it before the command runs, so the body gets
a plain value: ``room`` is the room to use, never ``None``; ``handle`` is who is
acting. They stack, with each other and with ``text_input.takes_text``.

``mycelium.cli_audit`` checks the whole CLI against these shapes.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from collections.abc import Callable

    from mycelium.config import MyceliumConfig

#: How each shared option is spelled. The audit reads these.
ROOM_FLAGS = ("--room", "-r")
ACT_FLAGS = ("--as", "--handle", "-H")
JSON_FLAGS = ("--json",)
LIMIT_FLAGS = ("--limit", "-n", "-l")
YES_FLAGS = ("--yes", "-y")

ROOM_HELP = "Room (default: MYCELIUM_ROOM_ID, this herdr pane's agent, this folder's membership, then the active room)."
ROOM_FILTER_HELP = "Only this room."
ACT_HELP = "Act as this handle (default: MYCELIUM_AGENT_HANDLE, this herdr pane's agent, this folder's membership, then your login)."
JSON_HELP = "Print JSON (the same as `mycelium --json <command>`)."
YES_HELP = "Go ahead without asking."

_CTX = "cli_context"


# ── resolving ────────────────────────────────────────────────────────────────


def resolve_room(config: MyceliumConfig, flag: str | None = None) -> str:
    """The room to use: ``caller.room``'s answer, or an error that says how to give one."""
    from mycelium import caller
    from mycelium.exceptions import MyceliumError

    answer = caller.room(config, flag)
    if answer.value:
        return answer.value
    raise MyceliumError(
        "No room context found",
        suggestion=(
            "Pass --room <room>, set MYCELIUM_ROOM_ID in your environment, "
            "or run: mycelium room use <name>"
        ),
    )


def room_or_exit(config: MyceliumConfig, flag: str | None = None) -> str:
    """``resolve_room``, with no room said the way commands say an error, then exit 1."""
    from mycelium.exceptions import MyceliumError

    try:
        return resolve_room(config, flag)
    except MyceliumError as e:
        _report(e)
        raise  # print_error exits; this is for the type checker


def resolve_handle(config: MyceliumConfig, flag: str | None, *, fallback: str | None) -> str:
    """Who is acting: ``identity.resolve_actor``'s answer, else ``fallback``, else an error."""
    from mycelium.identity import resolve_actor

    acting = resolve_actor(config, flag, fallback="")
    if acting:
        return acting
    if fallback:
        return fallback
    typer.echo(
        "Error: say who you're acting as: --as <handle>, or set MYCELIUM_AGENT_HANDLE.",
        err=True,
    )
    raise typer.Exit(2)


# ── the rewrite every decorator shares ───────────────────────────────────────


def declared(signature: inspect.Signature) -> set[str]:
    """Every flag a signature already declares."""
    out: set[str] = set()
    for p in signature.parameters.values():
        decls = getattr(p.default, "param_decls", None) or ()
        default = getattr(p.default, "default", None)
        if isinstance(default, str) and default.startswith("-"):
            out.add(default)
        out.update(d for d in decls if isinstance(d, str))
    return out


def _flags_of(p: inspect.Parameter) -> set[str]:
    return declared(inspect.Signature([p]))


def _context_param(signature: inspect.Signature) -> str | None:
    """The name of the command's own ``typer.Context`` parameter, if it has one."""
    for p in signature.parameters.values():
        if p.annotation is typer.Context:
            return p.name
    return None


def rewrite(
    fn: Callable[..., Any],
    *,
    replace: dict[str, inspect.Parameter] | None = None,
    add: list[inspect.Parameter] | None = None,
    needs_context: bool = False,
    before: Callable[[dict[str, Any], dict[str, Any], typer.Context | None], None],
) -> Callable[..., Any]:
    """Give ``fn`` a new signature and run ``before`` on its arguments first.

    ``replace`` swaps a parameter's declaration (the flags it answers to); ``add``
    appends options the command never sees. ``before(kwargs, extras, ctx)``
    receives the command's own arguments to fill in, the added options' values,
    and the click context when ``needs_context``.
    """
    replace = replace or {}
    add = add or []
    signature = inspect.signature(fn, eval_str=True)
    name = getattr(fn, "__name__", repr(fn))
    for param in replace:
        if param not in signature.parameters:
            msg = f"{name} has no parameter {param!r}"
            raise TypeError(msg)
    others = [p for p in signature.parameters.values() if p.name not in replace]
    wanted = (
        set().union(*(_flags_of(p) for p in [*replace.values(), *add]))
        if (replace or add)
        else set()
    )
    taken = wanted & declared(inspect.Signature(others))
    if taken:
        msg = f"{name} already uses {', '.join(sorted(taken))}"
        raise TypeError(msg)

    params = [replace.get(p.name, p) for p in signature.parameters.values()]
    ctx_name = _context_param(signature)
    extra = list(add)
    if needs_context and ctx_name is None:
        extra.append(
            inspect.Parameter(_CTX, inspect.Parameter.KEYWORD_ONLY, annotation=typer.Context)
        )
    tail = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    head = [
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY)
        for p in params
        if p.kind is not inspect.Parameter.VAR_KEYWORD
    ]
    new_signature = signature.replace(parameters=[*head, *extra, *tail])
    added = {p.name for p in add}

    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> Any:
        extras = {k: kwargs.pop(k) for k in list(kwargs) if k in added}
        ctx = kwargs.pop(_CTX, None) if ctx_name is None else kwargs.get(ctx_name)
        before(kwargs, extras, ctx)
        return fn(**kwargs)

    # What Typer reads to build the command (inspect.signature honors it).
    wrapper.__signature__ = new_signature  # ty: ignore[unresolved-attribute]
    wrapper.__annotations__ = {p.name: p.annotation for p in new_signature.parameters.values()}
    return wrapper


def _option(
    name: str, annotation: Any, default: Any, flags: tuple[str, ...], help: str
) -> inspect.Parameter:  # noqa: A002 - typer's word
    return inspect.Parameter(
        name,
        inspect.Parameter.KEYWORD_ONLY,
        annotation=annotation,
        default=typer.Option(default, *flags, help=help, show_default=default not in (None, False)),
    )


def _report(error: Exception) -> None:
    """A MyceliumError raised while resolving, said the way commands say one."""
    from mycelium.error_handler import print_error

    print_error(error)


# ── the options ──────────────────────────────────────────────────────────────


def in_room(
    param: str = "room",
    *,
    resolve: bool = True,
    help: str | None = None,  # noqa: A002
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``--room``/``-r``. Resolved to the room to use (``caller.room``'s order),
    or with ``resolve=False`` left as given, for a filter where none means all,
    or a command that decides itself what no room means (then say so in ``help``)."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        text = help or (ROOM_HELP if resolve else ROOM_FILTER_HELP)
        option = _option(param, str | None, None, ROOM_FLAGS, text)

        def before(kwargs: dict[str, Any], _extras: dict[str, Any], _ctx: Any) -> None:
            if not resolve:
                return
            from mycelium.config import MyceliumConfig
            from mycelium.exceptions import MyceliumError

            try:
                kwargs[param] = resolve_room(MyceliumConfig.load(), kwargs.get(param))
            except MyceliumError as e:
                _report(e)

        return rewrite(fn, replace={param: option}, before=before)

    return decorate


def acts_as(
    param: str = "handle", *, fallback: str | None = "cli-user"
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``--as``/``--handle``/``-H``, never required. Resolved to who is acting
    (``identity.resolve_actor``'s order); when nothing says, ``fallback``, or
    with ``fallback=None`` an error asking for one (a reply must have a sender)."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        option = _option(param, str | None, None, ACT_FLAGS, ACT_HELP)

        def before(kwargs: dict[str, Any], _extras: dict[str, Any], _ctx: Any) -> None:
            from mycelium.config import MyceliumConfig

            kwargs[param] = resolve_handle(
                MyceliumConfig.load(), kwargs.get(param), fallback=fallback
            )

        return rewrite(fn, replace={param: option}, before=before)

    return decorate


def emits_json(param: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``--json`` after the command, the same as ``mycelium --json`` before it.

    Either way the answer lands in ``ctx.obj["json"]`` (what most commands
    read) and, when the command has a ``param`` for it, in that.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        local = "json_flag"
        option = _option(param or local, bool, False, JSON_FLAGS, JSON_HELP)

        def before(kwargs: dict[str, Any], extras: dict[str, Any], ctx: Any) -> None:
            given = kwargs.get(param, False) if param else extras.get(local, False)
            obj = ctx.ensure_object(dict) if ctx is not None else {}
            wanted = bool(given or obj.get("json"))
            obj["json"] = wanted
            if param:
                kwargs[param] = wanted

        if param:
            return rewrite(fn, replace={param: option}, needs_context=True, before=before)
        return rewrite(fn, add=[option], needs_context=True, before=before)

    return decorate


def paged(
    param: str = "limit", default: int | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``--limit``/``-n``/``-l``: how many to show, keeping the command's own default."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn, eval_str=True)
        current = getattr(signature.parameters[param].default, "default", None)
        n = default if default is not None else current
        option = _option(param, int, n, LIMIT_FLAGS, "How many to show.")
        return rewrite(fn, replace={param: option}, before=lambda *_: None)

    return decorate


def confirms(
    param: str = "yes", *, also_force: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``--yes``/``-y``: go ahead without asking. ``also_force`` keeps
    ``--force``/``-f`` as a second spelling where that is what it used to be."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        flags = (*YES_FLAGS, "--force", "-f") if also_force else YES_FLAGS
        option = _option(param, bool, False, flags, YES_HELP)
        return rewrite(fn, replace={param: option}, before=lambda *_: None)

    return decorate
