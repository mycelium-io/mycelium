# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Config file search order: local .env first, then global ~/.mycelium/.env
_env_files = [".env"]
_global_env = Path.home() / ".mycelium" / ".env"
if _global_env.exists():
    _env_files.append(str(_global_env))


class Settings(BaseSettings):
    # OpenAPI docs
    OPENAPI_URL: str = "/openapi.json"

    # Database — single AgensGraph instance for SQL + graph + vector
    DATABASE_URL: str = "postgresql+asyncpg://postgres@localhost:5432/mycelium"
    EXPIRE_ON_COMMIT: bool = False

    # Graph DB — sync connection for openCypher queries (same DB, sync driver)
    GRAPH_DB_URL: str = "postgresql://postgres@localhost:5432/mycelium"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # Backend API (self-reference for inter-service calls)
    API_BASE_URL: str = "http://localhost:8000"

    # CORS — default for local dev; override in production via .env
    CORS_ORIGINS: set[str] = {"http://localhost:3000"}

    # LLM — uses litellm format: "provider/model" (e.g. anthropic/claude-sonnet-4-6, openai/gpt-4o, ollama/llama3)
    LLM_MODEL: str = "anthropic/claude-sonnet-4-6"
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None  # optional, for custom endpoints (ollama, vllm, etc.)

    # Coordination
    # How long to wait for additional agents to join after the first agent joins
    # a session before CognitiveEngine fires tick-0 (starts negotiation).
    COORDINATION_JOIN_WINDOW_SECONDS: int = 30
    # Each subsequent agent join pushes the deadline forward by this many
    # seconds (up to COORDINATION_JOIN_WINDOW_MAX_SECONDS total). Mirrors the
    # round-watchdog extension pattern: as long as new joins keep arriving the
    # window stays open, but a hard cap bounds total wait time. Set to 0 to
    # disable extension (fall back to fixed window).
    COORDINATION_JOIN_WINDOW_EXTENSION_SECONDS: int = 30
    COORDINATION_JOIN_WINDOW_MAX_SECONDS: int = 180
    # Per-round timeout: how long CognitiveEngine waits for an agent to reply
    # during a negotiation round before falling back to the safe default.
    COORDINATION_TICK_TIMEOUT_SECONDS: int = 30

    # Maximum SAO rounds per session. Passed to CFN /start as n_steps.
    # CFN's auto-compute formula assumes Boulware concession that LLM callback
    # agents don't exhibit; a low fixed cap keeps unconverged sessions from
    # burning rounds indefinitely. 0 = fall through to CFN auto-compute.
    NEGOTIATION_N_STEPS: int = 20

    @field_validator("LLM_BASE_URL", mode="before")
    @classmethod
    def _coerce_base_url(cls, v: object) -> object:
        """Treat empty string as unset — litellm and the OpenAI SDK both pass
        "" through to httpx which rejects it as UnsupportedProtocol."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("COORDINATION_TICK_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def _coerce_tick_timeout(cls, v: object) -> object:
        if v == "" or v is None:
            return 30
        return v

    # Filesystem-native memory storage
    # Root directory for .mycelium/ data (rooms, config)
    # Defaults to ~/.mycelium/ so backend and CLI share the same directory.
    MYCELIUM_DATA_DIR: str = str(Path.home() / ".mycelium")

    # Metrics collector (for proxying /api/observability/collector and /traces)
    COLLECTOR_URL: str = "http://mycelium-collector:4318"

    # Embedding (for persistent memory semantic search)
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSIONS: int = 384

    # IoC CFN management plane (optional — registration skipped if unset)
    CFN_MGMT_URL: str | None = None

    # IoC CFN cognition fabric node svc (required for session negotiation)
    COGNITION_FABRIC_NODE_URL: str = ""

    # Workspace ID in the CFN mgmt plane (set by mycelium install)
    WORKSPACE_ID: str = ""

    # Default MAS ID — fallback when ingest requests omit mas_id and room_name
    MAS_ID: str = ""

    # Knowledge ingest control surface. Master switch + per-payload caps.
    MYCELIUM_INGEST_ENABLED: bool = True
    MYCELIUM_INGEST_MAX_INPUT_TOKENS: int = 50_000
    MYCELIUM_INGEST_DEDUPE_TTL_SECONDS: int = 300
    # Skip ingest for trivially short content. Channel posts like "ack" or
    # a single emoji produce KG noise without value. Set 0 to ingest all.
    MYCELIUM_INGEST_MIN_CONTENT_CHARS: int = 32

    model_config = SettingsConfigDict(
        env_file=tuple(_env_files),
        env_file_encoding="utf-8",
        extra="ignore",
        # Compose sets LLM_API_KEY=${LLM_API_KEY:-}; without --env-file that becomes "" in
        # the container env and would override ~/.mycelium/.env. Ignore empty env vars.
        env_ignore_empty=True,
    )


settings = Settings()


class LLMUnavailableError(RuntimeError):
    """Raised when LLM is required but not configured."""

    def __init__(self) -> None:
        model = settings.LLM_MODEL
        super().__init__(
            f"LLM unavailable — no API key configured for {model}. "
            f"Set LLM_API_KEY (and optionally LLM_BASE_URL) in your .env."
        )


def require_llm() -> None:
    """Raise LLMUnavailableError if LLM is not configured.

    Ollama and other local providers (via LLM_BASE_URL) don't need an API key,
    so we only error when there's no key AND no custom base URL.
    """
    if not settings.LLM_API_KEY and not settings.LLM_BASE_URL:
        raise LLMUnavailableError
