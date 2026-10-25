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

#: How alike two texts must be to count as one point, by embedding, with
#: nothing said about it. Deliberately high: folding two different points into
#: one hides a disagreement. A text is compared with every text already folded
#: into a point, so three members saying one thing three ways land together.
SIMILARITY_THRESHOLD = 0.92
#: How alike a text must be to join a point all the same, kept beside the
#: others and flagged for people to check they agree. In a real run, one point
#: said three ways scored 0.84-0.94 pairwise, all but one pair at 0.886 or more,
#: while two different points on the same task scored up to 0.834. Embeddings
#: don't see negation ("rejects a negative tip" against "accepts a negative tip"
#: scores 0.88), so a fold under the first bar is never taken as agreement.
REWORDED_THRESHOLD = 0.86
#: How alike two meanings of a key term must be to count as one sense. Lower
#: than for points: members define a term in their own words, with their own
#: example, so one sense said four ways scored 0.85-0.92 in real runs, while
#: two senses (a list price against a contract template) scored 0.53-0.80.
MEANING_THRESHOLD = 0.85

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
    #: Every wording folded into it as ``(member, text)``, ``text`` first: a new
    #: text is compared with each.
    said: list[tuple[str, str]] = field(default_factory=list)
    #: A wording joined it under :data:`SIMILARITY_THRESHOLD`: the contract lists
    #: every wording and flags it for people to check they agree.
    reworded: bool = False
    #: Points folded into it because a member said they're the same, as
    #: ``(member, point id)``: who said so is recorded beside who said it.
    matched: list[tuple[str, str]] = field(default_factory=list)

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
    #: How many point ids were ever given, so an id stays unique after a
    #: point is folded into another; and where each folded point went.
    minted: int = 0
    folded_into: dict[str, str] = field(default_factory=dict)
    #: Pairs already compared, so a round never asks the model twice.
    _seen: dict[tuple[str, str], float] = field(default_factory=dict)

    def items(self) -> int:
        return (
            len(self.points)
            + sum(len(meanings) for _w, meanings in self.terms.values())
            + len(self.checks)
        )

    def alike(
        self, a: str, b: str, similar: Similar | None, threshold: float = SIMILARITY_THRESHOLD
    ) -> bool:
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
        return self._seen[pair] >= threshold


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
    """Fold one point in; the new point's id, or ``None`` when it joined one.

    It joins the first point it says the same as, and failing that the first
    one it says nearly the same as, which is then flagged as reworded."""
    same = [p for p in frame.points if p.type == kind]
    joined = next((p for p in same if any(frame.alike(t, text, similar) for _w, t in p.said)), None)
    if joined is None:
        joined = next(
            (
                p
                for p in same
                if any(frame.alike(t, text, similar, REWORDED_THRESHOLD) for _w, t in p.said)
            ),
            None,
        )
        if joined is not None:
            joined.reworded = True
    if joined is not None:
        if who not in joined.authors:
            joined.authors.append(who)
        if all(_norm(t) != _norm(text) for _w, t in joined.said):
            joined.said.append((who, text))
        if about and not joined.about:
            joined.about = about
        return None
    frame.minted += 1
    point = Point(
        id=f"p{frame.minted}",
        type=kind,
        text=text,
        authors=[who],
        about=about,
        said=[(who, text)],
    )
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
                    covers = list(dict.fromkeys(_current(frame, c) for c in piece["covers"]))
                    frame.checks.append(Check(text=text, covers=covers, owner=who))
            elif label == "same":
                fold_same(frame, list(piece["points"]), who, out.notes)
            else:
                about = _clean(piece.get("about") or "")
                added = _add_point(frame, label, text, about, who, similar)
                if added:
                    out.added.append(added)
    return out


def _current(frame: Frame, pid: str) -> str:
    """Where point ``pid`` is now: itself, or the point it was folded into."""
    seen: set[str] = set()
    while pid in frame.folded_into and pid not in seen:
        seen.add(pid)
        pid = frame.folded_into[pid]
    return pid


def fold_same(frame: Frame, ids: list[str], who: str, notes: list[str]) -> None:
    """Fold every point ``ids`` names into the last, because ``who`` said they
    say the same thing. Whoever stated any of them supports the one left, every
    wording is kept, and who said they're the same is recorded on it. An id
    that names no point is left out, with a note."""
    by_id = {p.id: p for p in frame.points}
    named = [_current(frame, pid) for pid in ids]
    missing = [pid for pid, now in zip(ids, named, strict=True) if now not in by_id]
    if missing:
        notes.append(f"{who} said {', '.join(missing)} matched a point, but there's no such point.")
    named = [pid for pid in dict.fromkeys(named) if pid in by_id]
    if len(named) < 2:
        return
    into = by_id[named[-1]]
    for pid in named[:-1]:
        point = by_id[pid]
        for author in point.authors:
            if author not in into.authors:
                into.authors.append(author)
        for said in point.said:
            if all(_norm(t) != _norm(said[1]) for _w, t in into.said):
                into.said.append(said)
        into.matched += [*point.matched, (who, pid)]
        into.reworded = into.reworded or point.reworded
        if point.about and not into.about:
            into.about = point.about
        frame.points.remove(point)
        frame.folded_into[pid] = into.id
        for check in frame.checks:
            check.covers = list(dict.fromkeys(_current(frame, c) for c in check.covers))


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
    order of first use. More than one group means the word is contested.

    A meaning joins a sense when it says the same as any meaning already in
    it, so four members saying one thing four ways land together. A meaning
    that says the same as two senses joins them into one: the order members
    answered in doesn't decide how many senses there are."""
    _shown, meanings = frame.terms[word]
    groups: list[tuple[str, list[str]]] = []
    for who, meaning in meanings.items():
        matching = [
            g
            for g in groups
            if any(frame.alike(meanings[m], meaning, similar, MEANING_THRESHOLD) for m in g[1])
        ]
        if not matching:
            groups.append((meaning, [who]))
            continue
        first = matching[0]
        for other in matching[1:]:
            first[1].extend(other[1])
            groups.remove(other)
        first[1].append(who)
    return groups


def contested(frame: Frame, similar: Similar | None) -> list[str]:
    """The words members are using in different senses, in the order first written."""
    return [word for word in frame.terms if len(senses(frame, word, similar)) > 1]


def contested_members(frame: Frame, cast: list[str], similar: Similar | None) -> list[str]:
    """Everyone who gave a meaning to a contested word, in cast order."""
    involved = {who for word in contested(frame, similar) for who in frame.terms[word][1]}
    return [h for h in cast if h in involved]


# ── what the prompts show ─────────────────────────────────────────────────────


def _matched(matched: list[tuple[str, str]]) -> str:
    """``p6 (b said it's the same), p11 (c said it's the same)``."""
    return ", ".join(f"{pid} ({who} said it's the same)" for who, pid in matched)


def show_points(frame: Frame, cast: list[str]) -> str:
    if not frame.points:
        return "(nothing yet)"
    total = len(cast)
    lines = []
    for p in frame.points:
        kind = p.type.replace("_", " ")
        if not p.reworded:
            lines.append(f"{p.id} ({kind}, stated by {p.support} of {total}): {p.text}")
            if p.matched:
                lines.append(f"  (folded in: {_matched(p.matched)})")
            continue
        lines.append(f"{p.id} ({kind}) said in different words. Check they agree:")
        lines += [f"  {who}: {text}" for who, text in p.said]
    return "\n".join(lines)


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
    reworded = [p.id for p in frame.points if p.reworded]
    if reworded:
        flags.append(
            _flag(
                "reworded",
                f"Said in different words. Check they agree: {_ids(reworded)}",
                points=reworded,
            )
        )

    points = []
    for p in frame.points:
        mine = []
        if p.id in single:
            mine.append("single")
        if p.id in conflicting:
            mine.append("conflict")
        if p.id in unchecked:
            mine.append("unchecked")
        if p.reworded:
            mine.append("reworded")
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
        if p.reworded or p.matched:
            entry["wordings"] = [{"member": who, "text": text} for who, text in p.said]
        if p.matched:
            # Who said a point folded in says the same, as support records who stated it.
            entry["matched_by"] = list(dict.fromkeys(who for who, _pid in p.matched))
            entry["folded"] = [{"point": pid, "by": who} for who, pid in p.matched]
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
            wordings = p.get("wordings") or []
            if "reworded" in (p.get("flags") or []):
                lines.append(f"- **{p['id']}** said in different words by {by}. Check they agree:")
                lines += [f"  - {w['member']}: {w['text']}" for w in wordings]
                continue
            lines.append(f"- **{p['id']}** {p['text']} (stated by {p['support']} of {total}: {by})")
            folded = p.get("folded") or []
            if folded:
                said = ", ".join(f"{f['point']} ({f['by']})" for f in folded)
                lines.append(f"  - Folded in because members said they're the same: {said}")
                lines += [f"  - {w['member']}: {w['text']}" for w in wordings[1:]]
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
        covers = dict.fromkeys(_current(frame, c) for c in check.covers if _ID_RE.match(c))
        check.covers = [c for c in covers if c in ids]
