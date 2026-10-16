# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The shared frame a team builds before work starts, merged in code.

Members write what they understand a task to be, and label it with markers
(:mod:`app.services.markers`): points, the meaning of a word, how a point
would be checked. This module folds those labelled pieces into one frame for
the conductor, with no model and no vote:

- **Points fold** when they are the same type and say the same thing: equal
  text, or close enough by the hub's embedding model when it is there. Each
  point keeps who stated it. Nothing is dropped, averaged or rewritten.
- **Problems are flagged, never resolved.** A point only one member stated, two
  members saying different things about the same subject, a word used in
  different senses, a point nothing checks, a member who never answered.
- **The result is a contract**: one dict a memory can carry in frontmatter and
  a person can read rendered as markdown (:func:`render`).

Same replies in the same cast order give the same frame, ids and flags. The
similarity function is passed in, so tests never depend on the real model,
and a failing one falls back to equal text for the rest of the run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services import markers
from app.services.turns import neutralize_mentions

logger = logging.getLogger(__name__)

#: ``similar(a, b)`` → cosine similarity, -1..1. May raise; a raise means
#: similarity is unavailable for the rest of the run.
Similar = Callable[[str, str], float]

#: How alike two texts must be to count as one, by embedding. Deliberately
#: high: folding two different points into one hides a disagreement, while
#: leaving a near-duplicate unfolded costs one extra line.
SIMILARITY_THRESHOLD = 0.92

#: Bounds on what one run keeps. Over a bound is dropped with a note.
PER_REPLY = 12
ITEM_CHARS = 600
PER_RUN = 80

#: A reply with text and no label, kept whole so it is never lost.
STATEMENT = "statement"

#: Point types a check is expected to cover.
CHECKABLE = ("objective", "constraint", "deliverable")

#: How each kind of point is headed when the frame is shown to people.
HEADINGS = {
    "objective": "What it's for",
    "constraint": "Constraints",
    "assumption": "Assumptions",
    "sub_goal": "Parts of the work",
    "deliverable": "What gets delivered",
    "out_of_scope": "Out of scope",
    STATEMENT: "Said without a label",
}


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean(text: str) -> str:
    """Text as it is stored: no marker of its own, no mention that would summon."""
    return markers.defang(neutralize_mentions(text.strip()))


@dataclass
class Point:
    id: str
    type: str
    text: str
    authors: list[str]
    about: str = ""

    @property
    def support(self) -> int:
        return len(self.authors)


@dataclass
class Check:
    text: str
    covers: list[str]
    owner: str


@dataclass
class Frame:
    """What a run has gathered so far."""

    points: list[Point] = field(default_factory=list)
    #: normalised word → (the word as first written, {member: meaning}). A
    #: member's later meaning for a word replaces its earlier one.
    terms: dict[str, tuple[str, dict[str, str]]] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    #: Members who answered any step that gathers pieces.
    answered: set[str] = field(default_factory=set)
    #: ``False`` once similarity failed or was never there: equal text only.
    similarity: bool = True
    #: The frame-round cap was reached while points were still being added.
    capped: bool = False
    #: Pairs already compared, so a round never asks the model twice.
    _seen: dict[tuple[str, str], float] = field(default_factory=dict)

    def items(self) -> int:
        return (
            len(self.points)
            + sum(len(meanings) for _w, meanings in self.terms.values())
            + len(self.checks)
        )

    def alike(self, a: str, b: str, similar: Similar | None) -> bool:
        """Whether two texts say the same thing: equal, or similar enough."""
        if _norm(a) == _norm(b):
            return True
        if similar is None or not self.similarity:
            return False
        pair = (a, b) if a <= b else (b, a)
        if pair not in self._seen:
            try:
                self._seen[pair] = float(similar(*pair))
            except Exception:
                logger.warning("similarity unavailable; folding equal text only", exc_info=True)
                self.similarity = False
                return False
        return self._seen[pair] >= SIMILARITY_THRESHOLD


@dataclass
class Folded:
    """What one round added, and anything a bound dropped."""

    added: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Members whose reply carried at least one labelled piece.
    labelled: set[str] = field(default_factory=set)


def _cut(text: str, who: str, notes: list[str]) -> str:
    if len(text) <= ITEM_CHARS:
        return text
    notes.append(f"Cut a point from {who} to {ITEM_CHARS} characters.")
    return text[:ITEM_CHARS].rstrip() + "…"


def _add_point(
    frame: Frame, kind: str, text: str, about: str, who: str, similar: Similar | None
) -> str | None:
    """Fold one point in; the new point's id, or ``None`` when it joined one."""
    for point in frame.points:
        if point.type == kind and frame.alike(point.text, text, similar):
            if who not in point.authors:
                point.authors.append(who)
            if about and not point.about:
                point.about = about
            return None
    point = Point(id=f"p{len(frame.points) + 1}", type=kind, text=text, authors=[who], about=about)
    frame.points.append(point)
    return point.id


def fold(
    frame: Frame,
    replies: list[tuple[str, list[dict[str, Any]]]],
    *,
    similar: Similar | None,
) -> Folded:
    """Fold each member's labelled pieces into the frame, in the order given
    (the conductor gives cast order, whatever order the replies arrived in)."""
    out = Folded()
    for who, pieces in replies:
        frame.answered.add(who)
        if pieces:
            out.labelled.add(who)
        if len(pieces) > PER_REPLY:
            out.notes.append(
                f"Kept the first {PER_REPLY} of {len(pieces)} labelled pieces from {who}."
            )
            pieces = pieces[:PER_REPLY]
        for piece in pieces:
            if frame.items() >= PER_RUN:
                out.notes.append(f"This run keeps {PER_RUN} pieces; dropped the rest from {who}.")
                break
            text = _cut(_clean(piece["text"]), who, out.notes)
            label = piece["label"]
            if label == "term":
                word = _clean(piece["term"])
                shown, meanings = frame.terms.get(_norm(word), (word, {}))
                meanings[who] = text
                frame.terms[_norm(word)] = (shown, meanings)
            elif label == "check":
                if not any(_norm(c.text) == _norm(text) for c in frame.checks):
                    frame.checks.append(Check(text=text, covers=list(piece["covers"]), owner=who))
            else:
                about = _clean(piece.get("about") or "")
                added = _add_point(frame, label, text, about, who, similar)
                if added:
                    out.added.append(added)
    return out


def add_statement(frame: Frame, who: str, text: str, *, similar: Similar | None) -> Folded:
    """Keep a reply that carried no label as one unlabelled statement by ``who``."""
    out = Folded()
    text = _cut(_clean(text), who, out.notes)
    if text and frame.items() < PER_RUN:
        added = _add_point(frame, STATEMENT, text, "", who, similar)
        if added:
            out.added.append(added)
    return out


# ── the words ────────────────────────────────────────────────────────────────


def senses(frame: Frame, word: str, similar: Similar | None) -> list[tuple[str, list[str]]]:
    """A word's meanings grouped by sense: ``[(meaning, [members])]``, in cast
    order of first use. More than one group means the word is contested."""
    _shown, meanings = frame.terms[word]
    groups: list[tuple[str, list[str]]] = []
    for who, meaning in meanings.items():
        for text, members in groups:
            if frame.alike(text, meaning, similar):
                members.append(who)
                break
        else:
            groups.append((meaning, [who]))
    return groups


def contested(frame: Frame, similar: Similar | None) -> list[str]:
    """The words members are using in different senses, in the order first written."""
    return [word for word in frame.terms if len(senses(frame, word, similar)) > 1]


def contested_members(frame: Frame, cast: list[str], similar: Similar | None) -> list[str]:
    """Everyone who gave a meaning to a contested word, in cast order."""
    involved = {who for word in contested(frame, similar) for who in frame.terms[word][1]}
    return [h for h in cast if h in involved]


# ── what the prompts show ─────────────────────────────────────────────────────


def show_points(frame: Frame, cast: list[str]) -> str:
    if not frame.points:
        return "(nothing yet)"
    total = len(cast)
    return "\n".join(
        f"{p.id} ({p.type.replace('_', ' ')}, stated by {p.support} of {total}): {p.text}"
        for p in frame.points
    )


def show_terms(frame: Frame, similar: Similar | None) -> str:
    if not frame.terms:
        return "(no words defined yet)"
    lines = []
    for word, (shown, _meanings) in frame.terms.items():
        groups = senses(frame, word, similar)
        if len(groups) == 1:
            lines.append(f"{shown}: {groups[0][0]} ({', '.join(groups[0][1])})")
            continue
        lines.append(f"{shown} is used in different senses:")
        lines += [f"  {', '.join(members)}: {text}" for text, members in groups]
    return "\n".join(lines)


def show_checks(frame: Frame) -> str:
    if not frame.checks:
        return "(no checks yet)"
    return "\n".join(
        f"{c.text} ({c.owner}{'; covers ' + ', '.join(c.covers) if c.covers else ''})"
        for c in frame.checks
    )


# ── the contract ──────────────────────────────────────────────────────────────


def _flag(kind: str, text: str, **about: Any) -> dict[str, Any]:
    return {"kind": kind, "text": text, **about}


#: How many point ids an open item names before it gives a count instead. An
#: open item is one line a person reads, so a run where most points were stated
#: once says that once rather than once per point.
LISTED = 8


def _ids(ids: list[str]) -> str:
    return (
        ", ".join(ids)
        if len(ids) <= LISTED
        else f"{', '.join(ids[:LISTED])} and {len(ids) - LISTED} more"
    )


def contract(
    frame: Frame,
    *,
    cast: list[str],
    ask: str,
    task: str,
    title: str,
    similar: Similar | None,
) -> dict[str, Any]:
    """Everything the frame holds, with every problem flagged, as plain data."""
    total = len(cast)
    flags: list[dict[str, Any]] = []
    by_about: dict[tuple[str, str], list[Point]] = {}
    for p in frame.points:
        if p.about:
            by_about.setdefault((p.type, _norm(p.about)), []).append(p)
    # Different things said about one subject, by more than one person: one
    # person's two points about pricing are detail, not a disagreement.
    clashes = [
        group
        for group in by_about.values()
        if len(group) > 1 and len({a for p in group for a in p.authors}) > 1
    ]
    conflicting = {p.id for group in clashes for p in group}
    covered = {pid for c in frame.checks for pid in c.covers}
    unchecked = [p.id for p in frame.points if p.type in CHECKABLE and p.id not in covered]
    single = [p.id for p in frame.points if p.support == 1 and total > 1]
    if single:
        text = (
            f"Every point was stated by only one person ({len(single)} points)"
            if len(single) == len(frame.points) and len(single) > 1
            else f"Only one person said this: {_ids(single)}"
        )
        flags.append(_flag("single", text, points=single))

    points = []
    for p in frame.points:
        mine = []
        if p.id in single:
            mine.append("single")
        if p.id in conflicting:
            mine.append("conflict")
        if p.id in unchecked:
            mine.append("unchecked")
        entry: dict[str, Any] = {
            "id": p.id,
            "type": p.type,
            "text": p.text,
            "support": p.support,
            "authors": list(p.authors),
            "flags": mine,
        }
        if p.about:
            entry["about"] = p.about
        points.append(entry)
    for group in clashes:
        flags.append(
            _flag(
                "conflict",
                f"People said different things about {group[0].about}: "
                f"{_ids([p.id for p in group])}",
                points=[p.id for p in group],
            )
        )

    glossary = []
    for word, (shown, _meanings) in frame.terms.items():
        groups = senses(frame, word, similar)
        status = "agreed" if len(groups) == 1 else "contested"
        glossary.append(
            {
                "term": shown,
                "status": status,
                "meanings": [{"text": text, "members": members} for text, members in groups],
            }
        )
        if status == "contested":
            flags.append(
                _flag("ambiguous", f"A word used in different senses: {shown}", term=shown)
            )

    if unchecked:
        flags.append(
            _flag(
                "unchecked",
                f"Nothing checks this yet: {_ids(unchecked)}",
                points=unchecked,
            )
        )
    quiet = [h for h in cast if h not in frame.answered]
    if quiet:
        flags.append(_flag("quiet_member", f"No answer from {', '.join(quiet)}", members=quiet))
    if frame.capped:
        flags.append(
            _flag("frame_cap_reached", "Points were still being added when the rounds ran out")
        )
    if not frame.similarity:
        flags.append(
            _flag(
                "similarity_unavailable",
                "Only identical wording was merged; similar points may be listed twice",
            )
        )
    return {
        "task": task,
        "title": title,
        "ask": ask,
        "cast": list(cast),
        "points": points,
        "glossary": glossary,
        "checks": [{"text": c.text, "covers": c.covers, "owner": c.owner} for c in frame.checks],
        "unchecked": unchecked,
        "flags": flags,
    }


def counts(made: dict[str, Any]) -> dict[str, Any]:
    """The numbers a person reads about a contract, and the app draws."""
    points = made.get("points") or []
    return {
        "points": len(points),
        "shared": sum(1 for p in points if p.get("support", 0) > 1),
        "contested": sum(1 for g in made.get("glossary") or [] if g.get("status") == "contested"),
        "checks": len(made.get("checks") or []),
        "flagged": len(made.get("flags") or []),
        "quiet": next(
            (f.get("members", []) for f in made.get("flags") or [] if f["kind"] == "quiet_member"),
            [],
        ),
    }


def render(made: dict[str, Any]) -> str:
    """The contract as the markdown a person reads in the memory."""
    total = len(made.get("cast") or [])
    lines = [f"# Shared summary: {made.get('title') or made.get('task') or 'this task'}", ""]
    if made.get("ask"):
        lines += [f"The ask: {made['ask']}", ""]
    if made.get("cast"):
        lines += [f"Worked out by {', '.join(made['cast'])}.", ""]
    points = made.get("points") or []
    for kind in (*markers.POINT_TYPES, STATEMENT):
        mine = [p for p in points if p["type"] == kind]
        if not mine:
            continue
        lines += [f"## {HEADINGS[kind]}", ""]
        for p in mine:
            by = ", ".join(p["authors"])
            lines.append(f"- **{p['id']}** {p['text']} (stated by {p['support']} of {total}: {by})")
        lines.append("")
    glossary = made.get("glossary") or []
    if glossary:
        lines += ["## Words", ""]
        for g in glossary:
            if g["status"] == "agreed":
                (only,) = g["meanings"]
                lines.append(f"- **{g['term']}**: {only['text']} ({', '.join(only['members'])})")
                continue
            lines.append(f"- **{g['term']}** is used in different senses:")
            lines += [f"  - {', '.join(m['members'])}: {m['text']}" for m in g["meanings"]]
        lines.append("")
    checks = made.get("checks") or []
    if checks:
        lines += ["## How we'll check", ""]
        for c in checks:
            covers = f"; covers {', '.join(c['covers'])}" if c["covers"] else ""
            lines.append(f"- {c['text']} ({c['owner']}{covers})")
        lines.append("")
    lines += ["## Open items", ""]
    flags = made.get("flags") or []
    lines += [f"- {f['text']}" for f in flags] or ["- None."]
    return "\n".join(lines).rstrip() + "\n"


def embedding_similarity() -> Similar | None:
    """Similarity by the hub's own embedding model, or ``None`` when it has none
    worth using (stub vectors in CI say nothing about meaning)."""
    from app.services import embedding
    from app.services.search_index import cosine_similarity

    if embedding._STUB:
        return None
    vectors: dict[str, list[float]] = {}

    def similar(a: str, b: str) -> float:
        for text in (a, b):
            if text not in vectors:
                vectors[text] = embedding.embed_text(text)
        return cosine_similarity(vectors[a], vectors[b])

    return similar


_ID_RE = re.compile(r"^p\d+$")


def known_covers(frame: Frame) -> None:
    """Drop ids a check names that are no point in the frame, so coverage is never
    claimed for something that does not exist."""
    ids = {p.id for p in frame.points}
    for check in frame.checks:
        check.covers = [c for c in check.covers if _ID_RE.match(c) and c in ids]
