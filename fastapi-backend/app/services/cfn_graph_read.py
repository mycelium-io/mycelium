# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Direct AgensGraph read for CFN's knowledge graphs.

CFN's shared-memories service writes to AgensGraph in the same Postgres
instance mycelium-backend uses (``settings.GRAPH_DB_URL``). CFN does NOT
expose a "list everything in the graph" API, so ``mycelium cfn ls`` goes
around CFN and reads AgensGraph directly.

This is **tight coupling to CFN's internal storage layout**:

- CFN names each MAS graph ``graph_<mas_id_with_hyphens_underscored>``
- Nodes have a ``properties`` dict with at least ``id`` and ``name`` fields
- No label filtering — we just MATCH (n) RETURN n

If CFN renames the graph or migrates to a different engine, ``mycelium
cfn ls`` breaks with an empty result or a SQL error. That's explicitly
documented in the CLI --help text.
"""

import logging
import re

import agensgraph  # noqa: F401 — registers psycopg2 type adapters
from sqlalchemy import create_engine, make_url
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None

# CFN writes its knowledge graphs into a separate Postgres database in the
# same instance we use for mycelium's SQL/vector tables. The backend's
# ``GRAPH_DB_URL`` points at ``/mycelium``; CFN's env points at ``/cfn_cp``.
# We reach into CFN's DB for the list endpoint.
_CFN_DB_NAME = "cfn_cp"

# CFN's AgensGraph adapter replaces hyphens in mas_id with underscores when
# constructing the graph name. Any other characters outside [a-zA-Z0-9_] would
# be suspicious — we refuse to query unsafe names rather than invite SQL issues.
_GRAPH_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class CfnGraphUnavailable(RuntimeError):
    """Raised when the AgensGraph read fails (missing graph, bad mas_id, SQL error)."""


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = make_url(settings.GRAPH_DB_URL).set(database=_CFN_DB_NAME)
        _engine = create_engine(
            url,
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=2,
            max_overflow=4,
        )
        logger.info("cfn_graph_read engine created: %s", str(url).split("@")[-1])
    return _engine


def _graph_name_for_mas(mas_id: str) -> str:
    """Mirror CFN's naming: ``graph_<mas_id_with_hyphens_underscored>``."""
    if not mas_id:
        raise CfnGraphUnavailable("mas_id is required")
    sanitized = mas_id.replace("-", "_")
    if not _GRAPH_NAME_PATTERN.match(sanitized):
        raise CfnGraphUnavailable(
            f"mas_id {mas_id!r} contains unsafe characters for AgensGraph naming",
        )
    return f"graph_{sanitized}"


def _node_to_dict(row) -> dict:
    """Coerce an agensgraph Vertex (or dict-like) result into a plain dict.

    agensgraph-python's Vertex exposes ``.label`` (str), ``.props`` (dict),
    and ``.vid`` (internal graph id like "3.1"). We flatten to a JSON-safe
    dict that survives FastAPI serialization.
    """
    if row is None:
        return {}
    props = getattr(row, "props", None)
    if isinstance(props, dict):
        vid = getattr(row, "vid", None)
        return {
            "label": getattr(row, "label", None),
            "vid": str(vid) if vid is not None else None,
            "id": props.get("id") or (str(vid) if vid is not None else ""),
            "name": props.get("name"),
            "properties": props,
        }
    if isinstance(row, dict):
        return row
    return {"raw": str(row)}


def list_concepts(*, mas_id: str, limit: int = 50) -> list[dict]:
    """Return up to ``limit`` concept nodes from CFN's graph for ``mas_id``.

    After ``SET graph_path``, AgensGraph's psycopg2 dialect lets us run
    bare cypher (``MATCH (n) RETURN n``) directly — no ``SELECT * FROM
    cypher(...)`` wrapper. The wrapper form breaks on quote escaping in
    certain dialect/driver combinations.

    Raises :class:`CfnGraphUnavailable` if the mas_id is unsafe, the graph
    doesn't exist, or AgensGraph returns an error.
    """
    graph = _graph_name_for_mas(mas_id)
    bounded_limit = max(1, min(int(limit), 500))

    try:
        with _get_engine().connect() as conn, conn.begin():
            conn.exec_driver_sql(f'SET graph_path = "{graph}"')
            result = conn.exec_driver_sql(
                f"MATCH (n) RETURN n LIMIT {bounded_limit}",
            )
            rows = result.fetchall()
    except SQLAlchemyError as exc:
        msg = str(exc).lower()
        if "does not exist" in msg or "not found" in msg:
            raise CfnGraphUnavailable(
                f"graph {graph!r} does not exist — has anything been ingested for mas_id={mas_id}?",
            ) from exc
        logger.exception("AgensGraph read failed for %s", graph)
        raise CfnGraphUnavailable(f"AgensGraph query failed: {exc}") from exc

    return [_node_to_dict(row[0]) for row in rows]
