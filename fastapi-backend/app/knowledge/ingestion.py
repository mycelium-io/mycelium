"""
Two-stage Anthropic LLM extraction service for OpenClaw turns.

Ported from cfn/ioc-cfn-cognitive-agents/ingestion-cognitive-agent/app/agent/service.py
(ConceptRelationshipExtractionService), adapted to use Anthropic tool use instead of
AzureOpenAI structured output.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING

from app.knowledge import service as kg_service
from app.knowledge.prompts import get_concept_prompt, get_relationship_prompt
from app.knowledge.schemas import KnowledgeGraphStoreRequest

if TYPE_CHECKING:
    import anthropic as anthropic_module

logger = logging.getLogger(__name__)

_TOOL_CALL_KEYS = ("id", "name", "input", "result")


class IngestionService:
    """Two-stage LLM extraction: openclaw turns → concepts + relationships → AgensGraph."""

    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._client: anthropic_module.Anthropic | None = None

    def _get_client(self) -> anthropic_module.Anthropic | None:
        if self._client is not None:
            return self._client
        if not self.api_key:
            return None
        try:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            logger.warning("anthropic package not installed — LLM extraction unavailable")
            return None
        else:
            return self._client
        return None

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
        """Use Anthropic tool use to extract structured concepts from the payload."""
        client = self._get_client()
        if client is None:
            return []

        tool: dict = {
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

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "tool", "name": "record_concepts"},
            system=get_concept_prompt("openclaw"),
            messages=[{"role": "user", "content": json.dumps(compact_payload)}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "record_concepts":
                return block.input.get("concepts", [])
        return []

    # ------------------------------------------------------------------
    # Stage 2: relationship extraction
    # ------------------------------------------------------------------

    def _llm_extract_relationships(
        self, concepts: list[dict], compact_payload: list[dict]
    ) -> list[dict]:
        """Use Anthropic tool use to extract structured relationships between concepts."""
        client = self._get_client()
        if client is None:
            return []

        tool: dict = {
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

        user_msg = json.dumps({"concepts": concepts, "records": compact_payload})

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "tool", "name": "record_relationships"},
            system=get_relationship_prompt("openclaw"),
            messages=[{"role": "user", "content": user_msg}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "record_relationships":
                return block.input.get("relationships", [])
        return []

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

        if not compact_payload:
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
