# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Sync AgensGraph database access.

The engine is created once per process from GRAPH_DB_URL in settings.
All operations use exec_driver_sql (psycopg2 dialect) with %s params.
"""

import logging

import agensgraph  # noqa: F401 — registers psycopg2 type adapters
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.knowledge.edge import Edge
from app.knowledge.node import Node

logger = logging.getLogger(__name__)

_engine = None


def get_engine():
    """Return (and lazily create) the shared sync engine for ioc-graph-db."""
    global _engine
    if _engine is None:
        from app.config import settings

        _engine = create_engine(
            settings.GRAPH_DB_URL,
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=10,
        )
        logger.info("AgensGraph engine created: %s", settings.GRAPH_DB_URL.split("@")[-1])
    return _engine


# ── helpers ───────────────────────────────────────────────────────────────────


def _create_graph(conn, graph_name: str) -> bool:
    result = conn.execute(
        text("SELECT COUNT(*) FROM ag_graph WHERE graphname = :name"), {"name": graph_name}
    )
    if result.scalar() > 0:
        return True
    conn.execute(text(f'CREATE GRAPH "{graph_name}"'))
    logger.info("Created graph '%s'", graph_name)
    return True


def get_graph(graph_name: str) -> dict | None:
    try:
        with get_engine().connect() as conn:
            result = conn.execute(
                text("""
                    SELECT graphname, nspname
                    FROM ag_graph g
                    JOIN pg_namespace n ON n.nspname = g.graphname
                    WHERE g.graphname = :name
                """),
                {"name": graph_name},
            ).fetchone()
            if not result:
                return None
            return {"name": result[0], "namespace": result[1]}
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to get graph '{graph_name}': {exc}") from exc


def delete_graph(graph_name: str) -> bool:
    try:
        with get_engine().begin() as conn:
            result = conn.execute(
                text("SELECT count(*) FROM ag_graph WHERE graphname = :name"), {"name": graph_name}
            ).fetchone()
            if not result or result[0] == 0:
                return True
            conn.execute(text(f'DROP GRAPH "{graph_name}" CASCADE'))
            logger.info("Deleted graph '%s'", graph_name)
            return True
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to delete graph '{graph_name}': {exc}") from exc


def get_node(graph: str, node: Node) -> dict | None:
    try:
        with get_engine().connect() as conn, conn.begin():
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            query, params = node.to_cypher_exists()
            result = conn.exec_driver_sql(query, params).fetchone()
            return result[0] if result and result[0] else None
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to get node '{node.id}': {exc}") from exc


def save(
    graph: str, nodes: list[Node], edges: list[Edge], force_replace: bool = False
) -> tuple[bool, str]:
    if not graph:
        return False, "Graph name cannot be empty"

    try:
        with get_engine().begin() as conn:
            _create_graph(conn, graph)
    except Exception as exc:
        return False, f"Error creating/accessing graph '{graph}': {exc}"

    if not nodes and not edges:
        return True, f"Graph: {graph} created"

    try:
        with get_engine().connect() as conn, conn.begin():
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')

            existing_nodes: list[str] = []
            existing_edges: list[str] = []
            for node in nodes:
                q, p = node.to_cypher_exists()
                r = conn.exec_driver_sql(q, p).fetchone()
                if r and r[0]:
                    existing_nodes.append(node.id)
            for edge in edges:
                q, p = edge.to_cypher_exists()
                r = conn.exec_driver_sql(q, p).fetchone()
                if r and r[0]:
                    existing_edges.append(edge.id)

            if not force_replace and (existing_nodes or existing_edges):
                parts = []
                if existing_nodes:
                    parts.append(f"Nodes already exist: {', '.join(existing_nodes)}")
                if existing_edges:
                    parts.append(f"Edges already exist: {', '.join(existing_edges)}")
                parts.append("Use force_replace=True to recreate.")
                raise ValueError(". ".join(parts))

            if force_replace:
                for node in nodes:
                    if node.id in existing_nodes:
                        q, p = node.to_cypher_delete()
                        conn.exec_driver_sql(q, p)

            for node in nodes:
                q, p = node.to_cypher_create()
                conn.exec_driver_sql(q, p)
            for edge in edges:
                q, p = edge.to_cypher_create()
                conn.exec_driver_sql(q, p)

        return True, f"Saved {len(nodes)} nodes and {len(edges)} edges to graph '{graph}'"

    except ValueError as exc:
        return False, str(exc)
    except SQLAlchemyError as exc:
        return False, f"Database error: {exc}"
    except Exception as exc:
        return False, f"Save failed: {exc}"


def delete(graph: str, nodes: list[Node]) -> tuple[bool, str]:
    if not nodes:
        return True, "No nodes provided"
    try:
        with get_engine().connect() as conn, conn.begin():
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            for node in nodes:
                q, p = node.to_cypher_delete()
                conn.exec_driver_sql(q, p)
        return True, f"Deleted {len(nodes)} nodes from graph '{graph}'"
    except SQLAlchemyError as exc:
        return False, f"Database error: {exc}"
    except Exception as exc:
        return False, f"Delete failed: {exc}"


def query_type_concept(graph: str, nodes: list[Node]) -> tuple[bool, list, str]:
    if len(nodes) != 1:
        return False, [], "Concept query requires exactly 1 node"
    node = nodes[0]
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            q, p = node.to_cypher_get()
            result = conn.exec_driver_sql(q, p).fetchone()
            if not result:
                return False, [], f"Node {node.id} does not exist"
            node_data = [dict(n) for n in result[0]] if result and result[0] else []
            return True, [{"edges": [], "nodes": node_data}], f"Queried concept {node.id}"
    except Exception as exc:
        return False, [], f"Query failed: {exc}"


def query_type_neighbor(graph: str, nodes: list[Node]) -> tuple[bool, list, str]:
    if len(nodes) != 1:
        return False, [], "Neighbor query requires exactly 1 node"
    node = nodes[0]
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            q, p = node.to_cypher_exists()
            if not conn.exec_driver_sql(q, p).fetchone():
                return False, [], f"Node {node.id} does not exist"
            q, p = node.to_cypher_neighbor_query()
            result = conn.exec_driver_sql(q, p).fetchone()
            if not result:
                return True, [], f"No neighbors for {node.id}"
            relationships = [dict(r) for r in result[1]] if result[1] else []
            neighbors = [dict(n) for n in result[2]] if result[2] else []
            return (
                True,
                [{"edges": relationships, "nodes": neighbors}],
                f"Queried neighbours for {node.id}",
            )
    except Exception as exc:
        return False, [], f"Query failed: {exc}"


def query_type_path(
    graph: str, nodes: list[Node], depth: int | None = None, use_direction: bool = True
) -> tuple[bool, list, str]:
    if len(nodes) != 2:
        return False, [], "Path query requires exactly 2 nodes"
    src, dst = nodes
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            for n in (src, dst):
                q, p = n.to_cypher_exists()
                if not conn.exec_driver_sql(q, p).fetchone():
                    return False, [], f"Node {n.id} does not exist"
            if use_direction:
                q, p = src.to_cypher_path_query_with_direction(dst, depth)
            else:
                q, p = src.to_cypher_path_query(dst, depth)
            path_results = conn.exec_driver_sql(q, p).fetchall()
            if not path_results:
                return True, [], f"No paths between {src.id} and {dst.id}"
            results = []
            for row in path_results:
                path = row[0]
                path_nodes, path_edges = [], []
                if hasattr(path, "vertices") and path.vertices:
                    for v in path.vertices:
                        path_nodes.append(dict(v.props) if hasattr(v, "props") else {})
                if hasattr(path, "edges") and path.edges:
                    for e in path.edges:
                        ed = dict(e.props) if hasattr(e, "props") else {}
                        ed["label"] = getattr(e, "label", "unknown")
                        path_edges.append(ed)
                results.append({"nodes": path_nodes, "edges": path_edges})
            return True, results, f"Found {len(results)} path(s) between {src.id} and {dst.id}"
    except Exception as exc:
        return False, [], f"Query failed: {exc}"
