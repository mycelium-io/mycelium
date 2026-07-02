# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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
import tomllib
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
from app.routes.coordination_sessions import router as coordination_sessions_router
from app.routes.knowledge import router as knowledge_router
from app.routes.memory import router as memory_router
from app.routes.messages import router as messages_router
from app.routes.plan import agent_router as agent_context_router
from app.routes.plan import router as plan_router
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

    # TTL sweep for transient event messages (#392)
    from app.services.event_sweep import start_event_sweep, stop_event_sweep

    start_event_sweep()

    # Pre-load embedding model so first request isn't slow
    from app.services.embedding import warmup as warmup_embeddings

    try:
        await asyncio.to_thread(warmup_embeddings)
    except Exception as exc:
        logger.warning("Embedding warmup failed (non-fatal): %s", exc)

    yield
    stop_watcher()
    stop_event_sweep()
    logger.info("Mycelium backend shutting down")


def _read_pkg_version() -> str:
    """Read version from pyproject.toml so release.yml's tag bump (which seds
    pyproject.toml::project.version) is reflected at /healthz without needing
    a second sed against this file. Falls back to '0.0.0+unknown' if the file
    can't be located (e.g. running from an unusual layout)."""
    for candidate in (Path(__file__).resolve().parent.parent / "pyproject.toml",):
        if candidate.exists():
            try:
                return tomllib.loads(candidate.read_text())["project"]["version"]
            except (KeyError, tomllib.TOMLDecodeError):
                break
    return "0.0.0+unknown"


app = FastAPI(
    title="Mycelium Backend",
    version=_read_pkg_version(),
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


# Core routes. Health endpoints stay top-level for orchestrator probes.
app.include_router(rooms_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(stream_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(agent_context_router, prefix="/api")

# CFN routes
app.include_router(audit_router)
app.include_router(cfn_proxy_router)
app.include_router(cfn_read_router)

# Knowledge graph — forwards openclaw turns to CFN shared-memories + observability
app.include_router(knowledge_router)

# Coordination observability (round-trace ring buffer; see issue #162)
app.include_router(coordination_router)

# Coordination sessions as a top-level resource — used by OpenClaw plugin,
# frontend, and CLI in place of addressing sessions by their parent room's
# display name.
app.include_router(coordination_sessions_router)


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


@app.get("/api/observability", tags=["metrics"])
async def get_metrics():
    """Return a snapshot of backend-collected metrics (embeddings, LLM, indexer, etc.).

    Note: served under ``/api/observability`` rather than ``/api/metrics`` because
    privacy-extension blocklists pattern-match ``/api/metrics*`` as analytics
    telemetry and silently drop the request in the browser.
    """
    from app.services.metrics import snapshot

    return snapshot()


@app.get("/api/observability/collector", tags=["metrics"])
async def get_collector_metrics():
    """Proxy to the OTLP collector's ``/collector/metrics`` endpoint.

    Returns counters, histograms, sessions, and scrape data directly from the
    collector's in-memory store.  Returns 502 if the collector is unreachable.

    Configure ``COLLECTOR_URL`` (default ``http://mycelium-collector:4318``)
    to point at the collector service.
    """
    return await _proxy_collector("/collector/metrics")


@app.get("/api/observability/traces/recent", tags=["metrics"])
async def get_recent_traces(limit: int = 100, host: str | None = None):
    """Proxy to the OTLP collector's ``/collector/traces`` endpoint.

    Returns recent trace spans from the collector's SQLite store.
    Returns 502 if the collector is unreachable.
    """
    path = f"/collector/traces?limit={limit}"
    if host:
        from urllib.parse import quote

        path += f"&host={quote(host)}"
    return await _proxy_collector(path)


@app.get("/api/observability/hosts", tags=["metrics"])
async def get_hosts():
    """Proxy to the OTLP collector's ``/collector/hosts`` endpoint.

    Returns distinct hosts that have reported OTLP data, with span counts
    and agent lists.  Returns 502 if the collector is unreachable.
    """
    return await _proxy_collector("/collector/hosts")


async def _proxy_collector(path: str):
    """Forward a GET request to the collector and return the raw JSON response.

    Defence-in-depth: sanitise any non-standard JSON tokens (``Infinity``,
    ``NaN``) that might slip through from upstream before forwarding to the
    browser.
    """
    import json
    import math

    import httpx
    from fastapi.responses import JSONResponse, Response

    def _sanitise(obj: object) -> object:
        """Replace float inf/nan with None for JSON compliance."""
        if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [_sanitise(v) for v in obj]
        return obj

    def _parse_constant(c: str) -> None:
        """Map non-standard JSON tokens (Infinity, NaN) to None at parse time."""
        return None

    url = f"{settings.COLLECTOR_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            try:
                data = json.loads(resp.text, parse_constant=_parse_constant)
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(
                    status_code=502,
                    content={"detail": "Invalid JSON from collector"},
                )
            data = _sanitise(data)
            return Response(
                content=json.dumps(data, default=str),
                media_type="application/json",
            )
        return JSONResponse(
            status_code=resp.status_code,
            content=resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {"detail": resp.text},
        )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=502,
            content={
                "detail": f"Collector unreachable at {settings.COLLECTOR_URL}. Run: mycelium up --metrics"
            },
        )
    except Exception as exc:
        logger.warning("Collector proxy failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Collector proxy error: {type(exc).__name__}"},
        )


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
