"""Convert knowledge graph API schemas to/from Node/Edge models."""

import json
import logging
from typing import Any

from app.knowledge.edge import Edge
from app.knowledge.node import Node
from app.knowledge.schemas import (
    Concept,
    EmbeddingConfig,
    KnowledgeGraphQueryResponseRecord,
    Relation,
)

logger = logging.getLogger(__name__)


def get_graph_name(data: dict[str, Any]) -> str:
    """Derive graph name from mas_id (priority) or wksp_id."""
    mas_id = data.get("mas_id") or ""
    wksp_id = data.get("wksp_id") or ""
    if mas_id:
        return "graph_" + mas_id.replace("-", "_")
    if wksp_id:
        return "graph_" + wksp_id.replace("-", "_")
    raise ValueError("Either mas_id or wksp_id must be provided")


def convert_to_models(data: dict[str, Any]) -> tuple[list[Node], list[Edge]]:
    """Convert KnowledgeGraphStoreRequest dict → (nodes, edges)."""
    mas_id = data.get("mas_id", "")
    wksp_id = data.get("wksp_id", "")
    memory_type = data.get("memory_type", "")

    nodes: list[Node] = []
    edges: list[Edge] = []

    records = data.get("records") or {}
    for concept in records.get("concepts") or []:
        props: dict[str, Any] = {
            "name": concept.get("name", ""),
            "description": concept.get("description", ""),
            **concept.get("attributes", {}),
        }
        if mas_id:
            props["mas_id"] = mas_id
        if wksp_id:
            props["wksp_id"] = wksp_id
        if memory_type:
            props["memory_type"] = memory_type
        if concept.get("tags"):
            props["tags"] = concept["tags"]
        if concept.get("embeddings"):
            emb = concept["embeddings"]
            props["embedding_vector"] = emb.get("data", [])
            props["embedding_model"] = emb.get("name", "")
        nodes.append(Node(id=concept["id"], labels=["Concept"], properties=props))

    for rel in records.get("relations") or []:
        props = {"node_ids": rel.get("node_ids", []), **rel.get("attributes", {})}
        if rel.get("embeddings"):
            emb = rel["embeddings"]
            props["embedding_vector"] = emb.get("data", [])
            props["embedding_model"] = emb.get("name", "")
        if mas_id:
            props["mas_id"] = mas_id
        if wksp_id:
            props["wksp_id"] = wksp_id
        if memory_type:
            props["memory_type"] = memory_type
        if rel.get("relation"):
            props["relation"] = rel["relation"]
        edges.append(Edge(id=rel["id"], node_ids=rel["node_ids"], relation=rel["relation"], properties=props))

    return nodes, edges


def convert_query_to_models(data: dict[str, Any]) -> list[Node]:
    """Convert KnowledgeGraphQueryRequest dict → list of Node objects."""
    nodes: list[Node] = []
    for concept in (data.get("records") or {}).get("concepts") or []:
        if not isinstance(concept, dict):
            continue
        props: dict[str, Any] = {
            "name": concept.get("name", ""),
            "description": concept.get("description", ""),
            **concept.get("attributes", {}),
        }
        if concept.get("tags"):
            props["tags"] = concept["tags"]
        if concept.get("embeddings"):
            emb = concept["embeddings"]
            props["embedding_vector"] = emb.get("data", [])
            props["embedding_model"] = emb.get("name", "")
        for key in ("mas_id", "wksp_id", "memory_type"):
            if data.get(key):
                props[key] = data[key]
        nodes.append(Node(id=concept.get("id", ""), labels=["Concept"], properties=props))
    return nodes


def _parse_json_field(value: Any, default: Any = None) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else []
    return value


def convert_models_to_query_response_records(
    db_results: list[dict[str, Any]]
) -> list[KnowledgeGraphQueryResponseRecord]:
    records = []
    for result in db_results:
        if "error" in result:
            continue

        relations: list[Relation] = []
        for edge in result.get("edges") or []:
            edge_props = edge.get("properties", edge)
            relation = edge_props.get("relation")
            node_ids = _parse_json_field(edge_props.get("node_ids", []))
            if not relation or not isinstance(relation, str) or len(node_ids) < 2:
                continue
            embeddings = None
            if "embedding_vector" in edge_props or "embedding_model" in edge_props:
                embeddings = EmbeddingConfig(
                    data=_parse_json_field(edge_props.get("embedding_vector", [])),
                    name=edge_props.get("embedding_model", ""),
                )
            attrs = {
                k: v for k, v in edge_props.items()
                if k not in ("id", "node_ids", "relation", "embedding_vector", "embedding_model", "embeddings")
            }
            relations.append(Relation(
                id=edge_props.get("id", ""),
                relation=relation,
                node_ids=node_ids,
                attributes=attrs,
                embeddings=embeddings,
            ))

        concepts: list[Concept] = []
        for node in result.get("nodes") or []:
            node_props = node.get("properties", node)
            embeddings = None
            if "embedding_vector" in node_props or "embedding_model" in node_props:
                embeddings = EmbeddingConfig(
                    data=_parse_json_field(node_props.get("embedding_vector", [])),
                    name=node_props.get("embedding_model", ""),
                )
            attrs = {
                k: v for k, v in node_props.items()
                if k not in ("id", "name", "description", "embedding_vector", "embedding_model", "embeddings", "tags")
            }
            concepts.append(Concept(
                id=node_props.get("id"),
                name=node_props.get("name", ""),
                description=node_props.get("description"),
                attributes=attrs,
                embeddings=embeddings,
                tags=_parse_json_field(node_props.get("tags", [])),
            ))

        records.append(KnowledgeGraphQueryResponseRecord(relationships=relations, concepts=concepts))
    return records
