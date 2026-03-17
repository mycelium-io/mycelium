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
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.agents import router as agents_router
from app.routes.audit import router as audit_router
from app.routes.cfn_proxy import router as cfn_proxy_router
from app.routes.knowledge import internal_router as knowledge_internal_router
from app.routes.knowledge import router as knowledge_router
from app.routes.mas import router as mas_router
from app.routes.memory import router as memory_router
from app.routes.messages import router as messages_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Mycelium backend starting up")
    from app.database import create_db_and_tables
    await create_db_and_tables()
    logger.info("Database tables ensured")
    # Preload embedding model so first request isn't slow
    try:
        from app.services.embedding import _get_model
        _get_model()
    except Exception:
        logger.warning("Embedding model preload failed — will load on first use")
    yield
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

# CFN routes
app.include_router(audit_router)
app.include_router(cfn_proxy_router)

# Knowledge graph
app.include_router(knowledge_router)
app.include_router(knowledge_internal_router)


@app.get("/", tags=["health"])
@app.get("/health", tags=["health"])
async def root():
    """Health check."""
    return {"status": "ok", "service": "mycelium-backend"}
