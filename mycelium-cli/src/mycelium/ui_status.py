# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
Shared presentation helpers for ``mycelium status`` and ``mycelium doctor``.

Both commands render a list of named checks with a status icon, a short
message, and optional detail lines. They historically diverged in format
(status used colored labels with multi-line detail sprawl; doctor used
flat icon-prefixed lines). This module is the single source of truth so
they stay visually aligned.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import typer

# ── Status → icon / color ────────────────────────────────────────────────────
#
# "ok" / "warning" / "error" are the canonical three; everything else is an
# alias that maps to one of them for colour purposes. Keeps callers from
# having to pre-normalize backend-specific statuses (``auth_error``,
# ``not_configured``, etc.) before calling print_check.

_STATUS_ALIAS = {
    "ok": "ok",
    "degraded": "warning",
    "warning": "warning",
    "not_configured": "warning",
    "unchecked": "warning",
    "not_cached": "warning",
    "stub": "warning",
    "invalid_format": "warning",
    "auth_error": "warning",
    "missing_extras": "error",
    "bad_model": "error",
    "unreachable": "error",
    "error": "error",
    "info": "info",
}

_STATUS_ICON = {
    "ok": "\x1b[32m✓\x1b[0m",
    "warning": "\x1b[33m~\x1b[0m",
    "error": "\x1b[31m✗\x1b[0m",
    "info": " ",
}

_STATUS_COLOR = {
    "ok": typer.colors.GREEN,
    "warning": typer.colors.YELLOW,
    "error": typer.colors.RED,
    "info": typer.colors.WHITE,
}


def _bucket(status: str) -> str:
    """Normalize any status string to one of ok / warning / error / info."""
    return _STATUS_ALIAS.get(status, "warning")


# ── Check result ──────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warning" | "error" | "info" | any alias above
    message: str
    details: list[str] = field(default_factory=list)
    fix_label: str = ""
    fix_fn: Callable[[], None] | None = None


# ── Layout constants ──────────────────────────────────────────────────────────

INDENT = "  "
NAME_WIDTH = 22  # chars for the check-name column after the icon
DETAIL_INDENT = " " * (len(INDENT) + 2 + NAME_WIDTH)  # align with message column


# ── Output helpers ────────────────────────────────────────────────────────────


def print_title(text: str, subtitle: str | None = None) -> None:
    """Top-of-output title. Bold, no leading newline (caller owns spacing)."""
    typer.secho(text, bold=True)
    if subtitle:
        typer.echo(f"{INDENT}{subtitle}")


def print_section(title: str) -> None:
    """Blank line + bold section header."""
    typer.echo("")
    typer.secho(title, bold=True)


def print_check(result: CheckResult, name_width: int = NAME_WIDTH) -> None:
    """Render one check: icon, aligned name, colored message, details beneath."""
    bucket = _bucket(result.status)
    icon = _STATUS_ICON[bucket]
    color = _STATUS_COLOR[bucket]
    typer.secho(
        f"{INDENT}{icon} {result.name:<{name_width}s}{result.message}",
        fg=color,
    )
    for detail in result.details:
        typer.echo(f"{DETAIL_INDENT}{detail}")


def print_kv(key: str, value: str, name_width: int = NAME_WIDTH) -> None:
    """Informational key/value line (no icon, no color) — for Configuration-style blocks."""
    typer.echo(f"{INDENT}  {key:<{name_width}s}{value}")


def print_verdict(status: str, message: str) -> None:
    """Final one-line summary with icon + color. Blank line above for separation.

    ``status`` is any string accepted by ``print_check`` — "ok", "warning",
    "error", or a backend alias ("auth_error", "missing_extras", etc).
    Warning-only doctor runs should verdict with "warning" (yellow ~),
    not "error" (red ✗), to avoid over-claiming severity.
    """
    bucket = _bucket(status)
    icon = _STATUS_ICON[bucket]
    color = _STATUS_COLOR[bucket]
    typer.echo("")
    typer.secho(f"{INDENT}{icon} {message}", fg=color)
