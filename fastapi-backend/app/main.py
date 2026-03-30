"""
Mycelium FastAPI backend.

  - Workspace / MAS / Agent registry
  - Room CRUD
  - Messages (POST + Postgres NOTIFY)
  - Sessions (presence)
  - SSE stream (LISTEN)
  - Audit events
  - CFN proxy (shared-memories, memory-operations)

No auth, no heartbeat, no Neo4j, no Yjs, no scheduler.
"""

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
from app.routes.agents import router as agents_router
from app.routes.audit import router as audit_router
from app.routes.cfn_proxy import router as cfn_proxy_router
from app.routes.cognition_engine import router as cognition_engine_router
from app.routes.knowledge import internal_router as knowledge_internal_router
from app.routes.knowledge import router as knowledge_router
from app.routes.mas import router as mas_router
from app.routes.memory import router as memory_router
from app.routes.messages import router as messages_router
from app.routes.notebook import router as notebook_router
from app.routes.rooms import router as rooms_router
from app.routes.sessions import router as sessions_router
from app.routes.stream import router as stream_router
from app.routes.workspaces import router as workspaces_router

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
    import requests

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
    try:
        resp = requests.post(
            f"{url.rstrip('/')}/api/memory-providers",
            json=payload,
            timeout=10,
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
    yield
    stop_watcher()
    logger.info("Mycelium backend shutting down")


app = FastAPI(
    title="Mycelium Backend",
    version="0.1.0",
    openapi_url=settings.OPENAPI_URL,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registry
app.include_router(workspaces_router)
app.include_router(mas_router)
app.include_router(agents_router)

# Core routes
app.include_router(rooms_router)
app.include_router(messages_router)
app.include_router(sessions_router)
app.include_router(stream_router)
app.include_router(memory_router)
app.include_router(notebook_router)

# CFN routes
app.include_router(audit_router)
app.include_router(cfn_proxy_router)
app.include_router(cognition_engine_router)

# Knowledge graph
app.include_router(knowledge_router)
app.include_router(knowledge_internal_router)


@app.get("/", tags=["health"])
@app.get("/health", tags=["health"])
async def root(
    check_llm: bool = False,
    session: AsyncSession = Depends(get_async_session),
):
    """Health check.

    Pass ?check_llm=true to probe the LLM provider (zero-cost model-list call).
    Without it, only local config status is included.
    """
    from app.services.llm_health import get_config_status, probe_provider

    result: dict = {"status": "ok", "service": "mycelium-backend", "version": app.version}

    # Database
    result["database"] = await _check_database(session)

    # Embedding model
    result["embedding"] = _check_embedding()

    # LLM
    if check_llm:
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
        return {"status": "stub", "model": settings.EMBEDDING_MODEL, "message": "Stub mode (no real embeddings)"}

    model_loaded = embedding._model is not None

    hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
    model_slug = settings.EMBEDDING_MODEL.replace("/", "--")
    snapshots_dir = os.path.join(hf_cache, f"models--{model_slug}", "snapshots")
    cache_exists = os.path.isdir(snapshots_dir)

    if model_loaded:
        return {"status": "ok", "model": settings.EMBEDDING_MODEL, "message": "Model loaded"}
    if cache_exists:
        return {"status": "ok", "model": settings.EMBEDDING_MODEL, "message": "Model cached (not yet loaded)"}
    return {
        "status": "not_cached",
        "model": settings.EMBEDDING_MODEL,
        "message": "Model not in cache; will download on first use",
    }
