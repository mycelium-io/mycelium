# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Mycelium FastAPI backend.

  - Room CRUD
  - Messages (POST + Postgres NOTIFY)
  - Sessions (presence)
  - SSE stream (LISTEN)

No auth, no heartbeat, no Neo4j, no Yjs, no scheduler.
"""

import asyncio
import logging
import os
import sys
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Must be set before sentence-transformers / huggingface_hub are imported.
# Prevents network calls when the model is already cached locally.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.agents import router as agents_router
from app.routes.engines import router as engines_router
from app.routes.episodes import router as episodes_router
from app.routes.invites import router as invites_router
from app.routes.memory import router as memory_router
from app.routes.messages import router as messages_router
from app.routes.participate import router as participate_router
from app.routes.plan import agent_router as agent_context_router
from app.routes.plan import router as plan_router
from app.routes.rooms import router as rooms_router
from app.routes.sessions import router as sessions_router
from app.routes.stream import router as stream_router
from app.routes.users import router as users_router
from app.services.auth import auth_gate

from .config import settings

# Logging
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
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
    # Say plainly whether the HTTP surface is gated — "is this hub open?" should
    # never require reading config to answer.
    from app.services import auth as auth_service

    if settings.AUTH_ENABLED:
        logger.info(
            "HTTP-API JWT gate ENABLED (issuers=%s, localhost_bypass=%s)",
            [e.issuer for e in settings.AUTH_ISSUERS] or "<none>",
            settings.AUTH_LOCALHOST_BYPASS,
        )
        for warning in auth_service.config_warnings():
            logger.warning("auth: %s", warning)
    else:
        logger.info("HTTP-API JWT gate disabled — requests are unauthenticated")
    # Incremental scan of filesystem → JSONL search index
    from app.services.reindex import start_watcher, startup_scan, stop_watcher

    await startup_scan()
    start_watcher()

    # TTL sweep for transient event messages
    from app.services.event_sweep import start_event_sweep, stop_event_sweep

    start_event_sweep()

    # Pre-load embedding model so first request isn't slow
    from app.services.embedding import warmup as warmup_embeddings

    try:
        await asyncio.to_thread(warmup_embeddings)
    except Exception as exc:
        logger.warning("Embedding warmup failed (non-fatal): %s", exc)

    # Wire the SIEP aligner into every room's summon seam before any
    # channel is provisioned, so all persisters pick it up. Dormant until an
    # @-summon of its reserved handle arrives — zero idle cost.
    from app.services.aligner import AlignerEngine
    from app.services.plan_sync import PlanSyncEngine
    from app.services.room_channels import manager as room_channel_manager
    from app.services.synthesizer import SynthesizerEngine

    # Two engine kinds share the one summon seam. Each engine self-selects by the
    # summoned handle's manifest kind (and the aligner's reserved-handle
    # fallback), so a fan-out dispatcher is enough — no central kind table. Only
    # one engine ever acts per summon since a handle maps to a single kind.
    app.state.aligner = AlignerEngine(room_channel_manager)
    app.state.synthesizer = SynthesizerEngine(room_channel_manager)
    _engine_handlers = (
        app.state.aligner.handle_summon,
        app.state.synthesizer.handle_summon,
    )

    def _dispatch_summon(
        room: str,
        handle: str,
        envelope: Any,
        co_summons: list[str] | None = None,
        message_text: str = "",
    ) -> None:
        for fire in _engine_handlers:
            try:
                fire(room, handle, envelope, co_summons, message_text)
            except Exception:
                logger.exception("engine summon handler failed for @%s in %s", handle, room)

    room_channel_manager.on_summon = _dispatch_summon
    logger.info(
        "engines wired (aligner @%s, synthesizer @%s; brain=pi via %s)",
        app.state.aligner.handle,
        app.state.synthesizer.handle,
        settings.ALIGNER_PI_BINARY,
    )

    # Wire the converged→plan→memory-sync consumer onto the same seam:
    # a ``commit:converged`` the aligner emits fires plan_compiler → plan/tasks.md
    # and a ``knowledge`` push that syncs the compiled plan to every store.
    app.state.plan_sync = PlanSyncEngine(room_channel_manager)
    room_channel_manager.on_converged = app.state.plan_sync.handle_converged
    logger.info("plan-sync consumer wired (commit:converged → plan_compiler + knowledge)")

    # Re-provision every room's SLIM channel on startup. Provision is
    # idempotent and best-effort; without this, a backend restart left every
    # existing room channel-less (a zombie) with no recovery path until it was
    # deleted + recreated. Runs after the aligner/plan-sync hooks are wired so
    # each restarted persister picks them up.
    from app.services.filesystem import list_room_names

    reprovisioned = 0
    for _room in list_room_names():
        try:
            if await room_channel_manager.provision(_room) is not None:
                reprovisioned += 1
        except Exception:
            logger.exception("startup re-provision failed for room %s", _room)
    if reprovisioned:
        logger.info("re-provisioned %d room channel(s) on startup", reprovisioned)

    yield
    stop_watcher()
    stop_event_sweep()

    # Tear down long-lived SLIM room channels + the shared node connection so a
    # restart doesn't leak or reuse a stale dataplane connection.
    from app.services.room_channels import manager as room_channel_manager

    try:
        await room_channel_manager.close_all()
    except Exception as exc:  # pragma: no cover - best-effort teardown
        logger.warning("SLIM channel teardown failed (non-fatal): %s", exc)

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
    # The JWT gate rides every route rather than a hand-picked list, so a route
    # added later is protected without anyone remembering to opt it in. It is
    # inert unless AUTH_ENABLED is on, and exempts health/docs itself.
    dependencies=[Depends(auth_gate)],
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
app.include_router(agents_router, prefix="/api")
app.include_router(engines_router, prefix="/api")
app.include_router(rooms_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(invites_router, prefix="/api")
app.include_router(episodes_router, prefix="/api")
app.include_router(participate_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(stream_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(agent_context_router, prefix="/api")
app.include_router(users_router, prefix="/api")


@app.get("/", tags=["health"])
@app.get("/health", tags=["health"])
async def root(
    check_llm: bool = False,
    llm_probe: str = "provider",
):
    """Health check.

    Pass ``?check_llm=true`` to probe the LLM provider.  Without it, only local
    config status is included.

    Probe mode is selected by ``llm_probe`` (only relevant when check_llm=true):

    * ``provider`` (default) — zero-cost model-list call.  Free but only validates
      openai/anthropic/ollama; returns "unchecked" for bedrock/vertex/etc.
    * ``completion`` — real one-shot ``pi`` turn.  Exercises the same runtime as
      inference and surfaces a missing/broken ``pi`` binary, bad model strings,
      and endpoint-level auth failures.  Costs a single token.
    """
    from app.services.llm_health import get_config_status, probe_completion, probe_provider

    result: dict = {"status": "ok", "service": "mycelium-backend", "version": app.version}

    # Storage — markdown + local JSONL, no database.
    result["storage"] = _check_storage()

    # HTTP-API JWT gate — whether this hub is gated, and how.
    from app.services import auth as auth_service

    result["auth"] = auth_service.status()

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

    # Coordination fabric — channels/persisters/members (H1). Every smoke bug was
    # silent; this makes "is the fabric actually working" answerable in one GET.
    from app.services.room_channels import manager as room_channel_manager

    coordination = room_channel_manager.status()
    result["coordination"] = coordination

    overall_issues = []
    if result["storage"]["status"] != "ok":
        overall_issues.append("storage")
    if result["llm"]["status"] not in ("ok", "unchecked"):
        overall_issues.append("llm")
    # A live channel whose persister has died is a zombie room — surface it.
    if any(r["provisioned"] and not r["persister_alive"] for r in coordination["rooms"]):
        overall_issues.append("coordination")
    if overall_issues:
        result["status"] = "degraded"
        result["issues"] = overall_issues

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


def _check_storage() -> dict:
    """Probe the local markdown/JSONL data directory is writable."""
    from app.services.filesystem import get_data_dir

    try:
        data_dir = get_data_dir()
        return {"status": "ok", "message": "Local store", "path": str(data_dir)}
    except Exception as exc:
        logger.warning("Storage health check failed: %s", exc)
        return {"status": "unreachable", "message": f"Cannot access data dir: {type(exc).__name__}"}


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
