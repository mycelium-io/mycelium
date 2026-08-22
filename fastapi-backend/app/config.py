# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where a registered engine runs its NEGMAS drive. Paired with the CLI's
# ``engine.runtime`` — flip both together.
EngineRuntime = Literal["backend", "host"]

# What a validated token's principal is. Distinguishing the two is what lets
# handle binding (#562) treat a human and a workload differently.
PrincipalRole = Literal["user", "agent"]


class TrustedIssuer(BaseModel):
    """One trust root the HTTP-API gate accepts tokens from.

    Trust is a *list* of these, matched by exact ``iss``, because more than one
    root is the normal case: the human OIDC issuer alongside (later) a workload
    trust root. Each entry carries its own keys, audience, and default role,
    so a new root is config, never issuer-specific code.
    """

    issuer: str
    # Omit to resolve the JWKS URI from ``<issuer>/.well-known/openid-configuration``.
    jwks_url: str | None = None
    # Overrides AUTH_AUDIENCE for tokens from this issuer.
    audience: str | None = None
    # Role for principals from this root when the token carries no role claim —
    # the load-bearing case, since which root signed a token usually *is* the
    # answer to user-vs-agent.
    role: PrincipalRole = "agent"

    @field_validator("issuer", "jwks_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


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

    # LLM — "provider/model" format (e.g. anthropic/claude-sonnet-4-6, openai/gpt-4o, ollama/llama3)
    LLM_MODEL: str = "anthropic/claude-sonnet-4-6"
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None  # optional, for custom endpoints (ollama, vllm, etc.)

    @field_validator("LLM_BASE_URL", mode="before")
    @classmethod
    def _coerce_base_url(cls, v: object) -> object:
        """Treat empty string as unset — the OpenAI SDK passes "" through to
        httpx which rejects it as UnsupportedProtocol."""
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
    # SLIM channel identity tier (off by default, #567). "psk" is the
    # shared-secret credential every room member derives (zero infra, no
    # per-agent identity). "signerjwt" opts into the SignerJwt floor (#476):
    # the moderator + each agent present a per-member self-signed ES256 identity
    # so members are cryptographically distinct, individually revocable MLS
    # participants. Surfaced here for discoverability; the slim_identity module
    # resolves it from MYCELIUM_SLIM_IDENTITY (env-only, like the master secret)
    # so the CLI mirror agrees without config coupling.
    SLIM_IDENTITY: str = "psk"

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
    # Pre-negotiation term check — one cheap brain call over the opening positions
    # looking for a word two agents use in different senses, and one clarifying
    # round when it finds any. On by default: a room that shares its vocabulary
    # pays a single call and negotiates exactly as before. Off skips the check.
    ALIGNER_TERM_CHECK: bool = True
    # Mediator brain runtime — the cognitive engine behind the SAO
    # mediator, an *internal* agent — always a persistent, optionally
    # OpenShell-sandboxed `pi -p --session <id> --mode json` session that gives the
    # internal agent real memory across SAO rounds (the anti-theatre property).
    # This is ONLY the runtime for mycelium's own cognition engines; user/participant
    # agent runtimes (claude_code, cursor, …) are untouched and keep their own runtime.
    # Path/name of the `pi` binary the mediator brain runs.
    ALIGNER_PI_BINARY: str = "pi"
    # Wrap each pi session in an OpenShell sandbox when true. Off by default:
    # `openshell` may not be installed and the sandbox path is a live-validation
    # step — the wrap is a config flip, not a code change (pi_brain._sandbox_wrap).
    ALIGNER_PI_OPENSHELL: bool = False
    # Per-turn wall-clock bound (seconds) on one pi brain call before it is killed.
    ALIGNER_PI_TIMEOUT_S: float = 120.0
    # Synthesizer engine (kind ``synthesizer``) — reads a room's memory and
    # compiles a structured summary as a ``knowledge`` memory. Dormant by
    # default like the aligner: nothing runs until a registered synthesizer
    # engine is @-summoned. Reuses the shared LLM_* + ALIGNER_PI_* Pi runtime
    # settings; only its own handle default and per-turn timeout live here.
    SYNTHESIZER_HANDLE: str = "synthesizer"
    # Per-turn wall-clock bound (seconds) on the synthesizer's one-shot pi call.
    SYNTHESIZER_PI_TIMEOUT_S: float = 120.0
    # Summonguard engine (kind ``summonguard``) — classifies each ``@``-mention as
    # a summon or provenance, so a room stops waking agents that were merely named.
    # Dormant like the others: nothing runs until a guard is registered in a room,
    # and every failure path wakes rather than suppresses.
    SUMMONGUARD_HANDLE: str = "summonguard"
    # Per-message wall-clock bound (seconds) on the guard's one-shot pi call.
    # Short: this sits between a message and an agent's turn, so a slow
    # classification is worse than a fail-open wake.
    SUMMONGUARD_PI_TIMEOUT_S: float = 20.0
    # How long an ``await`` long-poll waits for an in-flight summon-filter
    # judgement before serving the turn anyway. A property of the seam rather than
    # of any one guard, so it is named for the extension point. Absorbed by the
    # poll, invisible to the caller.
    SUMMON_FILTER_WAIT_S: float = 8.0
    # Kill switch: registered guards stay listed but classify everything as a wake,
    # so a misbehaving guard is disarmed without editing a room's manifests.
    SUMMONGUARD_DISABLE: bool = False

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

    # ── HTTP-API JWT gate ────────────────────────────────────────────────────
    # Off by default, and that is a hard requirement rather than a default worth
    # revisiting: auth must never stand between someone and trying the app.
    # With AUTH_ENABLED false the gate is inert and every request is anonymous
    # — exactly today's behavior.
    AUTH_ENABLED: bool = False
    # Trust roots, as JSON over env:
    #   AUTH_ISSUERS=[{"issuer":"https://idp/realm","jwks_url":"…","role":"user"}]
    AUTH_ISSUERS: list[TrustedIssuer] = []
    # Required ``aud`` when set; unset means the claim is not checked. A trusted
    # issuer entry may override it.
    AUTH_AUDIENCE: str | None = None
    # Skip the gate for real loopback callers so an operator who turns auth on
    # doesn't lock themselves out of the machine the hub runs on. Decided by the
    # request's client address, never the bind address — see services/auth.py.
    AUTH_LOCALHOST_BYPASS: bool = True
    # Which claim carries the canonical @handle, and which carries user-vs-agent.
    AUTH_HANDLE_CLAIM: str = "sub"
    AUTH_ROLE_CLAIM: str = "mycelium_role"
    # Clock-skew allowance (seconds) on exp/nbf/iat.
    AUTH_LEEWAY_S: float = 60.0
    # How long a fetched JWKS is served from cache before it is re-fetched.
    AUTH_JWKS_TTL_S: float = 300.0

    @field_validator("AUTH_AUDIENCE", mode="before")
    @classmethod
    def _coerce_audience(cls, v: object) -> object:
        """Treat an empty string as "don't check aud" — compose renders an unset
        audience as ``AUTH_AUDIENCE=``, which must not become a literal ""
        audience that no token can ever match."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    model_config = SettingsConfigDict(
        env_file=tuple(_env_files),
        env_file_encoding="utf-8",
        extra="ignore",
        # Compose sets LLM_API_KEY=${LLM_API_KEY:-}; without --env-file that becomes "" in
        # the container env and would override ~/.mycelium/.env. Ignore empty env vars.
        env_ignore_empty=True,
    )


settings = Settings()
