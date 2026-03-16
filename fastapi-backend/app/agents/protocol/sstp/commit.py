"""sstp/commit.py — CommitMessage kind."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import LogicalClock, MergeStrategy, _STBaseMessage


class CommitMessage(_STBaseMessage):
    """
    A state-commit message.

    All general optional fields that are optional on other kinds become
    **required** here (per the spec's Commit-Specific Extensions section).
    """

    kind: Literal["commit"]

    # Fields that are optional on other kinds but REQUIRED for commit
    state_object_id: str  # override → required (no None default)
    parent_ids: list[str]  # override → required (no empty default)
    logical_clock: LogicalClock  # override → required (no None default)
    merge_strategy: MergeStrategy
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    risk_score: float
    ttl_seconds: int
