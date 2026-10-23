# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a reply to a conductor step has to say, and what the hub read from it.

Each step that asks members for something asks for it in one shape, shown in
its prompt: two anchor ratings, one option, a rating with a reason for every
option, labelled pieces, key terms, or a stance. When a member's reply is
recorded, the hub reads it against the step's shape with the same parsers the
conductor collects with, and puts what it read on the message as ``reply``, so
a surface draws the values rather than the prose. A reply that lacks something
says what (``missing``) and is marked ``parsed: false``; nothing is guessed.

The idea of a defined message structure for each step comes from the IoC
ACCORD and CONCORD protocols (ioc-project.github.io/cognition-protocols/);
these shapes are Mycelium's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services import markers
from app.services import select as choosing

if TYPE_CHECKING:
    from app.services.protocols import Step

#: The payload key a member's reply to a conductor step carries what was read
#: under, beside the prose.
REPLY_KEY = "reply"

#: Which shape each kind of step asks for.
_BY_COLLECT = {
    "anchors": "anchors",
    "options": "option",
    "scores": "ratings",
    "pieces": "pieces",
    "keywords": "terms",
}


def shape_of(step: Step) -> str | None:
    """The shape a reply to ``step`` takes, or ``None`` when it asks for none."""
    if step.collect in _BY_COLLECT:
        return _BY_COLLECT[step.collect]
    if step.needs == "stance":
        return "stance"
    return None


def _text(content: dict[str, Any]) -> str:
    text = content.get("content")
    return text if isinstance(text, str) else ""


def read(
    shape: str,
    content: dict[str, Any],
    *,
    labels: list[str] | tuple[str, ...] = (),
    wanted: list[str] | tuple[str, ...] = (),
    anchor: tuple[int, int] | None = None,
    key_terms: list[str] | None = None,
) -> dict[str, Any]:
    """What a reply recorded as ``content`` says, read as ``shape``.

    ``labels`` are the options on the table and ``wanted`` the ones this step
    asks to be rated; ``anchor`` is the member's own (bad, ideal) ratings;
    ``key_terms`` are the run's terms, for pieces written as plain lines.
    """
    out: dict[str, Any] = {"shape": shape}
    missing: list[str] = []
    text = _text(content)
    if shape == "anchors":
        said = markers.anchor_lines(text)
        given = {k: {"score": v, "reason": why} for k, (v, why) in said.items() if k in ("bad", "ideal")}
        if given:
            out["anchors"] = given
        missing += [f"a rating for {end}" for end in ("bad", "ideal") if end not in said]
        if "bad" in said and "ideal" in said and said["ideal"][0] <= said["bad"][0]:
            missing.append("an ideal rated above the bad outcome")
    elif shape == "option":
        option, why = markers.split_why(markers.MARKER_RE.sub("", text).strip())
        if option:
            out["option"] = {"text": option, "why": why}
        else:
            missing.append("the option")
    elif shape == "ratings":
        given = {k: v for k, v in markers.rated_of(content).items() if k in labels}
        ratings = []
        for label in labels:
            if label not in given:
                continue
            score, why = given[label]
            entry: dict[str, Any] = {"option": label, "score": score, "reason": why}
            if anchor is not None:
                entry["toward_ideal"] = round(choosing.placed(score, anchor) * 100)
            ratings.append(entry)
        if ratings:
            out["ratings"] = ratings
        if anchor is not None:
            out["bad"], out["ideal"] = anchor
        for label in wanted:
            if label not in given:
                missing.append(f"a rating for {label}")
            elif not given[label][1]:
                missing.append(f"a reason for {label}")
    elif shape == "pieces":
        pieces = markers.pieces_of(content, key_terms)
        if pieces:
            out["pieces"] = pieces
        elif markers.MARKER_RE.sub("", text).strip():
            missing.append("a labelled line")
    elif shape == "terms":
        # Naming none is an answer: the prompt asks a member to say so.
        out["terms"] = markers.term_names(text)
    elif shape == "stance":
        stance = markers.stance_of(content)
        if stance:
            out["stance"] = stance
        else:
            missing.append("a stance")
    out["parsed"] = not missing
    if missing:
        out["missing"] = missing
    return out


def attach(content: dict[str, Any], reply: dict[str, Any]) -> None:
    """Put ``reply`` on a recorded message's payload, beside what's there."""
    l9 = content.get("l9")
    if not isinstance(l9, dict):
        return
    payload = l9.setdefault("payload", {})
    if not isinstance(payload, dict):
        return
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
        payload["data"] = data
    data[REPLY_KEY] = reply
