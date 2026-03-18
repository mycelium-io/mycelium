"""
Cognition Engine adapter endpoints.

API contract sourced from cisco-eti/ioc-cfn-cognitive-agents
(ingestion-cognitive-agent and evidence-gathering-cognitive-agent).
Wire format structs mirrored from:
  ioc-cfn-svc/pkg/client/cognitionagentclient/cognitionagentclient.go
  ioc-cfn-svc/pkg/common/common.go

Mycelium implements this surface so ioc-cfn-svc can route
COGNITION_ENGINE_SVC_URL → http://mycelium-backend:8000.

POST /api/knowledge-mgmt/extraction          — LLM extraction → AgensGraph
POST /api/knowledge-mgmt/reasoning/evidence  — intent → graph concept fetch
POST /api/semantic-negotiation               — stub (NegMAS wire-up TODO)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.knowledge import graph_db
from app.knowledge import service as kg_service
from app.knowledge.ingestion import IngestionService
from app.knowledge.schemas import KnowledgeGraphStoreRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cognition-engine"])


# ── Shared ─────────────────────────────────────────────────────────────────────


class CfnHeader(BaseModel):
    workspace_id: str
    mas_id: str
    agent_id: str | None = None


# ── Extraction schemas ─────────────────────────────────────────────────────────


class ExtractionPayloadMetadata(BaseModel):
    format: Literal["observe-sdk-otel", "openclaw"] = "openclaw"


class ExtractionPayload(BaseModel):
    metadata: ExtractionPayloadMetadata
    data: list[Any]


class ExtractionRequest(BaseModel):
    header: CfnHeader
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    payload: ExtractionPayload


class ConceptAttributes(BaseModel):
    model_config = ConfigDict(extra="allow")
    concept_type: str
    embedding: list[list[float]] | None = None


class CfnConcept(BaseModel):
    id: str
    name: str
    description: str
    type: str
    attributes: ConceptAttributes


class CfnRelation(BaseModel):
    id: str
    node_ids: list[str]
    relationship: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExtractionMeta(BaseModel):
    records_processed: int = 0
    concepts_extracted: int = 0
    relations_extracted: int = 0
    dedup_enabled: bool = False
    concepts_deduped: int = 0
    relations_deduped: int = 0


class ExtractionResponse(BaseModel):
    header: CfnHeader
    response_id: str
    concepts: list[CfnConcept] = Field(default_factory=list)
    relations: list[CfnRelation] = Field(default_factory=list)
    descriptor: str = "openclaw"
    metadata: ExtractionMeta = Field(default_factory=ExtractionMeta)


# ── Evidence schemas ───────────────────────────────────────────────────────────


class EvidencePayload(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    intent: str
    additional_context: list[Any] = Field(default_factory=list)


class EvidenceRequest(BaseModel):
    header: CfnHeader
    request_id: str | None = None
    payload: EvidencePayload


class ReasonerConcept(BaseModel):
    concept_id: str
    name: str
    description: str
    type: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ReasonerRelation(BaseModel):
    id: str
    node_ids: list[str]
    relationship: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ReasonerDetails(BaseModel):
    concepts: list[ReasonerConcept] = Field(default_factory=list)
    relations: list[ReasonerRelation] = Field(default_factory=list)


class ReasonerRecord(BaseModel):
    content: dict = Field(
        default_factory=lambda: {"evidence": {"details": {"concepts": [], "relations": []}}}
    )


class EvidenceResponse(BaseModel):
    header: CfnHeader
    response_id: str
    records: list[ReasonerRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Negotiation schemas ────────────────────────────────────────────────────────


class NegotiationRequest(BaseModel):
    header: CfnHeader
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    payload: dict[str, Any] = Field(default_factory=dict)


class NegotiationResponse(BaseModel):
    header: CfnHeader
    response_id: str


# ── Evidence graph helper ──────────────────────────────────────────────────────


def _query_graph_for_evidence(graph_name: str) -> tuple[list[dict], list[dict]]:
    """Fetch all concepts and edges from graph_name.

    Returns (nodes, edges). Both empty if graph missing or error.
    """
    from app.knowledge.graph_db import get_engine

    nodes: list[dict] = []
    edges: list[dict] = []
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql(f'SET graph_path = "{graph_name}"')
            for row in conn.exec_driver_sql("MATCH (n:Concept) RETURN n LIMIT 30").fetchall():
                v = row[0]
                nodes.append(dict(v.props) if hasattr(v, "props") else dict(v))
            for row in conn.exec_driver_sql(
                "MATCH (a)-[r]->(b) RETURN a.id, r, b.id LIMIT 30"
            ).fetchall():
                e = row[1]
                ed = dict(e.props) if hasattr(e, "props") else {}
                ed["label"] = getattr(e, "label", "RELATED_TO")
                ed["source_id"] = str(row[0])
                ed["target_id"] = str(row[2])
                edges.append(ed)
    except Exception as exc:
        logger.warning("evidence: graph query failed for %s: %s", graph_name, exc, exc_info=True)
    return nodes, edges


# ── Endpoint 1: extraction ─────────────────────────────────────────────────────


@router.post("/api/knowledge-mgmt/extraction", response_model=ExtractionResponse)
async def knowledge_extraction(body: ExtractionRequest) -> ExtractionResponse:
    """LLM extraction from raw data → AgensGraph storage, returns CFN wire format."""
    svc = IngestionService(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)

    # Normalise otel records into openclaw-style turn dicts before flattening
    raw_data = body.payload.data
    if body.payload.metadata.format == "observe-sdk-otel":
        raw_data = [
            {
                "userMessage": f"{r.get('SpanName', '')} [{r.get('ServiceName', '')}]",
                "response": str(r.get("SpanAttributes", {})),
            }
            for r in raw_data
            if isinstance(r, dict)
        ]

    compact_payload = svc._build_compact_payload(raw_data)

    if not compact_payload:
        return ExtractionResponse(
            header=body.header,
            response_id=body.request_id,
            metadata=ExtractionMeta(records_processed=len(body.payload.data)),
        )

    raw_concepts: list[dict] = await asyncio.to_thread(
        svc._llm_extract_concepts,
        compact_payload,
    )
    raw_rels: list[dict] = await asyncio.to_thread(
        svc._llm_extract_relationships,
        raw_concepts,
        compact_payload,
    )

    # Mirror the ID/mapping block from ingestion.py
    concepts_out = [
        {
            "id": svc._generate_id(c.get("name", "")),
            "name": c.get("name", ""),
            "description": c.get("description", ""),
            "attributes": {"concept_type": c.get("type", "unknown")},
        }
        for c in raw_concepts
    ]

    concept_ids = {c["id"] for c in concepts_out}
    relations_out = []
    for r in raw_rels:
        src = r.get("source", "")
        tgt = r.get("target", "")
        rel_label = r.get("relationship", "INTERACTS_WITH")
        src_id = svc._generate_id(src)
        tgt_id = svc._generate_id(tgt)
        if src_id not in concept_ids or tgt_id not in concept_ids:
            continue
        relations_out.append(
            {
                "id": svc._generate_id(f"{src_id}_{tgt_id}_{rel_label}"),
                "node_ids": [src_id, tgt_id],
                "relation": rel_label,
                "attributes": {
                    "source_name": src,
                    "target_name": tgt,
                    "summarized_context": r.get("description", ""),
                },
            }
        )

    # Store in AgensGraph (non-fatal on failure)
    try:
        store_req = KnowledgeGraphStoreRequest(
            mas_id=body.header.mas_id,
            wksp_id=body.header.workspace_id,
            records={"concepts": concepts_out, "relations": relations_out},
            force_replace=True,
        )
        await asyncio.to_thread(kg_service.create_graph_store, store_req)
    except Exception as exc:
        logger.warning("extraction: graph store failed: %s", exc, exc_info=True)

    cfn_concepts = [
        CfnConcept(
            id=c["id"],
            name=c["name"],
            description=c["description"],
            type=c["attributes"].get("concept_type", "unknown"),
            attributes=ConceptAttributes(
                concept_type=c["attributes"].get("concept_type", "unknown")
            ),
        )
        for c in concepts_out
    ]
    cfn_relations = [
        CfnRelation(
            id=r["id"],
            node_ids=r["node_ids"],
            relationship=r["relation"],
            attributes=r.get("attributes", {}),
        )
        for r in relations_out
    ]

    return ExtractionResponse(
        header=body.header,
        response_id=body.request_id,
        concepts=cfn_concepts,
        relations=cfn_relations,
        metadata=ExtractionMeta(
            records_processed=len(body.payload.data),
            concepts_extracted=len(cfn_concepts),
            relations_extracted=len(cfn_relations),
        ),
    )


# ── Endpoint 2: evidence ───────────────────────────────────────────────────────


@router.post("/api/knowledge-mgmt/reasoning/evidence", response_model=EvidenceResponse)
async def reasoning_evidence(body: EvidenceRequest) -> EvidenceResponse:
    """Fetch graph evidence for an intent from the MAS knowledge graph."""
    response_id = body.request_id or str(uuid4())
    graph_name = "graph_" + body.header.mas_id.replace("-", "_")

    graph = await asyncio.to_thread(graph_db.get_graph, graph_name)
    if not graph:
        return EvidenceResponse(
            header=body.header,
            response_id=response_id,
            records=[],
            metadata={"note": "graph_not_found", "graph_name": graph_name},
        )

    nodes, edges = await asyncio.to_thread(_query_graph_for_evidence, graph_name)

    reasoner_concepts = [
        ReasonerConcept(
            concept_id=str(n.get("id", "")),
            name=str(n.get("name", "")),
            description=str(n.get("description", "")),
            type=str(n.get("concept_type", n.get("type", "unknown"))),
            attributes={k: v for k, v in n.items() if k not in ("id", "name", "description")},
        )
        for n in nodes
    ]
    reasoner_relations = [
        ReasonerRelation(
            id=str(e.get("id", str(uuid4()))),
            node_ids=[e.get("source_id", ""), e.get("target_id", "")],
            relationship=str(e.get("label", "RELATED_TO")),
            attributes={
                k: v for k, v in e.items() if k not in ("id", "label", "source_id", "target_id")
            },
        )
        for e in edges
    ]

    record = ReasonerRecord(
        content={
            "evidence": {
                "details": {
                    "concepts": [c.model_dump() for c in reasoner_concepts],
                    "relations": [r.model_dump() for r in reasoner_relations],
                }
            }
        }
    )

    return EvidenceResponse(
        header=body.header,
        response_id=response_id,
        records=[record],
        metadata={
            "graph_name": graph_name,
            "concepts": len(reasoner_concepts),
            "relations": len(reasoner_relations),
        },
    )


# ── Endpoint 3: negotiation stub ───────────────────────────────────────────────


@router.post("/api/semantic-negotiation", response_model=NegotiationResponse)
async def semantic_negotiation(body: NegotiationRequest) -> NegotiationResponse:
    """Stub. TODO: wire to NegMAS SAO engine in app/agents/semantic_negotiation/."""
    return NegotiationResponse(header=body.header, response_id=body.request_id)
