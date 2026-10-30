# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium ask``: ask a person something, where you're working.

Three kinds, one card: ``--approve`` (a yes or no on something you'll do),
``--choose`` (pick one of your ``--option`` lines, or several with
``--multiple``) and ``--question`` (an open question). The ask is a kind the
hub knows, with known fields, and the app draws it (``POST /rooms/{room}/asks``).
The answer comes back as a message that wakes you, and ``await`` gives it as
values (``answer.decision``, ``answer.choices``/``chosen``, ``answer.text``),
with the question it answers and who answered, rather than prose to read.
Kinds and fields are frozen in ``contracts/approvals.json``.
"""

from __future__ import annotations

import json
import sys

import typer

from mycelium.cli_options import acts_as, emits_json, in_room
from mycelium.client import answered, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

#: The kinds of ask, as ``contracts/approvals.json`` freezes them.
KINDS = ("approve", "choose", "question")
#: The optional facts any ask may carry, in the order the card shows them.
FACTS = ("happens", "why", "undo", "link")
#: ``recommend`` on an approve: you would go ahead.
RECOMMEND_APPROVE = "approve"
#: What each kind asks a person to do, for the line ``ask`` prints.
_ASKED_TO = {"approve": "approve", "choose": "pick", "question": "answer"}


def _row_key(room: str, row_id: str) -> str:
    """The row key for however ``row_id`` was typed (``t3``, ``work/auth``)."""
    from mycelium.commands.board import _row

    item = _row(room, row_id)
    return item.source.label if item is not None else row_id


def _recommend(recommend: bool, options: list[str] | None) -> list[str] | str | None:
    """What you'd do, as the hub takes it: ``approve`` for ``--recommend``, or
    the option numbers ``--recommend-option`` gave (``1``, ``1,3``, or repeated)."""
    if options:
        return [p.strip() for given in options for p in given.split(",") if p.strip()]
    return RECOMMEND_APPROVE if recommend else None


@doc_ref(
    usage=(
        'mycelium ask [--approve | --choose | --question] "<question>" [--option <text>]... '
        "[--multiple] [--recommend] [--recommend-option <n>] [--suggest <text>] "
        "[--happens <text>] [--why <text>] [--undo <text>] [--link <url>] [--to <person>] "
        "[--task <id>]"
    ),
    desc=(
        "Ask a person to approve something, pick from options, or answer a question. "
        "They answer in the app, and the answer wakes you with what they decided as values."
    ),
    group="board",
)
@in_room()
@acts_as(fallback=None)
@emits_json()
def ask(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="What you're asking."),
    approve: bool = typer.Option(False, "--approve", help="A yes or no on something you'll do."),
    choose: bool = typer.Option(False, "--choose", help="Pick from the --option lines."),
    open_question: bool = typer.Option(False, "--question", help="An open question."),
    option: list[str] | None = typer.Option(
        None, "--option", help="One option of a --choose, in order. Give two or more."
    ),
    multiple: bool = typer.Option(False, "--multiple", help="A --choose may pick several."),
    recommend: bool = typer.Option(
        False, "--recommend", help="On --approve: you recommend going ahead, not only asking."
    ),
    recommend_option: list[str] | None = typer.Option(
        None,
        "--recommend-option",
        help="On --choose: the option number you'd pick (1), or several with --multiple (1,3).",
    ),
    suggest: str | None = typer.Option(
        None, "--suggest", help="Your draft answer to a --question, which they can send or edit."
    ),
    happens: str | None = typer.Option(None, "--happens", help="What will happen if approved."),
    why: str | None = typer.Option(None, "--why", help="Why now."),
    undo: str | None = typer.Option(
        None, "--undo", help="How to undo it. Include it whenever the change is hard to reverse."
    ),
    link: str | None = typer.Option(None, "--link", help="A PR, a memory or a URL it's about."),
    to: str | None = typer.Option(
        None,
        "--to",
        help="Who it waits on. Default: the person who filed the task, else your owner. "
        "Anyone in the room may answer.",
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        "-u",
        help="The task to ask in (e.g. t3, work/auth). Default: where you were last asked, "
        "a task's thread or the room's channel, else the one task you hold, else the channel.",
    ),
    room: str | None = None,
    handle: str | None = None,
) -> None:
    """Ask a person something, in the task's thread, or in the room's channel
    when it's about no task.

    The person sees a card where you asked, and under Waiting on you. Anyone in
    the room may answer it, and every answer can carry a note. The answer wakes
    you: ``await`` gives ``answer.decision`` (approved or declined) on an
    approve, ``answer.choices`` and ``answer.chosen`` on a choose, and
    ``answer.text`` (the answer to a question, or the note), with
    ``answer.question`` and who answered (``by``) and who you asked (``for``).
    If someone other than whom you asked answers, take it as input, and ask
    again if you need their own word. An answer is final. To try again, ask
    again.

    Examples:
        mycelium ask --approve "Turn Apple Pay on for everyone on Friday at 9:00" --recommend
        mycelium ask --approve "Merge the checkout PR" --link https://github.com/o/r/pull/7 --undo "Revert the merge"
        mycelium ask --choose "Which first?" --option "Implement to the spec" --option "Copy their code" --recommend-option 1
        mycelium ask --question "Where is it most broken for you?" --suggest "The mechanics"
    """
    kinds = [k for k, on in zip(KINDS, (approve, choose, open_question), strict=True) if on]
    if len(kinds) != 1:
        typer.secho(
            "Say what kind of ask it is: one of --approve, --choose or --question.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    kind = kinds[0]
    try:
        from mycelium_backend_client.api.asks import create_ask_api_rooms_room_name_asks_post
        from mycelium_backend_client.models import AskCreate, AskOptionCreate, AskPosted
        from mycelium_backend_client.types import UNSET

        config = MyceliumConfig.load()
        room_name = room or ""
        given = {"happens": happens, "why": why, "undo": undo, "link": link, "suggest": suggest}
        picks = _recommend(recommend, recommend_option)
        body = AskCreate(
            handle=handle or "",
            question=question,
            kind=kind,
            to=to.lstrip("@") if to else UNSET,
            task=_row_key(room_name, task) if task else UNSET,
            options=[AskOptionCreate(label=o) for o in option] if option else UNSET,
            multiple=True if multiple else UNSET,
            recommend=picks if picks is not None else UNSET,
            **{k: v for k, v in given.items() if v},
        )
        with typed_client(
            config, timeout=30.0, handle=handle, raise_on_unexpected_status=False
        ) as client:
            posted = answered(
                create_ask_api_rooms_room_name_asks_post.sync_detailed(
                    room_name, client=client, body=body
                ),
                AskPosted,
            )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from e
    if ctx.obj and ctx.obj.get("json"):
        sys.stdout.write(json.dumps(posted.to_dict(), indent=2) + "\n")
        return
    where = f"{room_name}/{posted.task}" if posted.task else f"{room_name}'s channel"
    typer.secho(
        f"  ⟫  asked @{posted.ask.to} to {_ASKED_TO[kind]}, in {where} (ask {posted.ask.id})",
        fg=typer.colors.GREEN,
    )
    typer.secho(
        "     The answer wakes you, and await gives it as answer.* values.",
        fg=typer.colors.BRIGHT_BLACK,
    )
