# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Epics in the terminal: a task with parts, drawn as the hub works it out.

The hub reads the board as people do (``GET /rooms/{room}/board``): each open
epic with its parts in path order, and the open tasks that stand alone. This
module draws that answer and decides nothing about it, so the terminal and the
app can't disagree about an epic. The field names and states are frozen in
``contracts/board-vocabulary.json`` under ``epic``.

A part's step number is its place on the path: parts with the same number run
side by side.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

# Frozen in contracts/board-vocabulary.json under ``epic``.
PART_STATES = ["done", "blocked", "waiting", "working", "open"]
WAITING_KINDS = ["ask", "turn", "task"]

STATE_MARK = {
    "done": ("✓", "green"),
    "blocked": ("⊘", "red"),
    "waiting": ("○", "yellow"),
    "working": ("●", "cyan"),
    "open": ("○", "dim"),
}


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def titles(epic: dict[str, Any]) -> dict[str, str]:
    """Every row the epic names, key to title, so a part can be named by title."""
    named = {epic["key"]: epic["title"]}
    named.update({p["key"]: p["title"] for p in epic.get("path") or []})
    return named


def where_it_stands(part: dict[str, Any], named: dict[str, str] | None = None) -> str:
    """Where a part stands, as a sentence a person reads."""
    named = named or {}
    state = part.get("state")
    if state == "done":
        return "Done"
    if state == "blocked":
        return f"Blocked: {part.get('blocked_by')}"
    if state == "waiting":
        after = ", ".join(named.get(k, k) for k in part.get("waiting_on") or [])
        return f"Waits on {after}"
    if state == "working":
        return f"@{part.get('holder')} is on it"
    return "Nobody has it yet"


def progress(epic: dict[str, Any]) -> str:
    """How far along it is and who leads it, as whole sentences."""
    total = epic.get("total") or 0
    done = epic.get("done") or 0
    words = f"{done} of {total} {'part is' if total == 1 else 'parts are'} done."
    if lead := epic.get("lead"):
        words += f" @{lead} leads it."
    return words


def _part_line(part: dict[str, Any], step: int, named: dict[str, str], *, latest: bool) -> Text:
    mark, color = STATE_MARK.get(part.get("state") or "open", ("○", "dim"))
    line = Text("   ")
    line.append(f"{step:>2} ", style="dim")
    line.append(f"{mark} ", style=color)
    line.append(part["title"])
    # What it is and where it stands go on their own line, so a long title or
    # a long list of what it waits on wraps without burying the key.
    line.append("\n        ")
    line.append(where_it_stands(part, named), style=color if color != "cyan" else "")
    if part.get("parts"):
        line.append(f"  {part.get('parts_done', 0)} of {part['parts']} parts done", style="dim")
    line.append(f"  {part['key']}", style="dim")
    if latest and (said := part.get("latest")):
        line.append("\n        ")
        line.append(f"@{said['sender']}: ", style="dim")
        line.append(_clip(said["text"], 96), style="dim italic")
    return line


def epic_lines(epic: dict[str, Any], *, latest: bool = False) -> list[Text]:
    """An epic as a heading and its parts in path order, one line each."""
    head = Text(" ")
    head.append(epic["title"], style="bold")
    head.append(f"   {progress(epic)}", style="dim")
    head.append(f"   {epic['key']}", style="dim")
    named = titles(epic)
    parts = {p["key"]: p for p in epic.get("path") or []}
    lines = [head]
    for n, step in enumerate(epic.get("steps") or [], start=1):
        for key in step:
            if key in parts:
                lines.append(_part_line(parts[key], n, named, latest=latest))
    if not parts:
        lines.append(Text("     It has no parts.", style="dim"))
    return lines


def epic_parts(board: dict[str, Any] | None) -> set[str]:
    """The keys the board draws as epics and their parts, so a list drawn
    beside them can leave those out rather than show them twice."""
    keys: set[str] = set()
    for epic in (board or {}).get("epics") or []:
        keys.add(epic["key"])
        keys.update(p["key"] for p in epic.get("path") or [])
    return keys


def waiting_line(item: dict[str, Any]) -> Text:
    """One thing waiting on a member, and where to answer it."""
    line = Text("  ")
    kind = item.get("kind")
    place = f'"{item["title"]}"' if item.get("title") else "the room"
    if kind == "ask":
        line.append(f"@{item.get('sender')} asked you", style="bold")
        line.append(f" in {place}")
        if (count := item.get("count") or 1) > 1:
            line.append(f" ({count} messages)", style="dim")
    elif kind == "turn":
        line.append("It's your turn", style="bold")
        line.append(f" in {place}. @{item.get('sender')} is running its flow")
    else:
        line.append("You have a task", style="bold")
        line.append(f": {place}")
    line.append(".")
    if item.get("epic_title"):
        line.append(f' It\'s part of "{item["epic_title"]}".', style="dim")
    if item.get("text"):
        line.append("\n    ")
        line.append(_clip(str(item["text"]), 110), style="dim italic")
    return line
