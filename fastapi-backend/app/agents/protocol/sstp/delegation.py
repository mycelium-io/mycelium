"""sstp/delegation.py — DelegationMessage kind."""
from __future__ import annotations

from typing import Literal

from ._base import _STBaseMessage


class DelegationMessage(_STBaseMessage):
    """Transfer of a task or authority to another agent."""

    kind: Literal["delegation"]
