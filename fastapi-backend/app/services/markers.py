# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The position marker an agent may end a reply with.

``[[mycelium: confidence=0.85 stance=accept]]`` is the one convention a
participant speaks: how sure it is, and whether it can live with what is on
the table. A flow that asks for ratings reads them from the same marker, one
capital letter per option: ``[[mycelium: A=82 B=41]]``. The reply route lifts the fields onto the L9 payload (so the
aligner scores them) and strips the marker from the prose; the conductor
reads a stance back off either place, since a human writing into a thread
through the message route leaves the marker in the text.
"""

from __future__ import annotations

import re
from typing import Any

MARKER_RE = re.compile(r"\[\[\s*mycelium\s*:(.*?)\]\]", re.IGNORECASE | re.DOTALL)

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


def parse_marker(text: str) -> tuple[dict[str, Any], str]:
    """Lift ``confidence``/``stance`` and option ratings out of any marker in
    ``text``; strip it.

    ``[[mycelium: A=82 B=41 stance=accept]]``: a key that is one capital letter
    is a rating of that option (``payload["scores"]``); ``a=82`` is not. Returns
    the payload fields found and the prose without the marker. A text that is
    nothing but a marker keeps its original form rather than becoming empty.
    """
    payload: dict[str, Any] = {}
    scores: dict[str, int] = {}
    for match in MARKER_RE.finditer(text):
        for key, raw in re.findall(r"(\w+)\s*=\s*(\S+)", match.group(1)):
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
    clean = MARKER_RE.sub("", text).strip() or text.strip()
    return payload, clean


def scores_of(content: dict[str, Any]) -> dict[str, int]:
    """The option ratings a transcript record states, or ``{}``.

    Read like :func:`stance_of`: the L9 payload first (the reply route lifted
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

    The L9 payload's ``action`` wins — that is where the reply route put a
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
