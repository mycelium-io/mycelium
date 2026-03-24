"""Options generation — component 2 of the semantic negotiation pipeline.

Ported from ioc-cfn-cognitive-agents/semantic-negotiation-agent/app/agent/options_generation.py.
Upstream used raw LLM string parsing; replaced with LiteLLM tool use for guaranteed
structured output. Three strategies preserved: LLM-only, memory+LLM, agent query.
Memory and agent query strategies retain stub hooks — replace with real MAS memory
and agent query calls when ready.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_LLM_ONLY_PROMPT = """Read the context thoroughly - it contains the premise or mission of the application and the current conversation. From it, infer the kind of negotiation at hand: negotiation may be about (a) different interpretations of a word or phrase, or (b) negotiating the amount or quantity of an entity. Deduce which applies based on the context.

For each negotiable entity below, suggest 2-4 concrete options that agents could negotiate over. If interpretation-heavy, suggest distinct plausible meanings. If quantity-heavy, suggest plausible quantities or levels. Use the sentence and context to keep options relevant.

Sentence: "{sentence}"
Context: {context}

Negotiable entities:
{terms_blob}"""

_MEMORY_LLM_PROMPT = """Read the context thoroughly - it contains the premise or mission and the current conversation. Using the sentence, context, and the memory/preferences below, suggest 2-4 concrete options for each negotiable entity. Prefer options that align with stated preferences where relevant.

Sentence: "{sentence}"
Context: {context}

Memory / preferences:
{memory_blob}

Negotiable entities:
{terms_blob}"""

_TOOL = {
    "type": "function",
    "function": {
        "name": "record_options",
        "description": "Record the generated options for each negotiable entity",
        "parameters": {
            "type": "object",
            "properties": {
                "options_per_term": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "term": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                            },
                        },
                        "required": ["term", "options"],
                    },
                },
            },
            "required": ["options_per_term"],
        },
    },
}


def _mock_memory_lookup(sentence: str, context: str | None = None) -> dict[str, Any]:
    """Stub for MAS memory lookup. Replace with real Mycelium memory query."""
    return {
        "preferences": "No preferences recorded.",
        "recent_context": context or "general",
        "domain_hints": context or "general",
    }


def _mock_agent_interpretation_query(
    negotiable_entities: list[str],
    sentence: str,
    context: str | None = None,
    sender_id: str | None = None,
) -> dict[str, list[str]]:
    """Stub for querying sending agents for their interpretations. Replace with real agent calls."""
    return {term: [f"interpretation of '{term}' (mock)"] for term in negotiable_entities}


def _call_llm(prompt: str) -> dict[str, Any]:
    """Call LiteLLM with tool use, return parsed arguments dict."""
    import time

    import litellm

    from app.config import settings
    from app.services.metrics import record_llm_call

    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "record_options"}},
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    t0 = time.monotonic()
    try:
        resp = litellm.completion(**kwargs)
    except Exception:
        record_llm_call(operation="negotiation_options", model=settings.LLM_MODEL, error=True)
        raise
    elapsed_ms = (time.monotonic() - t0) * 1000

    usage = getattr(resp, "usage", None)
    input_tok = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
    output_tok = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
    hidden = getattr(resp, "_hidden_params", {})
    cost = hidden.get("response_cost", 0.0) or 0.0
    record_llm_call(
        operation="negotiation_options",
        model=settings.LLM_MODEL,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cost_usd=cost,
        duration_ms=elapsed_ms,
    )

    tool_calls = resp.choices[0].message.tool_calls
    if not tool_calls:
        return {}
    raw = tool_calls[0].function.arguments
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        logger.warning("options_generation: could not parse tool arguments: %s", raw)
        return {}


def _extract_by_term(data: dict[str, Any], entities: list[str]) -> dict[str, list[str]]:
    """Map tool output back to {term: [options]} preserving entity order."""
    by_term: dict[str, list[str]] = {}
    for item in data.get("options_per_term", []):
        if isinstance(item, dict) and item.get("term"):
            by_term[str(item["term"]).strip()] = [str(o) for o in item.get("options", [])]
    # Preserve original order; fall back to empty list for any missing term
    return {e: by_term.get(e, []) for e in entities}


def _format_terms(entities: list[str]) -> str:
    return "\n".join(f'- "{e}"' for e in entities) if entities else "(none)"


class OptionsGeneration:
    """Generates candidate options per negotiable entity.

    Three strategies:
    1. LLM-only (default): LLM proposes options using context and its own judgment.
    2. Memory + LLM: Fetch memory/preferences (stub), pass to LLM.
    3. Agent query: Ask sending agents for their interpretations (stub).
    """

    def generate_options_llm_only(
        self,
        negotiable_entities: list[str],
        sentence: str,
        context: str | None = None,
    ) -> dict[str, list[str]]:
        if not negotiable_entities:
            return {}
        prompt = _LLM_ONLY_PROMPT.format(
            sentence=sentence,
            context=context or "not specified",
            terms_blob=_format_terms(negotiable_entities),
        )
        return _extract_by_term(_call_llm(prompt), negotiable_entities)

    def generate_options_with_memory(
        self,
        negotiable_entities: list[str],
        sentence: str,
        context: str | None = None,
    ) -> dict[str, list[str]]:
        if not negotiable_entities:
            return {}
        memory_data = _mock_memory_lookup(sentence, context)
        prompt = _MEMORY_LLM_PROMPT.format(
            sentence=sentence,
            context=context or "not specified",
            memory_blob=json.dumps(memory_data, indent=2),
            terms_blob=_format_terms(negotiable_entities),
        )
        return _extract_by_term(_call_llm(prompt), negotiable_entities)

    def generate_options_from_agents(
        self,
        negotiable_entities: list[str],
        sentence: str,
        context: str | None = None,
        sender_id: str | None = None,
    ) -> dict[str, list[str]]:
        if not negotiable_entities:
            return {}
        return _mock_agent_interpretation_query(negotiable_entities, sentence, context, sender_id)

    def generate_options(
        self,
        negotiable_entities: list[str],
        sentence: str,
        context: str | None = None,
    ) -> dict[str, list[str]]:
        """Generate options using LLM-only strategy (default)."""
        return self.generate_options_llm_only(negotiable_entities, sentence, context)
