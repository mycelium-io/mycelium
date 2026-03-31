# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Intent discovery — component 1 of the semantic negotiation pipeline.

Ported from ioc-cfn-cognitive-agents/semantic-negotiation-agent/app/agent/intent_discovery.py.
Upstream used raw LLM string parsing; replaced with LiteLLM tool use for guaranteed
structured output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """You are the issue identifier facilitating potential negotiations in a multi-agent application.

Read the context thoroughly — it contains the mission or premise of the application and the current conversation. Use that perspective to decide what counts as a negotiable issue: only flag terms or entities that, in this mission and conversation, could reasonably need negotiation between agents.

Then read the sentence and identify all such issues (negotiable entities). These include:
- Concrete items or resources the user mentions as needs, preferences, or priorities.
- Ambiguous terms: words whose meaning can vary by context or person.

For each, provide brief reasoning for why it could need negotiation.

Sentence: "{sentence}"
Context: {context}"""


@dataclass
class IntentDiscoveryResult:
    """Structured result of intent/entity extraction."""

    sentence: str
    context: str | None = None
    negotiable_entities: list[str] = field(default_factory=list)


class IntentDiscovery:
    """Extracts negotiable entities from a sentence using LiteLLM tool use."""

    _TOOL: ClassVar[dict] = {
        "type": "function",
        "function": {
            "name": "record_negotiable_entities",
            "description": "Record the negotiable entities identified in the sentence",
            "parameters": {
                "type": "object",
                "properties": {
                    "negotiable_entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "term": {
                                    "type": "string",
                                    "description": "Exact phrase from the sentence",
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "Why this needs negotiation",
                                },
                            },
                            "required": ["term", "reasoning"],
                        },
                    },
                },
                "required": ["negotiable_entities"],
            },
        },
    }

    def discover(
        self,
        sentence: str,
        context: str | None = None,
    ) -> list[str]:
        """Extract negotiable entities from a sentence.

        Returns a list of entity term strings.
        """
        import litellm

        from app.config import settings

        context_str = context or "not specified"
        prompt = _EXTRACT_PROMPT.format(sentence=sentence, context=context_str)

        kwargs: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [self._TOOL],
            "tool_choice": {"type": "function", "function": {"name": "record_negotiable_entities"}},
        }
        if settings.LLM_API_KEY:
            kwargs["api_key"] = settings.LLM_API_KEY
        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL

        resp = litellm.completion(**kwargs)
        tool_calls = resp.choices[0].message.tool_calls
        if not tool_calls:
            logger.warning("intent_discovery: no tool call in response")
            return []

        raw = tool_calls[0].function.arguments
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            logger.warning("intent_discovery: could not parse tool arguments: %s", raw)
            return []

        return [
            str(e["term"]).strip()
            for e in data.get("negotiable_entities", [])
            if isinstance(e, dict) and e.get("term")
        ]
