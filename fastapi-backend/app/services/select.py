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
- **the pick**, by CONCORD's rules (the IoC team's specification,
  ioc-project.github.io/cognition-protocols/): among the options every member
  rated at the bar or above, failing that every option anyone rated, the one
  the least happy member is best off with (leximin over the placed ratings:
  each option's sorted lowest first, compared from the lowest up; a tie goes
  to the option rated by more members, then the earlier one). A new best only
  replaces the option picked before when it is better by ``eps``.
- **whether everyone is on board**: every member rated the pick at the bar or
  above, and no rating anywhere is missing after being asked for again. When
  not, the member who rates the pick lowest is the one asked for a fix, until
  the fixes allowed are used up: then it is ``stuck``, and the pick stands as
  the best found.

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


#: How many of an option's first words make its name.
NAME_WORDS = 5


def _first_words(text: str) -> tuple[list[str], bool]:
    """The words of ``text``'s first sentence or clause, brackets dropped, and
    whether that is the whole of ``text``."""
    first = re.split(r"(?<=[.;:])\s", text.strip(), maxsplit=1)[0].rstrip(".;:")
    return re.sub(r"[()\[\]]", "", first).split(), first == text.strip().rstrip(".")


def short_name(text: str, skip: int = 0) -> str:
    """An option's name, for a reader who sees only its letter: a few words of
    its first sentence or clause, with ``…`` where it's cut. ``skip`` starts
    past words other options share, so the name is what tells it apart.
    Brackets are dropped, since the name sits inside a pair."""
    words, whole = _first_words(text)
    if skip >= len(words):
        skip = 0
    cut = words[skip : skip + NAME_WORDS]
    head = "…" if skip else ""
    tail = "" if whole and skip + len(cut) == len(words) else "…"
    return head + " ".join(cut).rstrip(",") + tail


def option_names(options: list[tuple[str, str]]) -> dict[str, str]:
    """``{label: name}`` for ``(label, text)`` options, each name different
    from the others where the texts allow: options whose first words are the
    same are named by the words after the ones they share."""
    first = {label: short_name(text) for label, text in options}
    names = dict(first)
    for label, text in options:
        twins = [t for lab, t in options if lab != label and first[lab] == first[label]]
        if not twins:
            continue
        words = [w.rstrip(",;").lower() for w in _first_words(text)[0]]
        shared = 0
        for twin in twins:
            other = [w.rstrip(",;").lower() for w in _first_words(twin)[0]]
            same = next(
                (i for i, (a, b) in enumerate(zip(words, other, strict=False)) if a != b),
                min(len(words), len(other)),
            )
            shared = max(shared, same)
        names[label] = short_name(text, skip=shared)
    return names


def named(label: str, text: str, names: dict[str, str] | None = None) -> str:
    """``B (Ship at once, and cancel…)``: a letter a reader can follow, by its
    name among ``names`` when given (``option_names``)."""
    return f"{label} ({(names or {}).get(label) or short_name(text)})"


def pick_named(record: dict[str, Any]) -> str:
    """A pick record's option, named as it was among the options rated."""
    label = str(record.get("pick") or "")
    options = [(str(o.get("label")), str(o.get("text"))) for o in record.get("options") or []]
    return named(label, str(record.get("text") or ""), option_names(options))


def same_text(a: str, b: str) -> bool:
    """Two proposals that differ only in spacing and case are one."""
    squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    return squash(a) == squash(b)


def add_option(
    options: list[Option], text: str, author: str, why: str = "", *, label: str | None = None
) -> Option | None:
    """Add a proposal under ``label``, or the next free letter; ``None`` when
    there is none.

    A duplicate folds into the earlier option, crediting its author (and its
    reason) too. After 26 lettered options nothing more is added.
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
    if label is None:
        if len(options) >= len(LABELS):
            return None
        label = LABELS[len(options)]
    elif any(o.label == label for o in options):
        return None
    option = Option(label=label, text=text, authors=[author])
    if why:
        option.why[author] = why
    options.append(option)
    return option


def placed(raw: float, anchor: tuple[float, float] | None) -> float:
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


#: How close two placed ratings have to be to count as equal.
TOL = 1e-9


def leximin(at: dict[str, float]) -> list[float]:
    """An option's placed ratings, lowest first: what the pick compares."""
    return sorted(at.values())


def lex_gt(v: list[float], u: list[float]) -> bool:
    """Whether ``v`` beats ``u`` leximin: higher at the first place they
    differ, or as good everywhere and rated by more members."""
    for a, b in zip(v, u, strict=False):
        if a > b + TOL:
            return True
        if b > a + TOL:
            return False
    return len(v) > len(u)


def accepts(v: list[float], u: list[float], eps: float) -> bool:
    """Whether ``v`` is enough better than ``u`` to replace it: at least ``eps``
    higher at some place, no lower anywhere before it."""
    return any(
        v[k] >= u[k] + eps - TOL and all(v[i] >= u[i] - TOL for i in range(k))
        for k in range(min(len(v), len(u)))
    )


def pick(
    options: list[Option],
    cast: list[str],
    ratings: dict[str, dict[str, float]],
    threshold: float,
    *,
    repairs_done: int = 0,
    max_repairs: int = 5,
    anchors: dict[str, tuple[float, float]] | None = None,
    reasons: dict[str, dict[str, str]] | None = None,
    incumbent: str | None = None,
    eps: float = 0.0,
    unrated: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """The result of one ``select`` step, as the record, the scorecard and the
    close carry it.

    ``ratings`` is ``{member: {option: 0-100}}`` on each member's own scale;
    ``anchors`` is ``{member: (bad, ideal)}``, the member's ratings of the two
    reference outcomes; ``reasons`` is ``{member: {option: why}}``.
    ``threshold`` is the bar, 0-1, on the placed scale. ``repairs_done`` is how
    many times this step already sent it back for a fix. ``incumbent`` is the
    option the step picked last time, which a new best has to beat by ``eps``
    to replace. ``unrated`` is ``{member: {option}}``, the ratings a member
    still hadn't given when asked again: while any stands, nothing is agreed.

    The rules are CONCORD's: the options everyone rated at the bar or above
    are the ones to pick among, failing that every option anyone rated; the
    pick is the best of those leximin; it replaces the incumbent only when
    better by ``eps``; it's agreed when everyone rated it at the bar or above
    and no rating anywhere is missing; otherwise the member who rates it
    lowest (the earlier in the cast on a tie) is asked for a fix, until the
    fixes allowed are used up.
    """
    anchors = anchors or {}
    reasons = reasons or {}
    unrated = unrated or {}
    bar = round(threshold * 100)
    table = {
        o.label: {h: ratings[h][o.label] for h in cast if o.label in ratings.get(h, {})}
        for o in options
    }
    exact = {
        label: {h: placed(raw, anchors.get(h)) for h, raw in given.items()}
        for label, given in table.items()
    }
    standing = {label: {h: round(v, 4) for h, v in at.items()} for label, at in exact.items()}
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
    scored = [o for o in options if exact.get(o.label)]
    if not cast or not scored:
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
            "selected": None,
            "accepted": False,
            "feasible": [],
            "unrated": {h: sorted(v) for h, v in unrated.items() if v},
        }

    def absent(label: str) -> list[str]:
        return [h for h in cast if h not in exact[label]]

    feasible = [
        o.label
        for o in scored
        if not absent(o.label) and min(exact[o.label].values()) >= threshold - TOL
    ]
    pool = [o for o in scored if o.label in feasible] or scored
    selected = pool[0]
    for o in pool[1:]:
        if lex_gt(leximin(exact[o.label]), leximin(exact[selected.label])):
            selected = o
    by_label = {o.label: o for o in options}
    held = by_label.get(incumbent or "")
    if (
        held is None
        or not exact.get(held.label)
        or (
            selected.label != held.label
            and accepts(leximin(exact[selected.label]), leximin(exact[held.label]), eps)
        )
    ):
        best, accepted = selected, True
    else:
        best, accepted = held, False

    given = table[best.label]
    at = exact[best.label]
    missing = absent(best.label)
    short = [h for h in cast if h in at and at[h] < threshold - TOL]
    lowest = min(at.values())
    any_unrated = any(unrated.values())

    outcome: Outcome
    if lowest >= threshold - TOL and not missing and not any_unrated:
        outcome = "feasible"
    elif repairs_done >= max_repairs:
        outcome = "stuck"
    else:
        outcome = "infeasible"
    # The member who rates the pick lowest, the earlier in the cast on a tie:
    # the one asked for a fix.
    least_happy = min(at, key=lambda h: (at[h], cast.index(h))) if outcome == "infeasible" else None
    return base | {
        "outcome": outcome,
        "pick": best.label,
        "text": best.text,
        "ratings": dict(given),
        "standing": dict(standing[best.label]),
        "verdicts": {h: verdict(at.get(h), threshold) for h in cast},
        "lowest": round(lowest, 4),
        "missing": missing,
        "least_happy": least_happy,
        "short": [
            {"member": h, "placed": standing[best.label][h], "why": why[best.label].get(h, "")}
            for h in sorted(short, key=lambda h: (at[h], cast.index(h)))
        ],
        "selected": selected.label,
        "accepted": accepted,
        "feasible": feasible,
        "unrated": {h: sorted(v) for h, v in unrated.items() if v},
    }


def mid_sentence(text: str) -> str:
    """``text`` as it reads after a comma: its first letter lowered, unless the
    first word is "I" or reads as a name or an acronym (``SLA``, ``iOS``)."""
    first = text.split(maxsplit=1)[0] if text.strip() else ""
    keep = first == "I" or first.startswith("I'") or any(c.isupper() for c in first[1:])
    return text if keep or not text else text[0].lower() + text[1:]


def _because(why: str) -> str:
    return f", because {mid_sentence(why)}" if why else ", with no reason given"


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
        blocks.append(f"Where {pick_named(record)} stands: {summary(record)}")
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
