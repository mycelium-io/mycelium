# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a reply to a conductor step has to say, and what the hub read from it.

A step that names a reply schema (``Step.reply``) asks for its answer in that
schema, shown in its prompt. When a member's reply is recorded, the hub reads it
against the schema with the parsers here, the same ones the conductor collects
with, and puts what it read on the message as ``reply``, so a surface draws the
values rather than the prose. A reply that lacks something says what
(``missing``) and is marked ``parsed: false``. Nothing is guessed.

The schemas are CONCORD's, as its specification writes them (the IoC team's
ACCORD and CONCORD, ioc-project.github.io/cognition-protocols/): the reply
elements, their fields, and what makes one valid.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from app.services import select as choosing

if TYPE_CHECKING:
    from app.services.protocols import Step

#: The payload key a member's reply to a conductor step carries what was read
#: under, beside the prose.
REPLY_KEY = "reply"

#: Each reply schema, and the phase of its protocol it answers.
SCHEMAS: dict[str, tuple[str, str]] = {
    "concord-anchor-reply": ("concord", "ANCHOR"),
    "concord-candidate-reply": ("concord", "SEED"),
    "concord-score-reply": ("concord", "SCORE"),
}


def schema_of(step: Step) -> str | None:
    """The reply schema ``step`` asks for, or ``None`` when it names none."""
    return step.reply if step.reply in SCHEMAS else None


# ── finding the element in what a member wrote ────────────────────────────────

_FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)\n\s*```", re.DOTALL)
#: A ``<`` that opens no tag, and an ``&`` that starts no entity: prose inside
#: an element writes them freely ("cost < 5", "R&D"), and XML can't.
_BARE_LT = re.compile(r"<(?![a-zA-Z/?!])")
_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)")


def _element(text: str, name: str) -> ET.Element | None:
    """The last ``<name>…</name>`` in ``text``, parsed; ``None`` when there is
    none or it isn't well formed. A code fence around it is fine."""
    for body in (*_FENCE.findall(text), text):
        found = list(re.finditer(rf"<{name}\b[^>]*>.*?</{name}\s*>", body, re.DOTALL))
        if not found:
            continue
        raw = found[-1].group(0)
        raw = _BARE_AMP.sub("&amp;", _BARE_LT.sub("&lt;", raw))
        try:
            return ET.fromstring(raw)
        except ET.ParseError:
            return None
    return None


def _text_of(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _raw(el: ET.Element | None) -> float | None:
    """A raw 0-100 rating, or ``None`` when it isn't one: out of range is
    refused, never clamped."""
    try:
        value = float(_text_of(el))
    except ValueError:
        return None
    return value if math.isfinite(value) and 0 <= value <= 100 else None


# ── reading a reply ───────────────────────────────────────────────────────────


def read(
    schema: str,
    content: dict[str, Any],
    *,
    candidates: list[str] | tuple[str, ...] = (),
    anchor: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """What a reply recorded as ``content`` says, read as ``schema``.

    ``candidates`` are the ids a score reply has to rate, and ``anchor`` the
    member's own ``(raw_reject, raw_ideal)``, for the normalized scores.
    """
    protocol, phase = SCHEMAS[schema]
    out: dict[str, Any] = {"protocol": protocol, "phase": phase, "schema": schema}
    text = content.get("content")
    text = text if isinstance(text, str) else ""
    el = _element(text, schema)
    missing: list[str] = []
    value: dict[str, Any] = {}
    if el is None:
        missing.append(f"a <{schema}> element")
    elif schema == "concord-anchor-reply":
        reject, ideal = _raw(el.find("raw_reject")), _raw(el.find("raw_ideal"))
        if reject is None:
            missing.append("raw_reject, a number from 0 to 100")
        if ideal is None:
            missing.append("raw_ideal, a number from 0 to 100")
        if reject is not None and ideal is not None:
            value = {"raw_reject": reject, "raw_ideal": ideal}
            if ideal <= reject:
                missing.append("raw_ideal above raw_reject")
        if note := _text_of(el.find("note")):
            value["note"] = note
    elif schema == "concord-candidate-reply":
        candidate, rationale = _text_of(el.find("candidate")), _text_of(el.find("rationale"))
        if candidate:
            value["candidate"] = candidate
        else:
            missing.append("a candidate")
        if rationale:
            value["rationale"] = rationale
        else:
            missing.append("a rationale")
    elif schema == "concord-score-reply":
        given: dict[str, tuple[float | None, str]] = {}
        for score in el.findall("score"):
            cid = (score.get("candidate_id") or "").strip()
            if cid:
                given[cid] = (_raw(score.find("raw")), _text_of(score.find("reasoning")))
        scores = []
        for cid in candidates:
            raw, reasoning = given.get(cid, (None, ""))
            if cid not in given:
                missing.append(f"a score for {cid}")
                continue
            if raw is None:
                missing.append(f"a raw 0-100 score for {cid}")
            if not reasoning:
                missing.append(f"reasoning for {cid}")
            if raw is None:
                continue
            entry: dict[str, Any] = {"candidate_id": cid, "raw": raw, "reasoning": reasoning}
            if anchor is not None:
                entry["normalized"] = round(choosing.placed(raw, anchor), 4)
            scores.append(entry)
        value["scores"] = scores
    out["parsed"] = not missing
    if missing:
        out["missing"] = missing
    out["value"] = value
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
