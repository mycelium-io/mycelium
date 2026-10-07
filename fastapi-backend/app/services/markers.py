# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The markers a member writes into a reply.

``[[mycelium: confidence=0.85 stance=accept]]`` is the one convention a
participant speaks: how sure it is, and whether it can live with what is on
the table. A flow that asks for ratings reads them from the same marker, one
capital letter per option: ``[[mycelium: A=82 B=41]]``. The reply route lifts the fields onto the packet payload (so the
aligner scores them) and strips the marker from the prose; the conductor
reads a stance back off either place, since a human writing into a thread
through the message route leaves the marker in the text.

A marker can also **label** the text that follows it, up to the next marker
or a blank line, so code can tell what kind of thing that text is without
anyone writing JSON:

    [[mycelium: constraint]] Refunds above 5000 need a person's approval.
    [[mycelium: term=handoff]] Passing the account to the next owner.
    [[mycelium: check covers=p2,p4]] Finance signs off the limits first.

A point is one of :data:`POINT_TYPES` (and may say what it is ``about``),
``term=<word>`` is the writer's meaning of that word, and ``check`` is how
points would be confirmed. The label is lifted onto the payload as
``pieces``; the labelled text stays in the prose where it was written.
"""

from __future__ import annotations

import re
from typing import Any

MARKER_RE = re.compile(r"\[\[\s*mycelium\s*:(.*?)\]\]", re.IGNORECASE | re.DOTALL)

#: A marker and the spaces after it, so a label at the start of a line leaves
#: the line's text where it was rather than indented by one space.
_STRIP_RE = re.compile(MARKER_RE.pattern + r"[ \t]*", re.IGNORECASE | re.DOTALL)

#: ``key=value`` inside a marker; a value may be quoted to hold spaces.
_PAIR_RE = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")

#: What a point can be, in the order a summary lists them.
POINT_TYPES = (
    "objective",
    "constraint",
    "assumption",
    "sub_goal",
    "deliverable",
    "out_of_scope",
)

#: A point's id as a check names it: ``p3``.
_POINT_ID = re.compile(r"^p\d+$")

#: Where labelled text stops when no marker follows it.
_BLANK_LINE = re.compile(r"\n[ \t]*\n")

STANCE_TO_ACTION = {
    "accept": "accept",
    "agree": "accept",
    "yes": "accept",
    "approve": "accept",
    "reject": "reject",
    "block": "reject",
    "no": "reject",
}


#: An option's rating: one capital letter naming the option, a whole number 0-100.
RATING_KEY = re.compile(r"^[A-Z]$")


def _rating(raw: str) -> int | None:
    """A whole number 0-100, or ``None``. Out of range is dropped, never clamped.

    A trailing comma is how a list is written (``A=82, B=41``), so it is not
    part of the number."""
    raw = raw.rstrip(",;")
    if not re.fullmatch(r"\d{1,3}", raw):
        return None
    value = int(raw)
    return value if value <= 100 else None


def _pairs(body: str) -> list[tuple[str, str]]:
    """``(key, value)`` for each ``key=value`` in a marker's body, quotes removed."""
    return [
        (key, quoted if quoted is not None else (single if single is not None else bare))
        for key, quoted, single, bare in (
            (m.group(1), m.group(2), m.group(3), m.group(4)) for m in _PAIR_RE.finditer(body)
        )
    ]


def _words(body: str) -> list[str]:
    """The bare words in a marker's body (what is not a ``key=value``), normalised."""
    rest = _PAIR_RE.sub(" ", body)
    return [w.strip().lower().replace("-", "_") for w in re.split(r"[\s,]+", rest) if w.strip()]


def _label(body: str) -> dict[str, Any] | None:
    """What a marker labels the text after it as, or ``None`` when it labels nothing."""
    pairs = {k.lower(): v for k, v in _pairs(body)}
    words = _words(body)
    point = next((w for w in words if w in POINT_TYPES), None)
    if point is not None:
        label: dict[str, Any] = {"label": point}
        about = (pairs.get("about") or "").strip()
        if about:
            label["about"] = about
        return label
    term = (pairs.get("term") or "").strip()
    if term:
        return {"label": "term", "term": term}
    if "check" in words:
        covers = [c.strip().lower() for c in (pairs.get("covers") or "").split(",") if c.strip()]
        # ``covers=p2, p4`` written with a space leaves ``p4`` as a bare word.
        covers += [w for w in words if _POINT_ID.match(w) and w not in covers]
        return {"label": "check", "covers": covers}
    return None


def labelled(text: str) -> list[dict[str, Any]]:
    """Every piece of ``text`` a marker labels, in the order written.

    A piece is the text after a labelling marker, up to the next marker or a
    blank line. A label with no text after it labels nothing and is dropped.
    """
    found = list(MARKER_RE.finditer(text))
    pieces: list[dict[str, Any]] = []
    for i, match in enumerate(found):
        label = _label(match.group(1))
        if label is None:
            continue
        stop = found[i + 1].start() if i + 1 < len(found) else len(text)
        body = text[match.end() : stop]
        blank = _BLANK_LINE.search(body)
        if blank:
            body = body[: blank.start()]
        body = body.strip()
        if body:
            pieces.append(label | {"text": body})
    return pieces


#: The opening of a marker, where it can't be one: what is defanged in stored text.
_OPENING_RE = re.compile(r"\[\[(?=\s*mycelium\s*:)", re.IGNORECASE)


def defang(text: str) -> str:
    """``text`` with every marker opening broken, so text a member wrote can be
    echoed into a later prompt without speaking a marker of its own."""
    return _OPENING_RE.sub("[ [", text)


def parse_marker(text: str) -> tuple[dict[str, Any], str]:
    """Lift ``confidence``/``stance``, option ratings and labelled pieces out of
    the markers in ``text``; strip the markers.

    ``[[mycelium: A=82 B=41 stance=accept]]``: a key that is one capital letter
    is a rating of that option (``payload["scores"]``); ``a=82`` is not. A
    marker that labels text (``[[mycelium: constraint]] ...``) adds a piece to
    ``payload["pieces"]`` and leaves the text in the prose. Returns the payload
    fields found and the prose without the markers. A text that is nothing but
    a marker keeps its original form rather than becoming empty.
    """
    payload: dict[str, Any] = {}
    scores: dict[str, int] = {}
    for match in MARKER_RE.finditer(text):
        for key, raw in _pairs(match.group(1)):
            # Ratings are matched before anything is lowercased: `A` is an
            # option, `a` is nothing.
            if RATING_KEY.match(key):
                value = _rating(raw)
                if value is not None:
                    scores[key] = value
                continue
            k = key.lower()
            if k == "confidence":
                try:
                    val = float(raw)
                except ValueError:
                    continue
                if 0.0 <= val <= 1.0:
                    payload["confidence"] = val
            elif k in ("stance", "action"):
                action = STANCE_TO_ACTION.get(raw.lower())
                if action:
                    payload["action"] = action
    if scores:
        payload["scores"] = scores
    pieces = labelled(text)
    if pieces:
        payload["pieces"] = pieces
    clean = _STRIP_RE.sub("", text).strip() or text.strip()
    return payload, clean


def _a_piece(raw: Any) -> dict[str, Any] | None:
    """A lifted piece as it should look, or ``None`` for anything malformed."""
    if not isinstance(raw, dict):
        return None
    label, text = raw.get("label"), raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    piece: dict[str, Any] = {"label": label, "text": text.strip()}
    if label in POINT_TYPES:
        about = raw.get("about")
        if isinstance(about, str) and about.strip():
            piece["about"] = about.strip()
        return piece
    if label == "term":
        term = raw.get("term")
        return piece | {"term": term.strip()} if isinstance(term, str) and term.strip() else None
    if label == "check":
        covers = raw.get("covers")
        ids = (
            [c.strip().lower() for c in covers if isinstance(c, str) and c.strip()]
            if isinstance(covers, list)
            else []
        )
        return piece | {"covers": ids}
    return None


def pieces_of(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The labelled pieces a transcript record states, in the order written.

    Read like :func:`scores_of`: the packet payload first (the reply route lifted
    the labels there), then the markers still in the prose (a person typing
    into the thread). Only well-formed pieces count.
    """
    payload = ((content.get("l9") or {}).get("payload") or {}).get("data") or {}
    lifted = payload.get("pieces") if isinstance(payload, dict) else None
    if isinstance(lifted, list):
        found = [p for p in (_a_piece(raw) for raw in lifted) if p is not None]
        if found:
            return found
    text = content.get("content")
    if not isinstance(text, str):
        return []
    return labelled(text)


def scores_of(content: dict[str, Any]) -> dict[str, int]:
    """The option ratings a transcript record states, or ``{}``.

    Read like :func:`stance_of`: the packet payload first (the reply route lifted
    the marker there), then a marker still in the prose. Only well-formed
    ratings count; nothing is guessed from what the prose says.
    """
    payload = ((content.get("l9") or {}).get("payload") or {}).get("data") or {}
    lifted = payload.get("scores") if isinstance(payload, dict) else None
    if isinstance(lifted, dict):
        found = {
            k: v
            for k, v in lifted.items()
            if isinstance(k, str)
            and RATING_KEY.match(k)
            and isinstance(v, int)
            and not isinstance(v, bool)
            and 0 <= v <= 100
        }
        if found:
            return found
    text = content.get("content")
    if not isinstance(text, str):
        return {}
    parsed, _clean = parse_marker(text)
    return dict(parsed.get("scores") or {})


def stance_of(content: dict[str, Any]) -> str | None:
    """``accept`` / ``reject`` as a transcript record states it, or ``None``.

    The packet payload's ``action`` wins — that is where the reply route put a
    marker it stripped. A marker still in the prose (a human's write through
    the message route) is read next. Anything else stated no stance.
    """
    payload = ((content.get("l9") or {}).get("payload") or {}).get("data") or {}
    action = payload.get("action") if isinstance(payload, dict) else None
    if action in ("accept", "reject"):
        return action
    text = content.get("content")
    if not isinstance(text, str):
        return None
    found, _clean = parse_marker(text)
    action = found.get("action")
    return action if action in ("accept", "reject") else None
