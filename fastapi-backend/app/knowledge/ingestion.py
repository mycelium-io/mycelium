"""
Two-stage LLM extraction service for OpenClaw turns.

Uses litellm (same provider/model/key/base_url config as the rest of Mycelium)
so any configured LLM backend works — Anthropic, OpenAI, litellm proxy, etc.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from app.config import settings
from app.knowledge import service as kg_service
from app.knowledge.prompts import get_concept_prompt, get_relationship_prompt
from app.knowledge.schemas import KnowledgeGraphStoreRequest

logger = logging.getLogger(__name__)

_TOOL_CALL_KEYS = ("id", "name", "input", "result")


def _litellm_call(system: str, user: str, tools: list[dict], tool_name: str) -> dict:
    """Call litellm with tool_choice forced to tool_name. Returns the tool input dict."""
    import litellm

    kwargs: dict = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "max_tokens": 4096,
        "temperature": 0,
    }
    if settings.LLM_API_KEY:
        kwargs["api_key"] = settings.LLM_API_KEY
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    try:
        resp = litellm.completion(**kwargs)
    except litellm.AuthenticationError:
        logger.warning(
            "LLM authentication failed for model %s. "
            "Check LLM_API_KEY in ~/.mycelium/.env",
            settings.LLM_MODEL,
        )
        raise RuntimeError(
            f"LLM authentication failed for {settings.LLM_MODEL}. "
            "Check LLM_API_KEY in ~/.mycelium/.env"
        )
    for choice in resp.choices:
        msg = choice.message
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function.name == tool_name:
                    return json.loads(tc.function.arguments)
    return {}


class IngestionService:
    """Two-stage LLM extraction: openclaw turns → concepts + relationships → AgensGraph."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        # api_key / model kept for backwards compat but ignored — settings are used directly
        pass

    @staticmethod
    def _generate_id(text: str) -> str:
        # MD5 used for deterministic node ID generation only — not security-sensitive
        return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    # ------------------------------------------------------------------
    # Payload builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_compact_payload(records: list[dict]) -> list[dict]:
        """Flatten openclaw records into compact turn dicts for LLM consumption.

        Each record may be a full openclaw object (with a ``turns`` list) or
        an individual turn dict.  For every turn we emit a flat dict with
        ``userMessage``, ``thinking``, ``toolCalls`` (stripped to id/name/input/result),
        and ``response``.
        """

        def _flatten_turn(turn: dict) -> dict:
            entry: dict = {}
            for key in ("userMessage", "thinking", "response"):
                val = turn.get(key)
                if val is not None:
                    entry[key] = val
            raw_calls = turn.get("toolCalls")
            if raw_calls:
                entry["toolCalls"] = [
                    {k: tc[k] for k in _TOOL_CALL_KEYS if k in tc} for tc in raw_calls
                ]
            return entry

        extracted: list[dict] = []
        for record in records:
            turns = record.get("turns") if isinstance(record.get("turns"), list) else None
            if turns is not None:
                for turn in turns:
                    flat = _flatten_turn(turn)
                    if flat:
                        extracted.append(flat)
            else:
                flat = _flatten_turn(record)
                if flat:
                    extracted.append(flat)
        return extracted

    # ------------------------------------------------------------------
    # Stage 1: concept extraction
    # ------------------------------------------------------------------

    def _llm_extract_concepts(self, compact_payload: list[dict]) -> list[dict]:
        """Use litellm tool use to extract structured concepts from the payload."""
        tool = {
            "name": "record_concepts",
            "description": "Record the extracted concepts",
            "input_schema": {
                "type": "object",
                "properties": {
                    "concepts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "type", "description"],
                        },
                    },
                },
                "required": ["concepts"],
            },
        }
        result = _litellm_call(
            system=get_concept_prompt("openclaw"),
            user=json.dumps(compact_payload),
            tools=[tool],
            tool_name="record_concepts",
        )
        return result.get("concepts", [])

    # ------------------------------------------------------------------
    # Stage 2: relationship extraction
    # ------------------------------------------------------------------

    def _llm_extract_relationships(
        self, concepts: list[dict], compact_payload: list[dict]
    ) -> list[dict]:
        """Use litellm tool use to extract structured relationships between concepts."""
        tool = {
            "name": "record_relationships",
            "description": "Record the extracted relationships",
            "input_schema": {
                "type": "object",
                "properties": {
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "relationship": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["source", "target", "relationship", "description"],
                        },
                    },
                },
                "required": ["relationships"],
            },
        }
        result = _litellm_call(
            system=get_relationship_prompt("openclaw"),
            user=json.dumps({"concepts": concepts, "records": compact_payload}),
            tools=[tool],
            tool_name="record_relationships",
        )
        return result.get("relationships", [])

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def ingest(
        self,
        records: list[dict],
        workspace_id: str,
        mas_id: str,
        agent_id: str | None = None,
        knowledge_service: object = None,
    ) -> dict:
        """Run the full ingestion pipeline.

        1. Build compact payload from openclaw records.
        2. LLM extract concepts (stage 1).
        3. LLM extract relationships (stage 2).
        4. Convert to KnowledgeGraphStoreRequest and store in AgensGraph.
        5. Return {graph_name, concepts_extracted, relations_extracted}.
        """
        compact_payload = self._build_compact_payload(records)
        logger.info("ingest: %d records -> %d compact turns", len(records), len(compact_payload))

        graph_name = "graph_" + mas_id.replace("-", "_")

        if not compact_payload or not settings.LLM_API_KEY:
            return {"graph_name": graph_name, "concepts_extracted": 0, "relations_extracted": 0}

        # Run sync LLM calls in thread to avoid blocking the event loop
        raw_concepts: list[dict] = await asyncio.to_thread(
            self._llm_extract_concepts, compact_payload
        )
        logger.info("ingest: %d concepts extracted", len(raw_concepts))

        raw_relationships: list[dict] = await asyncio.to_thread(
            self._llm_extract_relationships, raw_concepts, compact_payload
        )
        logger.info("ingest: %d relationships extracted", len(raw_relationships))

        # Map to KnowledgeGraphStoreRequest
        concepts_out = [
            {
                "id": self._generate_id(c.get("name", "")),
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "attributes": {"concept_type": c.get("type", "unknown")},
            }
            for c in raw_concepts
        ]

        concept_ids = {c["id"] for c in concepts_out}
        relations_out = []
        for r in raw_relationships:
            src = r.get("source", "")
            tgt = r.get("target", "")
            rel_label = r.get("relationship", "INTERACTS_WITH")
            src_id = self._generate_id(src)
            tgt_id = self._generate_id(tgt)
            if src_id not in concept_ids or tgt_id not in concept_ids:
                continue
            relations_out.append(
                {
                    "id": self._generate_id(f"{src_id}_{tgt_id}_{rel_label}"),
                    "node_ids": [src_id, tgt_id],
                    "relation": rel_label,
                    "attributes": {
                        "source_name": src,
                        "target_name": tgt,
                        "summarized_context": r.get("description", ""),
                    },
                }
            )

        store_req = KnowledgeGraphStoreRequest(
            mas_id=mas_id,
            wksp_id=workspace_id,
            records={"concepts": concepts_out, "relations": relations_out},
        )

        ks = knowledge_service or kg_service
        response = await asyncio.to_thread(ks.create_graph_store, store_req)

        if response.status.value != "success":
            logger.warning("ingest: graph store failed: %s", response.message)

        return {
            "graph_name": graph_name,
            "concepts_extracted": len(concepts_out),
            "relations_extracted": len(relations_out),
        }
