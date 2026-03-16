"""sstp/memory_delta.py — MemoryDeltaMessage kind."""
from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class MemoryDeltaMessage(_STBaseMessage):
    """An incremental update to a shared memory / knowledge graph."""

    kind: Literal["memory_delta"]
