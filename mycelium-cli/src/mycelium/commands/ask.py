# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium ask --approve``: ask a person to approve something, in a task's thread.

The ask is a kind the hub knows, with known fields, and the app draws it as a
card with Approve and Decline (``POST /rooms/{room}/asks``). The answer comes
back as a message that wakes you, and ``await`` gives you the decision as a
value (``answer.decision``, ``answer.reason``) rather than prose to read.
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
KINDS = ("approve",)
#: The optional facts an ask may carry, in the order the card shows them.
FACTS = ("happens", "why", "undo", "link")


def _row_key(room: str, row_id: str) -> str:
    """The row key for however ``row_id`` was typed (``t3``, ``work/auth``)."""
    from mycelium.commands.board import _row

    item = _row(room, row_id)
    return item.source.label if item is not None else row_id


@doc_ref(
    usage='mycelium ask --approve "<question>" [--happens <text>] [--why <text>] [--undo <text>] [--link <url>] [--to <person>] [--task <id>]',
    desc=(
        "Ask a person to approve something. They answer in the app, and the answer "
        "wakes you with the decision as a value. Only the question is required."
    ),
    group="board",
)
@in_room()
@acts_as(fallback=None)
@emits_json()
def ask(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="What you're asking them to approve."),
    approve: bool = typer.Option(False, "--approve", help="Ask for an approval (the one kind)."),
    happens: str | None = typer.Option(None, "--happens", help="What will happen if approved."),
    why: str | None = typer.Option(None, "--why", help="Why now."),
    undo: str | None = typer.Option(
        None, "--undo", help="How to undo it. Include it whenever the change is hard to reverse."
    ),
    link: str | None = typer.Option(None, "--link", help="A PR, a memory or a URL it's about."),
    to: str | None = typer.Option(
        None, "--to", help="Who to ask. Default: the person who filed the task."
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        "-u",
        help="The task to ask in (e.g. t3, work/auth). Default: the thread you were last "
        "asked in, else the one task you hold.",
    ),
    room: str | None = None,
    handle: str | None = None,
) -> None:
    """Ask a person to approve something, in a task's thread.

    The person sees a card with Approve and Decline, in the thread and under
    Waiting on you. Their answer wakes you: ``await`` gives the decision as
    ``answer.decision`` (approved or declined) and ``answer.reason``. A decision
    is final. To try again, ask again.

    Examples:
        mycelium ask --approve "Turn Apple Pay on for everyone on Friday at 9:00"
        mycelium ask --approve "Merge the checkout PR" --link https://github.com/o/r/pull/7 --undo "Revert the merge"
    """
    if not approve:
        typer.secho(
            "Say what kind of ask it is: --approve (the one kind for now).", fg=typer.colors.RED
        )
        raise typer.Exit(2)
    try:
        from mycelium_backend_client.api.asks import create_ask_api_rooms_room_name_asks_post
        from mycelium_backend_client.models import AskCreate, AskPosted
        from mycelium_backend_client.types import UNSET

        config = MyceliumConfig.load()
        room_name = room or ""
        given = {"happens": happens, "why": why, "undo": undo, "link": link}
        body = AskCreate(
            handle=handle or "",
            question=question,
            kind="approve",
            to=to.lstrip("@") if to else UNSET,
            task=_row_key(room_name, task) if task else UNSET,
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
    where = f"{room_name}/{posted.task}" if posted.task else room_name
    typer.secho(
        f"  ⟫  asked @{posted.ask.to} to approve, in {where} ({posted.ask.id})",
        fg=typer.colors.GREEN,
    )
    typer.secho(
        "     Their answer wakes you, and await gives it as answer.decision and answer.reason.",
        fg=typer.colors.BRIGHT_BLACK,
    )
