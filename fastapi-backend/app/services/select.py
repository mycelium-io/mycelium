# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Picking the option everyone can live with — code, never a model.

A flow's ``select`` step (``protocols.Step.kind == "select"``) asks nobody. It
reads the options the members proposed and the ratings they gave, and decides
three things a person can check by hand:

- **where each rating stands for its member**: each member first rated the
  same two reference outcomes, a bad one and an ideal one, on its own 0-100
  scale. A later rating is placed between those two (``placed``): 0 at the
  member's bad outcome, 1 at its ideal, so one member's 0.6 means what
  another's does, whatever numbers each used. A member with no reference
  ratings is placed on its raw scale (``raw / 100``).
- **the pick**: the option the least happy member is best off with (leximin
  over the placed ratings: each option's sorted lowest first, compared from the
  lowest up; a final tie goes to the earlier letter). A missing rating counts
  as 0 *for ranking*, so an option cannot win because the people who dislike
  it did not answer.
- **whether everyone is on board**: every member rated the pick, and every
  placed rating is at the bar or above. When not, the member least happy with
  it, among those who rated it, is the one asked for a fix. When only silence
  stands in the way, or the fixes allowed are used up, it is ``stuck``, and the
  pick stands as the best found.

**The numbers are never the argument.** Every rating carries its member's
reason, and everything this module writes for people leads with what a rating
means (:func:`verdict`) and why, with the numbers last. The record lists a
missing member as missing, never as 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

#: Letters an option can have, in order.
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

Outcome = Literal["feasible", "infeasible", "stuck"]

#: Where a placed rating counts as close to the member's ideal outcome.
NEAR_IDEAL = 0.9


@dataclass
class Option:
    """One proposal on the table: its letter, its text, who proposed it and why."""

    label: str
    text: str
    authors: list[str] = field(default_factory=list)
    #: Why each author proposed it, by author.
    why: dict[str, str] = field(default_factory=dict)


def same_text(a: str, b: str) -> bool:
    """Two proposals that differ only in spacing and case are one."""
    squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    return squash(a) == squash(b)


def add_option(options: list[Option], text: str, author: str, why: str = "") -> Option | None:
    """Add a proposal under the next free letter; ``None`` when there is none.

    A duplicate folds into the earlier option, crediting its author (and its
    reason) too. After 26 options nothing more is added.
    """
    text = text.strip()
    if not text:
        return None
    for existing in options:
        if same_text(existing.text, text):
            if author not in existing.authors:
                existing.authors.append(author)
            if why and author not in existing.why:
                existing.why[author] = why
            return existing
    if len(options) >= len(LABELS):
        return None
    option = Option(label=LABELS[len(options)], text=text, authors=[author])
    if why:
        option.why[author] = why
    options.append(option)
    return option


def placed(raw: int, anchor: tuple[int, int] | None) -> float:
    """Where ``raw`` stands between a member's bad and ideal ratings, 0 to 1.

    Below the bad outcome is 0 and above the ideal is 1: a rating outside the
    member's own range says no more than that end of it does."""
    if anchor is None:
        return max(0.0, min(1.0, raw / 100))
    bad, ideal = anchor
    if ideal <= bad:
        return max(0.0, min(1.0, raw / 100))
    return max(0.0, min(1.0, (raw - bad) / (ideal - bad)))


def verdict(value: float | None, bar: float) -> str:
    """What a placed rating means, in words, against the bar (both 0-1)."""
    if value is None:
        return "gave no rating"
    if value <= 0:
        return "no better than the bad outcome"
    if value < bar:
        return "short of the bar"
    if value >= NEAR_IDEAL:
        return "close to the ideal"
    return "meets the bar"


def ranking_key(
    option: Option, index: int, cast: list[str], standing: dict[str, dict[str, float]]
) -> tuple:
    """How an option ranks: its placed ratings lowest first (missing as 0),
    then the earlier letter. Larger wins."""
    vector = sorted(standing.get(option.label, {}).get(h, 0.0) for h in cast)
    return (vector, -index)


def pick(
    options: list[Option],
    cast: list[str],
    ratings: dict[str, dict[str, int]],
    threshold: float,
    *,
    repairs_done: int = 0,
    max_repairs: int = 5,
    anchors: dict[str, tuple[int, int]] | None = None,
    reasons: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The result of one ``select`` step, as the record, the scorecard and the
    close carry it.

    ``ratings`` is ``{member: {letter: 0-100}}`` on each member's own scale;
    ``anchors`` is ``{member: (bad, ideal)}``, the member's ratings of the two
    reference outcomes; ``reasons`` is ``{member: {letter: why}}``.
    ``threshold`` is the bar, 0-1, on the placed scale. ``repairs_done`` is how
    many times this step already sent it back for a fix.
    """
    anchors = anchors or {}
    reasons = reasons or {}
    bar = round(threshold * 100)
    table = {
        o.label: {h: ratings[h][o.label] for h in cast if o.label in ratings.get(h, {})}
        for o in options
    }
    standing = {
        label: {h: round(placed(raw, anchors.get(h)), 2) for h, raw in given.items()}
        for label, given in table.items()
    }
    why = {
        o.label: {h: reasons[h][o.label] for h in cast if reasons.get(h, {}).get(o.label)}
        for o in options
    }
    base: dict[str, Any] = {
        "threshold": bar,
        "anchored": [h for h in cast if h in anchors],
        "options": [
            {"label": o.label, "text": o.text, "authors": list(o.authors), "why": dict(o.why)}
            for o in options
        ],
        "table": table,
        "placed": standing,
        "reasons": why,
        "cast": list(cast),
    }
    if not options or not cast:
        return base | {
            "outcome": "stuck",
            "pick": None,
            "text": "",
            "ratings": {},
            "standing": {},
            "verdicts": {},
            "lowest": None,
            "missing": list(cast),
            "least_happy": None,
            "short": [],
        }
    best_index = max(range(len(options)), key=lambda i: ranking_key(options[i], i, cast, standing))
    best = options[best_index]
    given = table[best.label]
    at = standing[best.label]
    missing = [h for h in cast if h not in given]
    short = [h for h in cast if h in at and at[h] < threshold]
    lowest = min(at.values()) if at else None
    # The least happy rater of the pick among those who rated it; the earlier
    # in the cast on a tie.
    least_happy = min(short, key=lambda h: (at[h], cast.index(h))) if short else None

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
        "standing": dict(at),
        "verdicts": {h: verdict(at.get(h), threshold) for h in cast},
        "lowest": lowest,
        "missing": missing,
        "least_happy": least_happy,
        "short": [
            {"member": h, "placed": at[h], "why": why[best.label].get(h, "")}
            for h in sorted(short, key=lambda h: (at[h], cast.index(h)))
        ],
    }


def _because(why: str) -> str:
    return f", because {why[0].lower() + why[1:]}" if why else ", with no reason given"


def views(record: dict[str, Any], label: str) -> list[str]:
    """Each member's view of one option, in words: ``legal: short of the bar,
    because the Friday window breaks certification``. Names without ``@``."""
    cast: list[str] = record.get("cast") or []
    at: dict[str, float] = (record.get("placed") or {}).get(label, {})
    why: dict[str, str] = (record.get("reasons") or {}).get(label, {})
    bar = (record.get("threshold") or 0) / 100
    lines = []
    for h in cast:
        if h not in at:
            lines.append(f"{h}: gave no rating")
            continue
        lines.append(f"{h}: {verdict(at[h], bar)}{_because(why.get(h, ''))}")
    return lines


def scorecard(record: dict[str, Any]) -> str:
    """The pick as the thread reads it: each option with every member's view of
    it in words, the pick first, then where it stands, and the numbers last.

    Members are named without ``@``: this is posted into the thread, and a
    mention there would summon every member it names in the middle of the run.
    """
    options = record.get("options") or []
    chosen = record.get("pick")
    ordered = sorted(options, key=lambda o: o["label"] != chosen)
    blocks = []
    for o in ordered:
        mark = " (best so far)" if o["label"] == chosen else ""
        lines = [f"**{o['label']}**{mark}: {o['text']}"]
        lines += [f"- {v}" for v in views(record, o["label"])]
        blocks.append("\n".join(lines))
    if chosen:
        blocks.append(f"Where {chosen} stands: {summary(record)}")
    blocks.append(numbers(record))
    return "\n\n".join(blocks)


def numbers(record: dict[str, Any]) -> str:
    """The ratings as a table, for anyone checking the arithmetic: each member's
    rating on its own scale, and in brackets how far that is from its bad
    outcome to its ideal."""
    cast: list[str] = record.get("cast") or []
    options = record.get("options") or []
    table = record.get("table") or {}
    standing = record.get("placed") or {}
    header = "| option | " + " | ".join(cast) + " |"
    rule = "|---|" + "---|" * len(cast)
    rows = []
    for o in options:
        cells = []
        for h in cast:
            raw = table.get(o["label"], {}).get(h)
            at = standing.get(o["label"], {}).get(h)
            cells.append("?" if raw is None else f"{raw} ({round(at * 100)}%)")
        rows.append(f"| {o['label']} | " + " | ".join(cells) + " |")
    said = (
        "The numbers, for anyone checking: each member's rating on its own scale, and in "
        f"brackets how far it is from that member's bad outcome to its ideal. The bar is "
        f"{record.get('threshold', 0)}%."
    )
    return "\n".join([said, "", header, rule, *rows])


def summary(record: dict[str, Any]) -> str:
    """Where the pick stands, in words: who's short and why. Names without ``@``."""
    outcome = record.get("outcome")
    missing: list[str] = record.get("missing") or []
    if outcome == "feasible":
        return "everyone meets the bar."
    parts = [
        f"{s['member']} is short of the bar{_because(s.get('why') or '')}"
        if s.get("placed", 0) > 0
        else f"{s['member']} finds it no better than the bad outcome{_because(s.get('why') or '')}"
        for s in record.get("short") or []
    ]
    if missing:
        parts.append("no rating from " + ", ".join(missing))
    return "; ".join(parts) + "." if parts else "short of the bar."
