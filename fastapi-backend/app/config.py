
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # OpenAPI docs
    OPENAPI_URL: str = "/openapi.json"

    # Database — set via DATABASE_URL env var or .env file
    DATABASE_URL: str = "postgresql+asyncpg://postgres@localhost:5432/mycelium"
    EXPIRE_ON_COMMIT: bool = False

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # Backend API (self-reference for inter-service calls)
    API_BASE_URL: str = "http://localhost:8000"

    # AgensGraph (knowledge graph DB) — set via GRAPH_DB_URL env var or .env file
    GRAPH_DB_URL: str = "postgresql://postgres@localhost:5456/ioc-graph-db"

    # CORS — default for local dev; override in production via .env
    CORS_ORIGINS: set[str] = {"http://localhost:3000"}

    # Coordination
    COORDINATION_LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_BASE_URL: str | None = None   # e.g. http://host.docker.internal:8099/
    ANTHROPIC_AUTH_TOKEN: str | None = None  # token for proxy (overrides ANTHROPIC_API_KEY)
    COORDINATION_JOIN_WINDOW_SECONDS: int = 60
    COORDINATION_TICK_TIMEOUT_SECONDS: int = 60

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
