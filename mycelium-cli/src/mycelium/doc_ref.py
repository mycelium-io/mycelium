"""
Decorator for registering CLI commands in the HTML docs reference.

Usage:
    from mycelium.doc_ref import doc_ref

    @doc_ref(
        usage="mycelium room create <name> --mode <async|sync> [--trigger threshold:N]",
        desc="Create a new coordination room. Mode is required.",
        group="room",
    )
    @app.command()
    def create(...): ...

Then run `docs/generate_cli_reference.py` to update the HTML docs site.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Global registry — collected at import time, read by the generator.
_registry: list[DocEntry] = []


@dataclass
class DocEntry:
    usage: str
    desc: str
    group: str


def doc_ref(
    usage: str,
    desc: str,
    group: str = "other",
) -> Callable:
    """Register a CLI command for the HTML docs reference.

    Args:
        usage: The full command signature shown in docs.
        desc: One-line description for the docs page. May contain HTML.
        group: Command group name (e.g. "room", "memory"). Use "other" for top-level.
    """

    def decorator(fn: Callable) -> Callable:
        _registry.append(DocEntry(usage=usage, desc=desc, group=group))
        return fn

    return decorator


def get_registry() -> list[DocEntry]:
    """Return all registered doc entries, in definition order."""
    return list(_registry)
