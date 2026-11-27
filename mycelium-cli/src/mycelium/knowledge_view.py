# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a task's team learned, as text: ``mycelium memory graph --task``.

The hub's knowledge graph through one task (``GET /rooms/{room}/knowledge``),
drawn as a tree an agent reads before it acts: each memory under the one it
came from (``derived-from``), with its kind, whether it's still open, who wrote
it, and, for a memory from another task, which task. Dead ends are in it on
purpose: they're what stops the next agent trying the same thing.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape

KIND_STYLE = {
    "fact": "",
    "finding": "",
    "dead-end": "red",
}


#: How much of a memory's title a line shows; the rest is a `memory get` away.
TITLE_CHARS = 80


def short(title: str) -> str:
    title = " ".join(title.split())
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1].rstrip() + "…"


def kind_label(kind: str) -> str:
    label = kind.replace("-", " ")
    style = KIND_STYLE.get(kind, "")
    return f"[{style}]{label}[/{style}]" if style else label


def lines(graph: dict[str, Any], task: str | None = None) -> list[str]:
    """The graph as Rich markup lines: a header, then the tree."""
    memories: list[dict[str, Any]] = graph.get("memories") or []
    titles = {t["key"]: t["title"] for t in graph.get("tasks") or []}
    nodes = {m["key"]: m for m in memories}
    own = [m for m in memories if m.get("in_task") is not False]
    title = titles.get(task, task) if task else "What the room learned"
    opened = sum(1 for m in own if m.get("open"))
    head = f"[bold]{escape(title or '')}[/bold]  [dim]{len(own)} memories[/dim]"
    if opened:
        head += f"  [cyan]{opened} open[/cyan]"
    out = [head, ""]
    if not memories:
        out.append(
            "[dim]Nothing learned here yet. Save what you find with "
            "`mycelium memory set <key> <text> --kind finding --task <task>`.[/dim]"
        )
        return out

    # Each memory sits under the first memory in the picture it came from.
    children: dict[str, list[dict[str, Any]]] = {}
    roots = []
    for m in memories:
        parent = next((k for k in m.get("derived_from") or [] if k in nodes), None)
        if parent:
            children.setdefault(parent, []).append(m)
        else:
            roots.append(m)

    seen: set[str] = set()

    def walk(m: dict[str, Any], depth: int) -> None:
        if m["key"] in seen:
            return
        seen.add(m["key"])
        pad = "  " * depth
        tags = " ".join(f"#{t}" for t in m.get("tags") or [])
        parts = [f"{pad}{kind_label(m['kind'])}  {escape(short(m['title']))}"]
        if tags:
            parts.append(f"[dim]{escape(tags)}[/dim]")
        if m.get("open"):
            parts.append("[cyan]open[/cyan]")
        if m.get("in_task") is False and m.get("task"):
            parts.append(f"[dim]in {escape(titles.get(m['task'], m['task']))}[/dim]")
        else:
            parts.append(f"[dim]{escape(m.get('by') or '')}[/dim]")
        parts.append(f"[dim]{escape(m['key'])}[/dim]")
        out.append("  ".join(parts))
        for related in m.get("relates_to") or []:
            if related in nodes:
                out.append(f"{pad}  [dim]relates to {escape(short(nodes[related]['title']))}[/dim]")
        for child in children.get(m["key"], []):
            walk(child, depth + 1)

    for m in roots:
        walk(m, 0)
    return out
