# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The markers a member writes into a reply.

``[[mycelium: confidence=0.85 stance=accept]]`` is the one convention a
participant speaks: how sure it is, and whether it can live with what is on
the table. The reply route lifts the fields onto the message payload and
strips the marker from the prose; the conductor reads a stance back off
either place, since a human writing into a thread through the message route
leaves the marker in the text.
"""

from __future__ import annotations

import re
from typing import Any

MARKER_RE = re.compile(r"\[\[\s*mycelium\s*:(.*?)\]\]", re.IGNORECASE | re.DOTALL)

#: A marker and the spaces after it, so a marker at the start of a line leaves
#: the line's text where it was rather than indented by one space.
_STRIP_RE = re.compile(MARKER_RE.pattern + r"[ \t]*", re.IGNORECASE | re.DOTALL)

#: ``key=value`` inside a marker; a value may be quoted to hold spaces.
_PAIR_RE = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")

STANCE_TO_ACTION = {
    "accept": "accept",
    "agree": "accept",
    "yes": "accept",
    "approve": "accept",
    "reject": "reject",
    "block": "reject",
    "no": "reject",
}


def _pairs(body: str) -> list[tuple[str, str]]:
    """``(key, value)`` for each ``key=value`` in a marker's body, quotes removed."""
    return [
        (key, quoted if quoted is not None else (single if single is not None else bare))
        for key, quoted, single, bare in (
            (m.group(1), m.group(2), m.group(3), m.group(4)) for m in _PAIR_RE.finditer(body)
        )
    ]


#: The opening of a marker, where it can't be one: what is defanged in stored text.
_OPENING_RE = re.compile(r"\[\[(?=\s*mycelium\s*:)", re.IGNORECASE)


def defang(text: str) -> str:
    """``text`` with every marker opening broken, so text a member wrote can be
    echoed into a later prompt without speaking a marker of its own."""
    return _OPENING_RE.sub("[ [", text)


def parse_marker(text: str) -> tuple[dict[str, Any], str]:
    """Lift ``confidence``/``stance`` out of the markers in ``text``; strip the markers.

    Returns the payload fields found and the prose without the markers. A text
    that is nothing but a marker keeps its original form rather than becoming
    empty.
    """
    payload: dict[str, Any] = {}
    for match in MARKER_RE.finditer(text):
        for key, raw in _pairs(match.group(1)):
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
    clean = _STRIP_RE.sub("", text).strip() or text.strip()
    return payload, clean


def stance_of(content: dict[str, Any]) -> str | None:
    """``accept`` / ``reject`` as a transcript record states it, or ``None``.

    The message payload's ``action`` wins — that is where the reply route put a
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
