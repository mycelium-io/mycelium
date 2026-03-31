# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Knowledge graph service — business logic layer."""

import logging

from app.knowledge import adapter, graph_db
from app.knowledge.schemas import (
    QUERY_TYPE_CONCEPT,
    QUERY_TYPE_NEIGHBOUR,
    QUERY_TYPE_PATH,
    KnowledgeGraphDeleteRequest,
    KnowledgeGraphDeleteResponse,
    KnowledgeGraphQueryRequest,
    KnowledgeGraphQueryResponse,
    KnowledgeGraphStoreRequest,
    KnowledgeGraphStoreResponse,
    ResponseStatus,
)

logger = logging.getLogger(__name__)


def create_graph_store(data: KnowledgeGraphStoreRequest) -> KnowledgeGraphStoreResponse:
    request_id = data.request_id
    try:
        graph = adapter.get_graph_name(data.model_dump())
        nodes, edges = adapter.convert_to_models(data.model_dump())
        ok, msg = graph_db.save(
            graph=graph, nodes=nodes, edges=edges, force_replace=data.force_replace
        )
        status = ResponseStatus.SUCCESS if ok else ResponseStatus.FAILURE
        return KnowledgeGraphStoreResponse(request_id=request_id, status=status, message=msg)
    except Exception as exc:
        return KnowledgeGraphStoreResponse(
            request_id=request_id, status=ResponseStatus.FAILURE, message=f"Failed to create: {exc}"
        )


def delete_graph_store(data: KnowledgeGraphDeleteRequest) -> KnowledgeGraphDeleteResponse:
    request_id = data.request_id
    try:
        ag = adapter.get_graph_name(data.model_dump())
        nodes, _ = adapter.convert_to_models(data.model_dump())
        ok, msg = graph_db.delete(graph=ag, nodes=nodes)
        status = ResponseStatus.SUCCESS if ok else ResponseStatus.FAILURE
        return KnowledgeGraphDeleteResponse(request_id=request_id, status=status, message=msg)
    except Exception as exc:
        return KnowledgeGraphDeleteResponse(
            request_id=request_id, status=ResponseStatus.FAILURE, message=f"Failed to delete: {exc}"
        )


def delete_graph_store_internal(data: KnowledgeGraphDeleteRequest) -> KnowledgeGraphDeleteResponse:
    """Drop the whole graph (internal/admin use)."""
    request_id = data.request_id
    try:
        ag = adapter.get_graph_name(data.model_dump())
        ok = graph_db.delete_graph(ag)
        status = ResponseStatus.SUCCESS if ok else ResponseStatus.FAILURE
        msg = f"graph:{ag} {'deleted' if ok else 'not deleted'}"
        return KnowledgeGraphDeleteResponse(request_id=request_id, status=status, message=msg)
    except Exception as exc:
        return KnowledgeGraphDeleteResponse(
            request_id=request_id, status=ResponseStatus.FAILURE, message=f"Failed to delete: {exc}"
        )


def query_graph_store(data: KnowledgeGraphQueryRequest) -> KnowledgeGraphQueryResponse:
    request_id = data.request_id
    try:
        ag = adapter.get_graph_name(data.model_dump())
        nodes = adapter.convert_query_to_models(data.model_dump())

        if not graph_db.get_graph(ag):
            return KnowledgeGraphQueryResponse(
                request_id=request_id,
                status=ResponseStatus.NOT_FOUND,
                message=f"Graph {ag} does not exist",
            )

        not_found = [n.id for n in nodes if not graph_db.get_node(ag, n)]
        if not_found:
            return KnowledgeGraphQueryResponse(
                request_id=request_id,
                status=ResponseStatus.NOT_FOUND,
                message=f"Nodes do not exist: {', '.join(not_found)}",
            )

        qt = data.query_criteria.query_type if data.query_criteria else QUERY_TYPE_NEIGHBOUR
        depth = data.query_criteria.depth if data.query_criteria else None
        use_dir = data.query_criteria.use_direction if data.query_criteria else True

        if qt == QUERY_TYPE_PATH:
            ok, results, msg = graph_db.query_type_path(
                ag, nodes, depth=depth, use_direction=use_dir
            )
        elif qt == QUERY_TYPE_CONCEPT:
            ok, results, msg = graph_db.query_type_concept(ag, nodes)
        else:  # neighbour or default
            ok, results, msg = graph_db.query_type_neighbor(ag, nodes)

        if ok:
            records = adapter.convert_models_to_query_response_records(results)
            return KnowledgeGraphQueryResponse(
                request_id=request_id,
                status=ResponseStatus.SUCCESS,
                message=msg,
                records=records or None,
            )
        return KnowledgeGraphQueryResponse(
            request_id=request_id, status=ResponseStatus.FAILURE, message=msg
        )

    except Exception as exc:
        return KnowledgeGraphQueryResponse(
            request_id=request_id, status=ResponseStatus.FAILURE, message=f"Failed to query: {exc}"
        )
