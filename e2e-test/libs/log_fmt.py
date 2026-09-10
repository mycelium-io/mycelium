"""Shared helpers for logging command dispatch and results.

Used by every module that shells out (:mod:`libs.host_exec`,
:mod:`libs.mycelium_cli`) or calls the backend HTTP API
(:mod:`libs.mycelium_api`) so the pyATS TaskLog carries a consistent,
readable record of what was run and what came back: an ``INFO``-level
one-liner for the dispatch and the result summary (default-visible),
plus a ``DEBUG``-level dump of the full body/output, pretty-printed
when it parses as JSON.
"""

from __future__ import annotations

import json
from typing import Any

_MAX_LEN = 8000


def pretty(value: Any) -> str:
    """Render *value* for a debug log, pretty-printing JSON when possible.

    Accepts already-parsed objects (dict/list) or raw strings (CLI
    stdout, HTTP bodies) that may or may not be JSON. Falls back to
    ``str(value)`` for anything that can't be serialized. Long output
    is truncated so one giant blob can't drown the rest of the log.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "(empty)"
        if text[0] in "{[":
            try:
                value = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return _truncate(value)
        else:
            return _truncate(value)

    try:
        return _truncate(json.dumps(value, indent=2, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return _truncate(str(value))


def _truncate(text: str, limit: int = _MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} chars total]"
