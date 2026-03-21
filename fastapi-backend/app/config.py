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
    # Per-round timeout: how long CognitiveEngine waits for an agent to reply
    # during a negotiation round before falling back to the safe default.
    COORDINATION_TICK_TIMEOUT_SECONDS: int = 30

    @field_validator("COORDINATION_TICK_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def _coerce_tick_timeout(cls, v: object) -> object:
        if v == "" or v is None:
            return 30
        return v

    # Embedding (for persistent memory semantic search)
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSIONS: int = 384

    # IoC CFN management plane (optional — registration skipped if unset)
    CFN_MGMT_URL: str | None = None

    model_config = SettingsConfigDict(
        env_file=tuple(_env_files), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
