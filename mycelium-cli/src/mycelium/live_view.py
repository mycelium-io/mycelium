# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The room's stream as one conversation, for ``mycelium room watch --all``.

Every thread's messages, each labeled with its task, the board's notices, and
the conductor's posts said in a few words rather than as the prompt its
members read.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from rich.markup import escape

from mycelium.names import who
from mycelium.slim.message_format import payload_data_of, payload_type_of

#: The conductor engine's handle, whose posts are drawn from their structured line.
CONDUCTOR = "conductor"
#: How many lines of one message the live view prints before pointing at the thread.
BODY_LINES = 6


def describe_line(line: dict[str, Any]) -> str:
    """A conductor post's structured line, said in a few words.

    The conductor's prose is the prompt its members read; this is the one line
    a person watching needs. Mirrors ``describeConductorLine`` in the app.
    """
    event = line.get("event")
    if event == "open":
        cast = [f"{who} as {role}" for role, who in (line.get("roles") or {}).items()]
        if line.get("members"):
            cast.append(", ".join(line["members"]))
        return f"Running {line.get('protocol')}" + (f" · {' · '.join(cast)}" if cast else "")
    if event == "turn":
        rounds = (
            f" · round {line.get('round')} of {line.get('rounds')}" if line.get("rounds") else ""
        )
        return (
            f"{line.get('step')} → {line.get('to')} · turn {line.get('turn')} of {line.get('cap')}"
            + rounds
        )
    if event == "edge":
        said = {"accept": "accepted", "reject": "blocked", "silent": "did not answer"}.get(
            str(line.get("stance")), "stated no stance"
        )
        return f"{line.get('step')}: {line.get('who')} {said}, on to {line.get('next')}"
    if event == "select":
        record = line.get("select") or {}
        return f"{line.get('step')}: {_pick_summary(record)}"
    if event == "close":
        steps = line.get("steps")
        outcome = line.get("outcome")
        if line.get("pick"):
            # A run that picked says what it went with, or that it couldn't get there.
            if outcome == "converged":
                return f"Everyone's on board: going with {line.get('pick')}"
            return f"Couldn't get everyone there · best was {line.get('pick')}"
        if outcome in ("resolved", "converged"):
            return f"{line.get('protocol')} done · {steps} step{'' if steps == 1 else 's'}"
        return f"{line.get('protocol')} {outcome} · {line.get('reason')}"
    return str(event)


def _pick_summary(record: dict[str, Any]) -> str:
    """Where a pick stands: "B, everyone at 70+" or "B, @finance at 55"."""
    pick = record.get("pick")
    if not pick:
        return "nothing to pick yet"
    bar = record.get("threshold", 70)
    if record.get("outcome") == "feasible":
        return f"{pick}, everyone at {bar}+"
    ratings: dict[str, int] = record.get("ratings") or {}
    short = [f"@{h} at {r}" for h, r in sorted(ratings.items(), key=lambda kv: kv[1]) if r < bar]
    missing = record.get("missing") or []
    if missing:
        short.append("no rating from " + ", ".join(f"@{h}" for h in missing))
    return f"{pick}, {'; '.join(short) or 'short of the bar'}"


@dataclass
class LiveView:
    """Render the room's stream as one conversation across a task and its children.

    With no root task (``room watch --all``), every thread in the room, each
    line labeled with its task, and every board notice.
    """

    root_key: str = ""
    root_episode: str = ""
    root_title: str = ""
    titles: dict[str, str] = field(default_factory=dict)
    #: Thread → row key, so a cut-short message can say where the rest is.
    keys: dict[str, str] = field(default_factory=dict)
    #: The most recent message in the task's own thread: at the end, the result.
    last_root: tuple[str, str] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    #: When the view last showed something, so a stalled room can be called out.
    last_moved: float = field(default_factory=lambda: time.monotonic())

    def __post_init__(self) -> None:
        if self.root_episode:
            self.titles[self.root_episode] = self.root_title
            self.keys[self.root_episode] = self.root_key

    @staticmethod
    def _short(text: str, limit: int = 60) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _where(self, episode: str | None) -> str:
        title = self.titles.get(episode or "")
        return f"[dim]{escape(self._short(title, 32))} ·[/] " if title else ""

    def _notice(self, n: dict[str, Any], stamp: str) -> str | None:
        subkind = n.get("subkind")
        title = str(n.get("title") or n.get("key") or "")
        by = n.get("by") or "someone"
        if n.get("episode") and title:
            self.titles[str(n["episode"])] = title
        if n.get("episode") and n.get("key"):
            self.keys[str(n["episode"])] = str(n["key"])
        title = escape(title)
        by = escape(str(by))
        if subkind == "filed":
            who = f" for [cyan]{escape(str(n['for']))}[/]" if n.get("for") else ""
            return f"  {stamp}  [dim]──[/] [cyan]{by}[/] filed [bold]{title}[/]{who}"
        if subkind == "claimed":
            return f"  {stamp}  [dim]──[/] [cyan]{by}[/] took [bold]{title}[/]"
        if subkind == "resolved":
            if n.get("key") == self.root_key:
                self.done.set()
            return f"  {stamp}  [green]✓[/]  [cyan]{by}[/] resolved [bold]{title}[/]"
        return None

    def quiet_for(self) -> float:
        """Seconds since the view last had anything to show."""
        return time.monotonic() - self.last_moved

    def render(self, frame: dict[str, Any]) -> str | None:
        line = self._render(frame)
        if line is not None:
            self.last_moved = time.monotonic()
        return line

    def _render(self, frame: dict[str, Any]) -> str | None:
        if frame.get("message_type") != "l9_exchange":
            return None
        try:
            data = json.loads(frame.get("content") or "{}")
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        stamp = f"[dim]{time.strftime('%H:%M:%S')}[/]"
        ptype = payload_type_of(data)
        if ptype == "notice":
            return self._notice(payload_data_of(data), stamp)
        if ptype in {"ping", "presence", "keepalive"}:
            return None
        text = str(data.get("content") or "").strip()
        if not text:
            return None
        sender = str(frame.get("sender_handle") or "?")
        episode = frame.get("episode")
        where = self._where(episode)
        if sender == CONDUCTOR:
            line = payload_data_of(data).get("conductor")
            said = (
                describe_line(line)
                if isinstance(line, dict)
                else self._short(text.splitlines()[0], 80)
            )
            return f"  {stamp}  [magenta]{CONDUCTOR}[/] {where}[dim]{escape(said)}[/]"
        if episode == self.root_episode:
            self.last_root = (sender, text)
        return f"  {stamp}  [yellow]{escape(who(sender))}[/] {where}{self._body(text, episode)}"

    def _body(self, text: str, episode: str | None) -> str:
        """A message as the view prints it: its first lines, and where to read the rest."""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        shown = "\n".join(lines[:BODY_LINES])
        more = len(lines) - BODY_LINES
        body = escape(shown).replace("\n", "\n" + " " * 12)
        if more > 0:
            key = self.keys.get(episode or "")
            where = f" · board messages {key}" if key else ""
            body += f"\n{' ' * 12}[dim]… {more} more line{'s' if more > 1 else ''}{where}[/]"
        return body
