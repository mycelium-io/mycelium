# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Picking the option everyone can live with — code, never a model.

A flow's ``select`` step (``protocols.Step.kind == "select"``) asks nobody. It
reads the options the members suggested and the 0-100 ratings they gave, and
decides three things a person can check by hand:

- **the pick**: the option the least happy member likes best (leximin: each
  option's ratings sorted lowest first, compared from the lowest up, so the
  second-lowest breaks a tie on the lowest, and so on; a final tie goes to the
  earlier letter). A missing rating counts as 0 *for ranking*, so an option
  cannot win because the people who dislike it did not answer.
- **whether everyone is on board**: every member of the cast rated the pick,
  and every rating clears the bar.
- **who fixes it** when not: the lowest rater of the pick among those who
  rated it. When the only problem is members who gave no rating, or the fixes
  allowed are used up, a fix cannot help, and the step is ``stuck``.

The result record lists a missing member as missing, never as 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

#: Letters an option can have, in order.
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

Outcome = Literal["feasible", "infeasible", "stuck"]


@dataclass
class Option:
    """One suggestion on the table: its letter, its text, who suggested it."""

    label: str
    text: str
    authors: list[str] = field(default_factory=list)


def _same(a: str, b: str) -> bool:
    """Two suggestions that differ only in spacing and case are one."""
    squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    return squash(a) == squash(b)


def add_option(options: list[Option], text: str, author: str) -> Option | None:
    """Add a suggestion under the next free letter; ``None`` when there is none.

    A duplicate folds into the earlier option, crediting its author too. After
    26 options nothing more is added.
    """
    text = text.strip()
    if not text:
        return None
    for existing in options:
        if _same(existing.text, text):
            if author not in existing.authors:
                existing.authors.append(author)
            return existing
    if len(options) >= len(LABELS):
        return None
    option = Option(label=LABELS[len(options)], text=text, authors=[author])
    options.append(option)
    return option


def ranking_key(
    option: Option, index: int, cast: list[str], ratings: dict[str, dict[str, int]]
) -> tuple:
    """How an option ranks: its ratings lowest first (missing as 0), then the
    earlier letter. Larger wins."""
    vector = sorted(ratings.get(h, {}).get(option.label, 0) for h in cast)
    return (vector, -index)


def pick(
    options: list[Option],
    cast: list[str],
    ratings: dict[str, dict[str, int]],
    threshold: float,
    *,
    repairs_done: int = 0,
    max_repairs: int = 2,
) -> dict[str, Any]:
    """The result of one ``select`` step, as the record, the scorecard and the
    close carry it.

    ``ratings`` is ``{member: {letter: 0-100}}``; ``threshold`` is 0-1.
    ``repairs_done`` is how many times this step already sent it back for a fix.
    """
    bar = round(threshold * 100)
    table = {
        o.label: {h: ratings[h][o.label] for h in cast if o.label in ratings.get(h, {})}
        for o in options
    }
    base: dict[str, Any] = {
        "threshold": bar,
        "options": [
            {"label": o.label, "text": o.text, "authors": list(o.authors)} for o in options
        ],
        "table": table,
        "cast": list(cast),
    }
    if not options or not cast:
        return base | {
            "outcome": "stuck",
            "pick": None,
            "text": "",
            "ratings": {},
            "lowest": None,
            "missing": list(cast),
            "least_happy": None,
        }
    best_index = max(range(len(options)), key=lambda i: ranking_key(options[i], i, cast, ratings))
    best = options[best_index]
    given = table[best.label]
    missing = [h for h in cast if h not in given]
    short = [h for h in cast if h in given and given[h] < bar]
    lowest = min(given.values()) if given else None
    # The lowest rater of the pick among those who rated it; the earlier in the
    # cast on a tie.
    least_happy = min(short, key=lambda h: (given[h], cast.index(h))) if short else None

    outcome: Outcome
    if not missing and not short:
        outcome = "feasible"
    elif not short or repairs_done >= max_repairs:
        # Only silence stands in the way (a fix cannot reach someone who is not
        # answering), or the fixes allowed are used up.
        outcome = "stuck"
    else:
        outcome = "infeasible"
    return base | {
        "outcome": outcome,
        "pick": best.label,
        "text": best.text,
        "ratings": dict(given),
        "lowest": lowest,
        "missing": missing,
        "least_happy": least_happy,
    }


def scorecard(record: dict[str, Any]) -> str:
    """The rating table as the thread reads it: options down the side, members
    across, ``?`` where a member gave no rating, then the pick and who's short.

    Members are named without ``@``: this is posted into the thread, and a
    mention there would summon every member it names in the middle of the run.
    """
    cast: list[str] = record.get("cast") or []
    options = record.get("options") or []
    table = record.get("table") or {}
    bar = record.get("threshold", 70)
    header = "| option | " + " | ".join(cast) + " |"
    rule = "|---|" + "---|" * len(cast)
    rows = []
    for o in options:
        cells = [str(table.get(o["label"], {}).get(h, "?")) for h in cast]
        mark = " ◀" if o["label"] == record.get("pick") else ""
        rows.append(f"| **{o['label']}**{mark} | " + " | ".join(cells) + " |")
    lines = [header, rule, *rows, "", f"The bar is {bar}."]
    pick_label = record.get("pick")
    if pick_label:
        lines.append(f"Best so far: **{pick_label}**, {summary(record)}")
    return "\n".join(lines)


def summary(record: dict[str, Any]) -> str:
    """One clause on where the pick stands. Names without ``@``, like the scorecard."""
    outcome = record.get("outcome")
    ratings: dict[str, int] = record.get("ratings") or {}
    missing: list[str] = record.get("missing") or []
    bar = record.get("threshold", 70)
    if outcome == "feasible":
        return f"everyone rated it {bar} or more."
    parts = [f"{h} at {r}" for h, r in sorted(ratings.items(), key=lambda kv: kv[1]) if r < bar]
    if missing:
        parts.append("no rating from " + ", ".join(missing))
    return "; ".join(parts) + "." if parts else "short of the bar."
