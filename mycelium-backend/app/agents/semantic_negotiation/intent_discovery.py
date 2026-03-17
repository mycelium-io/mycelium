"""Intent discovery — component 1 of the semantic negotiation pipeline.

Given a context (e.g. a conversation transcript or a structured state object)
this component identifies the negotiable issues between parties and returns
them as a list of issue identifiers.

Current implementation: stub returning hardcoded example issues.
Replace :meth:`IntentDiscovery.discover` with a real LLM/NLP-backed
implementation when ready.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_STUB_ISSUES: list[str] = ["budget", "timeline", "scope", "quality"]


class IntentDiscovery:
    """Extracts negotiation issues from a shared context.

    Args:
        context: Any structured or unstructured object describing the current
            state of the interaction (e.g. agent memories, conversation history).
    """

    def __init__(self, context: Any = None) -> None:
        self.context = context

    def discover(self, content_text: str | None = None) -> list[str]:
        """Analyse ``content_text`` (or ``self.context``) and return negotiable issue ids.

        .. note::
            **Stub implementation** — always returns
            ``["budget", "timeline", "scope", "quality"]`` regardless of input.
            Replace this method body with a real LLM/NLP-backed implementation.

        Args:
            content_text: Free-text description of the mission or negotiation goal.

        Returns:
            Ordered list of issue identifier strings.
        """
        logger.debug(
            "IntentDiscovery.discover() — stub; content_text=%r returning %s",
            content_text,
            _STUB_ISSUES,
        )
        return list(_STUB_ISSUES)
