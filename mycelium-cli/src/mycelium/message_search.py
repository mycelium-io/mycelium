# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium room search``: every message in a room, by any field, with facets.

The hub runs the search (``GET /rooms/{room}/messages/search``); this builds
the query from the words and flags given, and prints what came back: each hit
with where it was said, then the counts per field that say how to narrow, then
the command that reads the next page.
"""

from __future__ import annotations

import json as json_module
import re
from typing import TYPE_CHECKING, Any

import typer

from mycelium import search_grammar
from mycelium.client import typed_client as _typed_client
from mycelium.exceptions import MyceliumError
from mycelium.names import who

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

#: The facets worth a line in the terminal, in the order a reader narrows by.
FACET_ORDER: tuple[str, ...] = (
    "from",
    "task",
    "in",
    "to",
    "mentions",
    "stance",
    "has",
    "is",
    "type",
    "kind",
    "status",
    "step",
    "day",
)

#: Buckets shown per facet line; the JSON carries every one the hub sent.
FACET_WIDTH = 6


def build_query(words: list[str], flags: dict[str, list[str]]) -> str:
    """The query the hub reads: the words as typed, then a clause per flag value.

    ``flags`` maps a field (or ``after``/``before``/``on``/``sort``) to the
    values given for it. Values of a closed field are checked here, so a typo
    is caught before it is sent rather than quietly matching nothing.
    """
    parts = [" ".join(words).strip()] if words else []
    for name, values in flags.items():
        for value in values:
            allowed = search_grammar.CLOSED_VALUES.get(name)
            if allowed and value.lower() not in allowed:
                raise typer.BadParameter(f"--{name} is one of {', '.join(allowed)}, not {value!r}")
            if name in search_grammar.TIME_KEYS and not search_grammar.is_time(value):
                raise typer.BadParameter(
                    f"--{name} {value!r} is neither an ISO date nor an age like 2h, 30m or 1d"
                )
            parts.append(search_grammar.clause(name, value))
    return " ".join(p for p in parts if p)


def _highlight(text: str, needles: list[str]) -> str:
    if not needles:
        return text
    pattern = re.compile(
        "|".join(re.escape(n) for n in sorted(needles, key=lambda n: len(n), reverse=True)), re.I
    )
    return pattern.sub(lambda m: typer.style(m.group(0), fg=typer.colors.YELLOW, bold=True), text)


def _needles(scope: dict[str, Any]) -> list[str]:
    text = scope.get("text") or ""
    phrases = re.findall(r'"([^"]+)"', text)
    words = re.sub(r'"[^"]+"', " ", text).split()
    return [*phrases, *words]


def run(  # noqa: PLR0913 — every knob the read has
    config: MyceliumConfig,
    room_name: str,
    query: str,
    *,
    limit: int,
    cursor: str | None,
    context: int,
    facets_only: bool,
    json_output: bool,
) -> None:
    from mycelium_backend_client.api.messages import (
        search_messages_api_rooms_room_name_messages_search_get as search_api,
    )
    from mycelium_backend_client.types import UNSET

    with _typed_client(config) as client:
        response = search_api.sync_detailed(
            room_name=room_name,
            client=client,
            q=query,
            limit=1 if facets_only else limit,
            cursor=cursor or UNSET,
            context=context,
        )
    if response.status_code == 404:  # noqa: PLR2004
        raise MyceliumError(
            f"Room '{room_name}' not found", suggestion="List rooms with: mycelium room ls"
        )
    if response.status_code != 200:  # noqa: PLR2004
        raise MyceliumError(f"Search failed ({response.status_code}): {response.content[:200]!r}")
    body: dict[str, Any] = json_module.loads(response.content)

    if json_output:
        if facets_only:
            body["hits"] = []
        typer.echo(json_module.dumps(body, indent=2, default=str))
        return
    render(room_name, query, body, limit=limit, facets_only=facets_only)


def render(  # noqa: C901, PLR0912 — one read-out, top to bottom
    room_name: str, query: str, body: dict[str, Any], *, limit: int, facets_only: bool
) -> None:
    scope = body.get("scope") or {}
    hits = [] if facets_only else body.get("hits") or []
    total = body.get("total", 0)
    sort = scope.get("sort", "newest")

    typer.secho(f"\n  {room_name}  ", fg=typer.colors.CYAN, bold=True, nl=False)
    shown = f"{len(hits)} of {total}" if hits and total > len(hits) else str(total)
    noun = "match" if total == 1 else "matches"
    typer.secho(
        f"{shown} {noun} · {sort} first · {body.get('scanned', 0)} messages read",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if query:
        typer.secho(f"  q: {query}", fg=typer.colors.BRIGHT_BLACK)
    for problem in scope.get("problems") or []:
        typer.secho(f"  couldn't read {problem!r}: it was left out", fg=typer.colors.RED)
    typer.echo()

    needles = _needles(scope)
    for hit in hits:
        _print_hit(hit, needles)

    facets = body.get("facets") or {}
    lines = [(name, facets[name]) for name in FACET_ORDER if facets.get(name)]
    if lines:
        typer.secho("  narrow by", fg=typer.colors.BRIGHT_BLACK, bold=True)
        width = max(len(name) for name, _ in lines)
        for name, buckets in lines:
            cells = []
            for b in buckets[:FACET_WIDTH]:
                label = b["label"] if b["label"] == b["value"] else f"{b['label']} ({b['value']})"
                cells.append(f"{label} {typer.style(str(b['count']), bold=True)}")
            more = len(buckets) - FACET_WIDTH
            tail = typer.style(f" · +{more}", fg=typer.colors.BRIGHT_BLACK) if more > 0 else ""
            typer.echo(f"    {name.ljust(width)}  " + " · ".join(cells) + tail)
        typer.echo()

    nxt = body.get("next_cursor")
    if nxt and not facets_only:
        quoted = f' "{query}"' if query else ""
        typer.secho(
            f"  {total - len(hits)} more · mycelium room search{quoted} --room {room_name}"
            f" --limit {limit} --cursor '{nxt}'\n",
            fg=typer.colors.BRIGHT_BLACK,
        )


def _print_hit(hit: dict[str, Any], needles: list[str]) -> None:
    msg = hit["message"]
    stamp = str(msg.get("created_at", ""))[:16].replace("T", " ")
    where = (
        f'in "{hit["task_title"]}"'
        if hit.get("task_title")
        else ("in a thread" if hit.get("thread") else "in the room")
    )
    extras = []
    if hit.get("recipients"):
        extras.append("to " + ", ".join(f"@{r}" for r in hit["recipients"]))
    if hit.get("stance"):
        extras.append(hit["stance"])
    if msg.get("edited_at"):
        extras.append("edited")
    tail = typer.style(f"  [{' · '.join(extras)}]", fg=typer.colors.BRIGHT_BLACK) if extras else ""
    typer.echo(
        f"  {typer.style(stamp, fg=typer.colors.BRIGHT_BLACK)}  "
        f"{typer.style(who(msg['sender_handle']), bold=True)}  "
        f"{typer.style(where, fg=typer.colors.CYAN)}  "
        f"{typer.style(str(msg['id'])[:8], fg=typer.colors.BRIGHT_BLACK)}{tail}"
    )
    for before in hit.get("context_before") or []:
        _print_context(before)
    typer.echo(f"      {_highlight(hit['snippet'], needles)}")
    for after in hit.get("context_after") or []:
        _print_context(after)
    if hit.get("task_key"):
        typer.secho(
            f"      read the thread: mycelium board messages {hit['task_key']}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.echo()


def _print_context(msg: dict[str, Any]) -> None:
    flat = " ".join((msg.get("content") or "").split())
    flat = flat if len(flat) <= 120 else flat[:119] + "…"  # noqa: PLR2004
    typer.secho(f"      │ {msg['sender_handle']}: {flat}", fg=typer.colors.BRIGHT_BLACK)
