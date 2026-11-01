# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Make ``NO_PROXY`` readable by httpx before anything opens a connection.

httpx refuses to build a client at all when ``NO_PROXY`` holds an IPv6
address in brackets (``[fd00::1]``, ``[::1]:8000``) or an IPv6 range
(``fd00::/8``), forms other tools accept and that a VM's network setup
writes. Every command then fails before it reaches the hub. httpx matches a
bare IPv6 address, so the brackets (and a port after them) come off; a range
it can't match in any form, so it goes, with a note on stderr.
"""

from __future__ import annotations

import os
import sys

_NAMES = ("NO_PROXY", "no_proxy")


def readable(value: str) -> tuple[str, list[str]]:
    """``value`` as httpx reads it, and the entries left out."""
    kept: list[str] = []
    dropped: list[str] = []
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if entry.startswith("[") and "]" in entry:
            entry = entry[1 : entry.index("]")]
        if "/" in entry and ":" in entry and "://" not in entry:
            dropped.append(raw.strip())
            continue
        kept.append(entry)
    return ",".join(kept), dropped


def repair() -> None:
    """Rewrite ``NO_PROXY``/``no_proxy`` in this process's environment, if needed."""
    for name in _NAMES:
        value = os.environ.get(name)
        if not value:
            continue
        fixed, dropped = readable(value)
        if fixed == value:
            continue
        os.environ[name] = fixed
        if dropped:
            print(  # noqa: T201 - a note on stderr, before any command runs
                f"mycelium: ignoring {', '.join(dropped)} in {name}: "
                "the HTTP client can't match an IPv6 range",
                file=sys.stderr,
            )
