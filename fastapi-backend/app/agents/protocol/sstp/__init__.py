"""
sstp — Pydantic v2 models for the Semantic State Transfer Protocol (SSTP)
"""
from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

__version__: str = "1.0.0"

from ._base import (
    EncodingType,
    LogicalClock,
    MergeStrategy,
    Origin,
    PayloadRef,
    PayloadRefType,
    PolicyLabels,
    PropagationType,
    ProtocolType,
    Provenance,
    SemanticContext,
    SensitivityType,
    _STBaseMessage,
)

from .commit import CommitMessage
from .delegation import DelegationMessage
from .evidence_bundle import EvidenceBundleMessage
from .intent import IntentMessage
from .knowledge import KnowledgeMessage
from .memory_delta import MemoryDeltaMessage
from .negotiate import SSTPNegotiateMessage, NegotiateSemanticContext
from .query import QueryMessage

STPMessage = Annotated[
    Union[
        IntentMessage,
        DelegationMessage,
        KnowledgeMessage,
        QueryMessage,
        CommitMessage,
        MemoryDeltaMessage,
        EvidenceBundleMessage,
        SSTPNegotiateMessage,
    ],
    Field(discriminator="kind"),
]

__all__ = [
    "__version__",
    "ProtocolType", "SensitivityType", "PropagationType", "EncodingType",
    "MergeStrategy", "PayloadRefType",
    "Origin", "SemanticContext", "PolicyLabels", "Provenance", "PayloadRef",
    "LogicalClock", "_STBaseMessage",
    "IntentMessage", "DelegationMessage", "KnowledgeMessage", "QueryMessage",
    "CommitMessage", "MemoryDeltaMessage", "EvidenceBundleMessage",
    "NegotiateSemanticContext", "SSTPNegotiateMessage",
    "STPMessage",
]
