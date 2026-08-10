# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where a registered engine runs its NEGMAS drive. Paired with the CLI's
# ``engine.runtime`` — flip both together.
EngineRuntime = Literal["backend", "host"]

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

    # SLIM fabric — the coordination bus. Room provisioning is
    # best-effort: when no node is reachable at this endpoint the backend simply
    # skips channel provisioning, so memory/CRUD keep working without a fabric.
    SLIM_NODE_ENDPOINT: str = "http://127.0.0.1:46357"
    # Default SLIM org/workspace segment for a room whose meta carries no
    # workspace_id (org=workspace, namespace=room, app=agent).
    SLIM_WORKSPACE: str = "mycelium"
    # Master toggle: set false to disable SLIM room provisioning outright.
    SLIM_ENABLED: bool = True

    # SIEP aligner — the first cognition engine. Dormant by default:
    # nothing runs until the reserved handle is @-summoned on a room channel.
    # A reserved handle is how a summon of the engine is told apart from an
    # @-mention of a normal teammate.
    ALIGNER_HANDLE: str = "aligner"
    # MPC at/above this converges; below rejects (mirrors the old CFN
    # validation-intervention default of 0.6).
    ALIGNER_THRESHOLD: float = 0.6
    # Driver round cap — a hard bound so the loop always terminates.
    ALIGNER_MAX_ROUNDS: int = 3
    # Per-round wait for participant replies before scoring what arrived.
    ALIGNER_ROUND_TIMEOUT_S: float = 30.0
    # How often the driver polls the transcript for round replies.
    ALIGNER_POLL_INTERVAL_S: float = 0.2
    # Mediator — hard cap on NEGMAS SAO steps (one agent turn each) so
    # the negotiation always terminates even if agreement is never reached. Set
    # well above the participant count so several proposer rotations can happen
    # (spike used 20).
    ALIGNER_MEDIATOR_MAX_STEPS: int = 20
    # Mediator brain runtime — the cognitive engine behind the SAO
    # mediator, an *internal* agent — always a persistent, optionally
    # OpenShell-sandboxed `pi -p --session <id> --mode json` session that gives the
    # internal agent real memory across SAO rounds (the anti-theatre property).
    # This is ONLY mycelium's own cognition runtime — user/participant agent
    # runtimes (claude_code, cursor, …) are untouched; Pi is never imposed on them.
    # Path/name of the `pi` binary the mediator brain runs.
    ALIGNER_PI_BINARY: str = "pi"
    # Wrap each pi session in an OpenShell sandbox when true. Off by default:
    # `openshell` may not be installed and the sandbox path is a live-validation
    # step — the wrap is a config flip, not a code change (pi_brain._sandbox_wrap).
    ALIGNER_PI_OPENSHELL: bool = False
    # Per-turn wall-clock bound (seconds) on one pi brain call before it is killed.
    ALIGNER_PI_TIMEOUT_S: float = 120.0
    # Where a registered `engine` (kind aligner) runs its NEGMAS drive — selects
    # the engine runtime. "backend" (default):
    # this backend owns the run via its summon seam. "host": the host daemon owns
    # it (the engine runs where `pi` lives), so `handle_summon` must NOT also fire
    # for a registered engine or the negotiation double-runs. The reserved
    # ALIGNER_HANDLE fallback always runs backend-side (it has no host manifest).
    # Flip this in tandem with the CLI's `engine.runtime` — they're a pair.
    ENGINE_RUNTIME: EngineRuntime = "backend"

    @field_validator("ENGINE_RUNTIME", mode="before")
    @classmethod
    def _normalize_engine_runtime(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

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
