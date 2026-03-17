
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Coordination
    COORDINATION_LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_BASE_URL: str | None = None   # e.g. http://host.docker.internal:8099/
    ANTHROPIC_AUTH_TOKEN: str | None = None  # token for proxy (overrides ANTHROPIC_API_KEY)
    COORDINATION_JOIN_WINDOW_SECONDS: int = 60
    COORDINATION_TICK_TIMEOUT_SECONDS: int = 60

    # Embedding (for persistent memory semantic search)
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSIONS: int = 384

    # Room defaults
    DEFAULT_ROOM_MODE: str = "async"

    # Async CognitiveEngine synthesis
    SYNTHESIS_LLM_MODEL: str = "claude-sonnet-4-6"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
