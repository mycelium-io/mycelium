# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Mycelium FastAPI backend.

  - Room CRUD
  - Messages (POST + Postgres NOTIFY)
  - Sessions (presence)
  - SSE stream (LISTEN)
  - Audit events
  - CFN proxy (shared-memories, memory-operations)

No auth, no heartbeat, no Neo4j, no Yjs, no scheduler.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Must be set before sentence-transformers / huggingface_hub are imported.
# Prevents network calls when the model is already cached locally.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.routes.audit import router as audit_router
from app.routes.cfn_proxy import cfn_read_router
from app.routes.cfn_proxy import router as cfn_proxy_router
from app.routes.coordination import router as coordination_router
from app.routes.knowledge import router as knowledge_router
from app.routes.memory import router as memory_router
from app.routes.messages import router as messages_router
from app.routes.rooms import router as rooms_router
from app.routes.sessions import router as sessions_router
from app.routes.stream import router as stream_router

from .config import settings

# Logging
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/app.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def _register_memory_provider() -> None:
    """Register Mycelium as a memory provider with ioc-cfn-mgmt-plane-svc.

    Non-fatal — if CFN_MGMT_URL is unset or the call fails, startup continues.
    Mirrors the registration contract used by ioc-knowledge-memory-svc.
    """
    import time

    import requests

    from app.services.metrics import record_cfn_call

    url = settings.CFN_MGMT_URL
    if not url:
        return

    api_url = settings.API_BASE_URL
    payload = {
        "memory_provider_name": "mycelium",
        "description": (
            "Mycelium persistent memory — namespaced KVP, semantic vector search, "
            f"and knowledge graph. API: {api_url}/docs"
        ),
        "config": {
            "url": api_url,
            "shared": "True",
        },
    }
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{url.rstrip('/')}/api/memory-providers",
            json=payload,
            timeout=10,
        )
        record_cfn_call(
            service="mgmt",
            operation="register_memory_provider",
            duration_ms=(time.monotonic() - t0) * 1000,
            status_code=resp.status_code,
            error=resp.status_code not in (201, 409),
        )
        if resp.status_code == 201:
            logger.info("Registered as memory provider with CFN mgmt plane")
        elif resp.status_code == 409:
            logger.info("Already registered as memory provider with CFN mgmt plane")
        else:
            logger.warning(
                "CFN memory provider registration returned %s: %s", resp.status_code, resp.text
            )
    except Exception as exc:
        record_cfn_call(
            service="mgmt",
            operation="register_memory_provider",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=True,
        )
        logger.warning("CFN memory provider registration failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Mycelium backend starting up")
    from app.database import create_db_and_tables

    await create_db_and_tables()
    logger.info("Database tables ensured")
    # Register with IoC CFN mgmt plane if configured
    _register_memory_provider()
    # Incremental scan of filesystem → search index
    from app.services.reindex import start_watcher, startup_scan, stop_watcher

    await startup_scan()
    start_watcher()

    # Pre-load embedding model so first request isn't slow
    from app.services.embedding import warmup as warmup_embeddings

    try:
        await asyncio.to_thread(warmup_embeddings)
    except Exception as exc:
        logger.warning("Embedding warmup failed (non-fatal): %s", exc)

    yield
    stop_watcher()
    logger.info("Mycelium backend shutting down")


app = FastAPI(
    title="Mycelium Backend",
    version="0.1.0",
    openapi_url=settings.OPENAPI_URL,
    lifespan=lifespan,
)

# CORS — starlette types CORSMiddleware as a class but typeshed expects a factory.
app.add_middleware(
    CORSMiddleware,  # ty: ignore[invalid-argument-type]
    allow_origins=list(settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Core routes
app.include_router(rooms_router)
app.include_router(messages_router)
app.include_router(sessions_router)
app.include_router(stream_router)
app.include_router(memory_router)

# CFN routes
app.include_router(audit_router)
app.include_router(cfn_proxy_router)
app.include_router(cfn_read_router)

# Knowledge graph — forwards openclaw turns to CFN shared-memories + observability
app.include_router(knowledge_router)

# Coordination observability (round-trace ring buffer; see issue #162)
app.include_router(coordination_router)


@app.get("/", tags=["health"])
@app.get("/health", tags=["health"])
async def root(
    check_llm: bool = False,
    llm_probe: str = "provider",
    session: AsyncSession = Depends(get_async_session),
):
    """Health check.

    Pass ``?check_llm=true`` to probe the LLM provider.  Without it, only local
    config status is included.

    Probe mode is selected by ``llm_probe`` (only relevant when check_llm=true):

    * ``provider`` (default) — zero-cost model-list call.  Free but only validates
      openai/anthropic/ollama; returns "unchecked" for bedrock/vertex/etc.
    * ``completion`` — real ``litellm.acompletion(max_tokens=1)`` call.  Exercises
      the same code path as inference and surfaces missing provider SDK extras
      (e.g. boto3 for Bedrock), bad model strings, and endpoint-level auth
      failures.  Costs a single token.
    """
    from app.services.llm_health import get_config_status, probe_completion, probe_provider

    result: dict = {"status": "ok", "service": "mycelium-backend", "version": app.version}

    # Database
    result["database"] = await _check_database(session)

    # Embedding model
    result["embedding"] = _check_embedding()

    # LLM
    if check_llm:
        if llm_probe == "completion":
            llm = await probe_completion()
        else:
            llm = await probe_provider()
    else:
        llm = get_config_status()
    result["llm"] = llm.to_dict()

    overall_issues = []
    if result["database"]["status"] != "ok":
        overall_issues.append("database")
    if result["llm"]["status"] not in ("ok", "unchecked"):
        overall_issues.append("llm")
    if overall_issues:
        result["status"] = "degraded"

    return result


@app.get("/api/metrics", tags=["metrics"])
async def get_metrics():
    """Return a snapshot of backend-collected metrics (embeddings, LLM, indexer, etc.)."""
    from app.services.metrics import snapshot

    return snapshot()


@app.get("/api/observability/collector", tags=["observability"])
async def get_collector_metrics():
    """Return OTLP/scrape metrics written by the CLI collector.

    Reads ``~/.mycelium/metrics.json`` and returns the collector-specific
    keys (counters, histograms, sessions, scrape) -- excluding the ``backend``
    key which duplicates ``GET /api/observability``.  Returns 404 when the file
    is absent (collector not running or never started).
    """
    import json

    from fastapi.responses import JSONResponse

    metrics_path = Path.home() / ".mycelium" / "metrics.json"
    if not metrics_path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": "Collector metrics file not found. Run: mycelium metrics collect"},
        )
    try:
        raw = json.loads(metrics_path.read_text())
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to read collector metrics file"},
        )
    return {
        "updated_at": raw.get("updated_at"),
        "counters": raw.get("counters", {}),
        "histograms": raw.get("histograms", {}),
        "sessions": raw.get("sessions", []),
        "scrape": raw.get("scrape", {}),
    }


@app.get("/api/observability/traces/recent", tags=["observability"])
async def get_recent_traces(limit: int = 100):
    """Return recent OTLP traces captured by the CLI collector.

    Reads ``~/.mycelium/traces.db`` (SQLite) written by ``mycelium metrics collect``.
    Each trace includes its full span tree for waterfall rendering.
    Returns 404 when the database is absent.
    """
    import json
    import sqlite3

    from fastapi.responses import JSONResponse

    db_path = Path.home() / ".mycelium" / "traces.db"
    if not db_path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": "Traces database not found. Run: mycelium metrics collect"},
        )
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row

        trace_ids = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT trace_id FROM spans ORDER BY start_time DESC LIMIT ?",
                (limit * 20,),
            ).fetchall()
        ]
        seen: list[str] = []
        seen_set: set[str] = set()
        for tid in trace_ids:
            if tid not in seen_set:
                seen.append(tid)
                seen_set.add(tid)
            if len(seen) >= limit:
                break

        traces: list[dict] = []
        for trace_id in seen:
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
                (trace_id,),
            ).fetchall()
            if not rows:
                continue
            spans = []
            for r in rows:
                spans.append({
                    "trace_id": r["trace_id"],
                    "span_id": r["span_id"],
                    "parent_span_id": r["parent_span_id"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "service": r["service"],
                    "start_time": r["start_time"],
                    "duration_ms": r["duration_ms"],
                    "status": r["status"],
                    "status_message": r["status_message"],
                    "attributes": json.loads(r["attributes"]),
                })
            root_spans = [s for s in spans if not s["parent_span_id"]]
            root = root_spans[0] if root_spans else spans[0]
            total_duration = max((s["duration_ms"] for s in spans), default=0)
            has_error = any(s["status"] == "error" for s in spans)
            agent = ""
            for s in spans:
                a = s.get("attributes", {})
                agent = (
                    str(a.get("openclaw.channel", ""))
                    or str(a.get("openclaw.agent", ""))
                    or str(a.get("gen_ai.agent", ""))
                )
                if agent:
                    break
            traces.append({
                "trace_id": trace_id,
                "root_span": root["name"],
                "service": root.get("service", ""),
                "agent": agent,
                "start_time": root["start_time"],
                "duration_ms": round(total_duration, 2),
                "span_count": len(spans),
                "has_error": has_error,
                "spans": spans,
            })
        conn.close()
    except Exception:
        logger.exception("Failed to read traces database")
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to read traces database"},
        )
    return {
        "count": len(traces),
        "traces": traces,
    }


async def _check_database(session: AsyncSession) -> dict:
    """Probe database connectivity with SELECT 1."""
    from sqlalchemy import text

    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "message": "Connected"}
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return {"status": "unreachable", "message": f"Cannot connect: {type(exc).__name__}"}


def _check_embedding() -> dict:
    """Report embedding model status (loaded, cache exists, or stub mode)."""
    import os

    from app.services import embedding

    if embedding._STUB:
        return {
            "status": "stub",
            "model": settings.EMBEDDING_MODEL,
            "message": "Stub mode (no real embeddings)",
        }

    model_loaded = embedding._model is not None

    if model_loaded:
        return {"status": "ok", "model": settings.EMBEDDING_MODEL, "message": "Model loaded"}

    # Check fastembed cache
    cache_dir = embedding._FASTEMBED_CACHE
    cache_exists = os.path.isdir(cache_dir) and any(
        f.endswith(".onnx") for root, _, files in os.walk(cache_dir) for f in files
    )
    if cache_exists:
        return {
            "status": "ok",
            "model": settings.EMBEDDING_MODEL,
            "message": "Model cached (not yet loaded)",
        }
    return {
        "status": "not_cached",
        "model": settings.EMBEDDING_MODEL,
        "message": "Model not in cache; will download on first use",
    }
