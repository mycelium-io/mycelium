# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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

    @field_validator("LLM_BASE_URL", mode="before")
    @classmethod
    def _coerce_base_url(cls, v: object) -> object:
        """Treat empty string as unset — litellm and the OpenAI SDK both pass
        "" through to httpx which rejects it as UnsupportedProtocol."""
        if isinstance(v, str) and v.strip() == "":
            return None
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
