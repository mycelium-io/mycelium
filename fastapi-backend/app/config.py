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
    # Per-agent base budget for the per-round watchdog. The initial deadline
    # for a round is BASE * N + STARTUP. Set high enough to cover a typical
    # LLM agent's read-tick → narrate → run-CLI cycle (15-60s).
    COORDINATION_TICK_TIMEOUT_SECONDS: int = 45
    # Constant added on top of BASE * N for the initial round deadline. Covers
    # gateway routing, model cold start, and the first network leg.
    COORDINATION_ROUND_STARTUP_SECONDS: int = 30
    # When a new (real, non-synthesised) reply arrives mid-round, extend the
    # watchdog by EXTENSION * remaining_handles, but never less than FLOOR.
    # Bounded above by COORDINATION_ROUND_MAX_SECONDS.
    COORDINATION_ROUND_EXTENSION_PER_REMAINING_SECONDS: int = 30
    COORDINATION_ROUND_EXTENSION_FLOOR_SECONDS: int = 20
    # Hard cap on total wall time per round, regardless of activity. Prevents
    # one wedged agent from blocking the negotiation indefinitely.
    COORDINATION_ROUND_MAX_SECONDS: int = 300

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
            return 45
        return v

    _ROUND_TIMER_DEFAULTS = {
        "COORDINATION_ROUND_STARTUP_SECONDS": 30,
        "COORDINATION_ROUND_EXTENSION_PER_REMAINING_SECONDS": 30,
        "COORDINATION_ROUND_EXTENSION_FLOOR_SECONDS": 20,
        "COORDINATION_ROUND_MAX_SECONDS": 300,
    }

    @field_validator(
        "COORDINATION_ROUND_STARTUP_SECONDS",
        "COORDINATION_ROUND_EXTENSION_PER_REMAINING_SECONDS",
        "COORDINATION_ROUND_EXTENSION_FLOOR_SECONDS",
        "COORDINATION_ROUND_MAX_SECONDS",
        mode="before",
    )
    @classmethod
    def _coerce_round_timer_int(cls, v: object, info) -> object:  # type: ignore[no-untyped-def]
        if v == "" or v is None:
            return cls._ROUND_TIMER_DEFAULTS[info.field_name]
        return v

    # Filesystem-native memory storage
    # Root directory for .mycelium/ data (rooms, notebooks, config)
    # Defaults to ~/.mycelium/ so backend and CLI share the same directory.
    MYCELIUM_DATA_DIR: str = str(Path.home() / ".mycelium")

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

    # Knowledge ingest control surface — see KnowledgeIngestConfig in the CLI
    # for the authoritative descriptions. Defaults here match CLI defaults.
    MYCELIUM_INGEST_ENABLED: bool = True
    MYCELIUM_INGEST_MAX_INPUT_TOKENS: int = 50_000
    MYCELIUM_INGEST_DEDUPE_TTL_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=tuple(_env_files),
        env_file_encoding="utf-8",
        extra="ignore",
        # Compose sets LLM_API_KEY=${LLM_API_KEY:-}; without --env-file that becomes "" in
        # the container env and would override ~/.mycelium/.env. Ignore empty env vars.
        env_ignore_empty=True,
    )


settings = Settings()  # type: ignore[call-arg]


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
