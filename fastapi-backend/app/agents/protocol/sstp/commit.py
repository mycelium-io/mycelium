# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""sstp/commit.py — SSTPCommitMessage kind."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ._base import EncodingType, LogicalClock, MergeStrategy, _STBaseMessage


class NegotiateCommitSemanticContext(BaseModel):
    """
    Semantic context for ``kind='commit'`` messages that finalize a negotiation.

    Carries the schema identity of the commit plus the ``final_agreement``
    so consumers can inspect the outcome directly from the envelope without
    having to parse the full ``payload``.
    """

    schema_id: str = "urn:ioc:schema:negotiate:commit:v1"
    schema_version: str = "1.0"
    encoding: EncodingType = "json"
    session_id: str
    final_agreement: list[dict[str, Any]] | None = Field(
        None,
        description=(
            "Agreed option per issue. Each entry is "
            "{'issue_id': str, 'chosen_option': str}. "
            "None when negotiation ended without agreement."
        ),
    )


class SSTPCommitMessage(_STBaseMessage):
    """
    A state-commit message.

    All general optional fields that are optional on other kinds become
    **required** here (per the spec's Commit-Specific Extensions section).
    """

    kind: Literal["commit"]

    # Override: typed semantic context carrying the final agreement
    semantic_context: NegotiateCommitSemanticContext  # type: ignore[override]

    # Fields that are optional on other kinds but REQUIRED for commit
    state_object_id: str  # override → required (no None default)
    parent_ids: list[str]  # override → required (no empty default)
    logical_clock: LogicalClock  # override → required (no None default)
    merge_strategy: MergeStrategy
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    risk_score: float
    ttl_seconds: int
