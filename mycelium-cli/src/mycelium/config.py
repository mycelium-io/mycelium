# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Configuration management for Mycelium CLI.

Supports two config locations (like git):
1. Global: ~/.mycelium/config.toml - identity, server settings
2. Project-local: ./.mycelium/config.toml - room settings

Load priority (highest to lowest):
1. Command-line flags
2. Environment variables
3. Project-local config (./.mycelium/)
4. Global config (~/.mycelium/)
5. Defaults
"""

import os
import warnings
from pathlib import Path
from typing import Any

import toml
from pydantic import BaseModel, Field, field_validator

from mycelium.protocol import EngineRuntime

# Header key prepended to every ~/.mycelium/config.json write. Strict JSON has no
# comment syntax; ``"//"`` is the npm/package.json convention for documentation
# keys and every consumer ignores it (they look up known sections by name). The
# key leads so it's the first thing a user sees on `cat`.
_JSON_HEADER_KEY = "//"
_JSON_HEADER_VALUE = (
    "DO NOT EDIT: auto-generated from ~/.mycelium/config.toml on every save. "
    "Edit config.toml instead, or use `mycelium config set`. "
    "Any edits here are silently overwritten on the next save."
)


class IdentityConfig(BaseModel):
    """Agent identity configuration."""

    name: str | None = Field(
        default=None,
        description="Display name chosen by user",
    )
    machine_id: str | None = Field(
        default=None,
        description="Stable UUID for machine affinity (generated on first use)",
    )
    autonomous: bool = Field(
        default=False,
        description="True when running as an autonomous agent",
    )


class ServerConfig(BaseModel):
    """Server connection configuration."""

    api_url: str = Field(
        default="http://localhost:8000",
        description="Mycelium backend API URL",
    )

    @field_validator("api_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URLs don't have trailing slashes."""
        return v.rstrip("/")


class SlimConfig(BaseModel):
    """SLIM messaging-fabric connection configuration.

    ``node_endpoint`` is the address of the ``slim`` node this agent connects
    to. It's the same value whether the node is self-hosted (``mycelium hub
    host``) or a shared mycelium-hosted rendezvous; set it with ``mycelium
    connect <address>``. MLS makes the node a blind ciphertext forwarder, so the
    host is untrusted either way.
    """

    node_endpoint: str = Field(
        default="http://127.0.0.1:46357",
        description="SLIM node endpoint (host:port), e.g. http://127.0.0.1:46357",
    )

    identity: str = Field(
        default="psk",
        description=(
            "SLIM channel identity tier: 'psk' (default, off-by-default #567) is the "
            "shared-secret credential every room member derives (zero infra, no "
            "per-agent identity). 'signerjwt' opts into the SignerJwt floor (#476): "
            "each member presents a per-agent self-signed ES256 identity so members "
            "are cryptographically distinct, individually revocable MLS "
            "participants. Selecting 'signerjwt' with no resolvable material "
            "degrades to 'psk' unless MYCELIUM_SLIM_IDENTITY_REQUIRE=1 fails closed."
        ),
    )

    master_secret: str | None = Field(
        default=None,
        description=(
            "Hub-only SLIM PSK master secret. Auto-generated on first "
            "``mycelium config apply`` / install when unset; rendered to "
            "``MYCELIUM_SLIM_MASTER_SECRET`` in ~/.mycelium/.env for the backend "
            "container. Spokes do not need this. Override with "
            "``mycelium config set slim.master_secret …`` to rotate."
        ),
    )

    @field_validator("master_secret")
    @classmethod
    def _validate_master_secret(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return None
        if len(stripped) < 32:
            raise ValueError("slim.master_secret must be at least 32 characters")
        return stripped

    @field_validator("identity")
    @classmethod
    def _validate_identity(cls, v: str) -> str:
        """Only ``psk`` / ``signerjwt`` are valid identity tiers.

        The retired ``spire`` tier (#668) degrades to ``psk`` with a warning rather
        than raising: a config written before the removal would otherwise fail every
        command, including the ``config set`` needed to correct it.
        """
        normalized = v.strip().lower()
        if normalized == "spire":
            warnings.warn(
                "slim.identity='spire' has been retired; falling back to 'psk'. "
                "Set slim.identity to 'psk' or 'signerjwt' to silence this.",
                stacklevel=2,
            )
            return "psk"
        if normalized not in ("psk", "signerjwt"):
            raise ValueError(f"slim.identity must be 'psk' or 'signerjwt', got {v!r}")
        return normalized

    @field_validator("node_endpoint")
    @classmethod
    def normalize_endpoint(cls, v: str) -> str:
        """Ensure the endpoint carries a scheme and no trailing slash."""
        v = v.strip().rstrip("/")
        if v and "://" not in v:
            v = f"http://{v}"
        return v


class LLMConfig(BaseModel):
    """LLM configuration ("provider/model" format)."""

    model: str | None = Field(
        default=None,
        description="LLM model in provider/model format (e.g. anthropic/claude-sonnet-4-6)",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for the LLM provider",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL for LLM endpoint (ollama, vllm, etc.)",
    )


class EngineConfig(BaseModel):
    """First-party Cognition Engine runtime configuration.

    ``runtime`` is ``backend``-only: the always-on backend owns a registered
    engine's run via its summon seam. (The ``host`` runtime rode the daemon,
    which has been removed; legacy ``host`` config coerces to ``backend``.)
    """

    runtime: EngineRuntime = Field(
        default="backend",
        description="Where registered engines run their drive (backend-only).",
    )

    @field_validator("runtime", mode="before")
    @classmethod
    def _normalize_runtime(cls, v: object) -> object:
        # Normalize casing/whitespace; coerce 'host' to 'backend' for backward compatibility.
        if isinstance(v, str):
            normalized = v.strip().lower()
            return "backend" if normalized == "host" else normalized
        return v


class TrustedIssuer(BaseModel):
    """One trust root the backend's HTTP-API gate accepts tokens from.

    Configured as a repeatable ``[[auth.issuers]]`` block. More than one root is
    the normal case (a human OIDC issuer alongside an agent/service-account one),
    and each carries its own keys, audience, and default role, so adding a root
    is config rather than code.
    """

    issuer: str = Field(
        ...,
        description="Exact `iss` claim value to trust, e.g. https://idp.example.com/realms/mycelium",
    )
    jwks_url: str | None = Field(
        default=None,
        description="JWKS URL for this issuer. Omit to resolve it from the issuer's OIDC discovery document.",
    )
    audience: str | None = Field(
        default=None,
        description="Required `aud` for tokens from this issuer; overrides auth.audience.",
    )
    role: str = Field(
        default="agent",
        description="Role ('user' or 'agent') for principals from this issuer when the token carries no role claim.",
    )

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in ("user", "agent"):
            raise ValueError("role must be 'user' or 'agent'")
        return normalized

    @field_validator("issuer", "jwks_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class AuthConfig(BaseModel):
    """HTTP-API JWT gate, off by default.

    The backend validates a bearer token against a configured issuer + JWKS. It
    ships **disabled**: auth must never stand between someone and trying
    Mycelium, so the default stack needs no issuer and no tokens. Turning it on
    is a per-deployment decision for when a team shares a hub over a network.

    When enabling it, set ``audience`` as well. Without one, *any* token a
    trusted issuer ever minted is accepted, including tokens a user obtained
    for an unrelated application on the same IdP. The audience is what makes
    "valid token" mean "token meant for this hub".
    """

    enabled: bool = Field(
        default=False,
        description="Enforce bearer-token auth on the backend HTTP API.",
    )
    issuers: list[TrustedIssuer] = Field(
        default_factory=list,
        description="Trust roots, as repeatable [[auth.issuers]] blocks.",
    )
    audience: str | None = Field(
        default=None,
        description="Required `aud` claim for every token. Strongly recommended whenever auth is enabled; unset means the audience is not checked.",
    )
    localhost_bypass: bool = Field(
        default=True,
        description="Let loopback callers through without a token, so enabling auth can't lock an operator out of the hub machine. Does not apply to a backend in Docker, whose callers arrive from the bridge gateway rather than loopback.",
    )
    handle_claim: str = Field(
        default="sub",
        description="Token claim carrying the canonical @handle.",
    )
    role_claim: str = Field(
        default="mycelium_role",
        description="Token claim distinguishing a user from an agent.",
    )
    leeway_s: float = Field(
        default=60.0,
        description="Clock-skew allowance in seconds on exp/nbf/iat.",
    )
    jwks_ttl_s: float = Field(
        default=300.0,
        description="How long a fetched JWKS is cached before re-fetch. Key rotation is also picked up on an unseen kid.",
    )


class LoginConfig(BaseModel):
    """Where ``mycelium login`` gets a human's token: the client side of auth.

    Distinct from :class:`AuthConfig`, which configures the *hub's* gate: this
    section says which issuer this machine logs in against, that one says which
    issuers the backend trusts. A spoke needs only this half.

    Unset ``issuer`` means "no login configured", which is the default: the CLI
    sends no token and behaves exactly as it does with no identity at all.
    """

    issuer: str | None = Field(
        default=None,
        description="OIDC issuer to log in against, e.g. https://sso.example.com/realms/mycelium",
    )
    client_id: str = Field(
        default="mycelium-cli",
        description="OAuth client id registered for the CLI at that issuer.",
    )
    client_secret: str | None = Field(
        default=None,
        description="Client secret, only for issuers that refuse public clients. PKCE means the CLI normally needs none.",
    )
    scopes: str = Field(
        default="openid profile email offline_access",
        description="Space-separated scopes to request. 'offline_access' is what gets a refresh token from most issuers.",
    )
    audience: str | None = Field(
        default=None,
        description="Audience to request for the token; should match the hub's auth.audience.",
    )
    redirect_port: int = Field(
        default=0,
        description="Fixed loopback port for the browser redirect (0 = pick a free one). Set this when the issuer requires an exact registered redirect URI.",
    )

    @field_validator("issuer")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class AgentAuthConfig(BaseModel):
    """Where an *agent* gets its own token: the workload half of the client side.

    An agent is not a human: no browser, no consent screen, and nobody to run
    ``mycelium login`` on its behalf. Its credential is its own OIDC client
    (``client_credentials``), so the token's ``sub`` is the client id, which is
    the agent's handle, the same handle the hub binds its writes to.

    This section holds only what is *shared* by every agent on the machine (the
    issuer and the audience to ask for). The per-agent half (which client id an
    agent is, and its secret) is a secret, so it lives in the ``0600`` store
    behind ``mycelium agent credential set``, never in ``config.toml``.

    Unset ``issuer`` means "no agent credentials configured", which is the
    default: agents send no token, exactly as before.
    """

    issuer: str | None = Field(
        default=None,
        description="OIDC issuer agents mint their service-account tokens from. Unset (default) means agents send no token.",
    )
    scopes: str | None = Field(
        default=None,
        description="Space-separated scopes to request for an agent token. Unset sends none, which is what most issuers want for client_credentials.",
    )
    audience: str | None = Field(
        default=None,
        description="Audience to request for agent tokens; should match the hub's auth.audience.",
    )

    @field_validator("issuer")
    @classmethod
    def _strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if isinstance(v, str) else v


class RuntimeConfig(BaseModel):
    """Docker runtime / environment configuration."""

    backend_port: int = Field(
        default=8000,
        description="Host port for the backend API",
    )
    collector_port: int = Field(
        default=4318,
        description="Host port for the OTLP metrics collector",
    )
    frontend_port: int = Field(
        default=3000,
        description="Host port for the frontend UI",
    )
    allowed_dev_origins: str = Field(
        default="",
        description=(
            "Comma-separated origins the Next.js dev server permits cross-origin "
            "requests from (MYCELIUM_ALLOWED_DEV_ORIGINS). Add your public IP or "
            "hostname when running `mycelium up` (or pnpm dev) behind a reverse "
            "proxy or NAT and accessing the UI from a browser on a different host. "
            "Production Docker builds do not use this — the browser always hits its "
            "own origin. Example: mycelium config set runtime.allowed_dev_origins "
            "'3.139.30.16' or '3.139.30.16,10.0.0.5'"
        ),
    )
    data_dir: str | None = Field(
        default=None,
        description="Root directory for .mycelium/ data (defaults to ~/.mycelium)",
    )
    trusted_proxies: str = Field(
        default="",
        description=(
            "Which forwarders the backend may believe about the original request "
            "(rendered as uvicorn's FORWARDED_ALLOW_IPS). Empty (the default) trusts "
            "only loopback, so a direct caller cannot spoof X-Forwarded-Proto and "
            "make the hub advertise a scheme it is not served on. Set it when a "
            "TLS-terminating reverse proxy fronts the backend, otherwise every "
            "absolute URL the hub generates (the A2A agent card's `url` most "
            "visibly) comes out http:// on an https:// deployment. Use '*' when the "
            "backend is only reachable through that proxy, or a comma-separated list "
            "of proxy addresses. Example: mycelium config set "
            "runtime.trusted_proxies '*'"
        ),
    )


class RoomConfig(BaseModel):
    """Room management configuration."""

    active: str | None = Field(
        default=None,
        description="Currently active room name",
    )


class ScrapeTarget(BaseModel):
    """A Prometheus ``/metrics`` endpoint for the collector to poll.

    Configured under ``[[metrics.scrape]]`` in ``config.toml``::

        [[metrics.scrape]]
        name = "my-service"
        url  = "http://localhost:9000/metrics"
        kind = "http_red"   # default; rolls up prometheus-fastapi-instrumentator series

    The collector polls every target on the same 30s cadence as the backend
    and stores results under the top-level ``scrape`` key in
    ``$MYCELIUM_DATA_DIR/metrics/metrics.json``. Targets unreachable at scrape time are
    preserved with ``data: null`` so the display panel can show "degraded"
    rather than silently dropping them.
    """

    name: str = Field(
        ...,
        description="Stable, short identifier used as the dict key in metrics.json and as the panel label.",
        min_length=1,
        max_length=64,
    )
    url: str = Field(
        ...,
        description="Full URL of the Prometheus exposition endpoint (typically ending in /metrics).",
    )
    kind: str = Field(
        default="http_red",
        description=(
            "Roll-up strategy: 'http_red' (HTTP rate/error/duration, e.g. "
            "prometheus-fastapi-instrumentator) or 'grpc_red' (gRPC RED, e.g. the "
            "OpenShell gateway's *_grpc_requests_total + *_grpc_request_duration_seconds)."
        ),
    )


class A2aConfig(BaseModel):
    """Configuration for the A2A bridge (outbound + inbound Agent2Agent gateway).

    The default settings are safe for a public-facing deployment: the SSRF guard
    refuses card URLs that resolve to private, loopback, or link-local addresses
    so a misconfigured or attacker-supplied card URL can't probe the internal
    network. Only set ``allow_private_hosts = true`` for a deployment where all
    A2A agents are on the internal network and you trust every registrar.
    """

    allow_private_hosts: bool = Field(
        default=False,
        description=(
            "Disable the SSRF guard that refuses A2A card URLs resolving to private, "
            "loopback, or link-local addresses. Only set this for a trusted internal "
            "deployment whose A2A agents live on the internal network."
        ),
    )


class MetricsConfig(BaseModel):
    """Configuration for the metrics collector + display.

    Use ``[[metrics.scrape]]`` to add Prometheus ``/metrics`` targets (e.g. a
    user's own instrumented service) for the collector to poll.

    On spoke nodes, set ``collector_url`` to the hub's collector address
    (e.g. ``http://hub-ip:4318``). This makes ``mycelium metrics show``
    fetch data from the hub and sets the default OTLP endpoint for
    adapter plugins; no local collector needed.
    """

    collector_url: str | None = Field(
        default=None,
        description=(
            "URL of the hub OTLP collector (e.g. http://hub-ip:4318). "
            "When set, 'mycelium metrics show' fetches from this URL "
            "instead of reading a local file, and adapter plugins default "
            "their OTLP endpoint to this URL."
        ),
    )
    scrape: list[ScrapeTarget] = Field(
        default_factory=list,
        description="Explicit Prometheus /metrics endpoints for the collector to scrape.",
    )


class MyceliumConfig(BaseModel):
    """Complete Mycelium CLI configuration."""

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    slim: SlimConfig = Field(default_factory=SlimConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    login: LoginConfig = Field(default_factory=LoginConfig)
    agent_auth: AgentAuthConfig = Field(default_factory=AgentAuthConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rooms: RoomConfig = Field(default_factory=RoomConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    a2a: A2aConfig = Field(default_factory=A2aConfig)
    adapters: dict[str, Any] = Field(
        default_factory=dict,
        description="Registered agent framework adapters (claude-code, cursor, …)",
    )

    model_config = {"arbitrary_types_allowed": True}
    _global_config_path: Path | None = None
    _project_config_path: Path | None = None

    @classmethod
    def get_global_config_dir(cls) -> Path:
        return Path.home() / ".mycelium"

    @classmethod
    def get_global_config_path(cls) -> Path:
        return cls.get_global_config_dir() / "config.toml"

    @classmethod
    def get_logs_dir(cls) -> Path:
        logs_dir = cls.get_global_config_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @classmethod
    def get_project_config_dir(cls) -> Path:
        return Path.cwd() / ".mycelium"

    @classmethod
    def get_project_config_path(cls) -> Path:
        return cls.get_project_config_dir() / "config.toml"

    @classmethod
    def find_project_config(cls) -> Path | None:
        """Find project-local .mycelium/ by walking up directory tree."""
        global_dir = cls.get_global_config_dir()
        current = Path.cwd()
        while current != current.parent:
            config_path = current / ".mycelium" / "config.toml"
            if config_path.exists() and config_path.parent != global_dir:
                return config_path
            current = current.parent
        return None

    @classmethod
    def has_project_config(cls) -> bool:
        return cls.find_project_config() is not None

    @classmethod
    def get_config_path(cls) -> Path:
        project_config = cls.find_project_config()
        return project_config if project_config else cls.get_global_config_path()

    @classmethod
    def get_config_dir(cls) -> Path:
        project_config = cls.find_project_config()
        if project_config:
            return project_config.parent
        return cls.get_global_config_dir()

    @classmethod
    def load(cls, config_path: Path | None = None) -> "MyceliumConfig":
        """Load configuration from global and project-local files."""
        config_dict: dict[str, Any] = {}

        if config_path is not None:
            if config_path.exists():
                with open(config_path) as f:
                    config_dict = toml.load(f)
            global_path = config_path
            project_path = None
        else:
            global_path = cls.get_global_config_path()
            if global_path.exists():
                with open(global_path) as f:
                    config_dict = toml.load(f)

            project_path = cls.find_project_config()
            if project_path and project_path.exists():
                with open(project_path) as f:
                    project_dict = toml.load(f)
                config_dict = cls._deep_merge(config_dict, project_dict)

        env_overrides = cls._load_from_env()
        config_dict = cls._deep_merge(config_dict, env_overrides)

        instance = cls(**config_dict)
        instance._global_config_path = global_path
        instance._project_config_path = project_path
        return instance

    @classmethod
    def _load_from_env(cls) -> dict[str, Any]:
        """Load configuration overrides from environment variables."""
        env_config: dict[str, Any] = {
            "server": {},
            "slim": {},
            "rooms": {},
            "llm": {},
            "engine": {},
            "login": {},
            "agent_auth": {},
            "runtime": {},
            "metrics": {},
        }

        if engine_runtime := os.getenv("ENGINE_RUNTIME"):
            env_config["engine"]["runtime"] = engine_runtime

        if api_url := os.getenv("MYCELIUM_API_URL"):
            env_config["server"]["api_url"] = api_url
        if slim_endpoint := os.getenv("MYCELIUM_SLIM_ENDPOINT"):
            env_config["slim"]["node_endpoint"] = slim_endpoint
        if slim_master := os.getenv("MYCELIUM_SLIM_MASTER_SECRET"):
            env_config["slim"]["master_secret"] = slim_master
        if slim_identity := os.getenv("MYCELIUM_SLIM_IDENTITY"):
            env_config["slim"]["identity"] = slim_identity
        if active_room := os.getenv("MYCELIUM_ACTIVE_ROOM"):
            env_config["rooms"]["active"] = active_room

        # LLM overrides
        if llm_model := os.getenv("LLM_MODEL"):
            env_config["llm"]["model"] = llm_model
        if llm_api_key := os.getenv("LLM_API_KEY"):
            env_config["llm"]["api_key"] = llm_api_key
        if llm_base_url := os.getenv("LLM_BASE_URL"):
            env_config["llm"]["base_url"] = llm_base_url

        # Login (OIDC client) overrides: how a CI runner points `mycelium login`
        # at an issuer without writing a config file.
        if login_issuer := os.getenv("MYCELIUM_LOGIN_ISSUER"):
            env_config["login"]["issuer"] = login_issuer
        if login_client_id := os.getenv("MYCELIUM_LOGIN_CLIENT_ID"):
            env_config["login"]["client_id"] = login_client_id
        if login_client_secret := os.getenv("MYCELIUM_LOGIN_CLIENT_SECRET"):
            env_config["login"]["client_secret"] = login_client_secret
        if login_audience := os.getenv("MYCELIUM_LOGIN_AUDIENCE"):
            env_config["login"]["audience"] = login_audience
        if login_scopes := os.getenv("MYCELIUM_LOGIN_SCOPES"):
            env_config["login"]["scopes"] = login_scopes

        # Agent (service-account) overrides: how a container hands its agent an
        # issuer without a config file. The per-agent client id and secret are
        # secrets and stay out of config; see `mycelium.agent_credentials`.
        if agent_issuer := os.getenv("MYCELIUM_AGENT_AUTH_ISSUER"):
            env_config["agent_auth"]["issuer"] = agent_issuer
        if agent_scopes := os.getenv("MYCELIUM_AGENT_AUTH_SCOPES"):
            env_config["agent_auth"]["scopes"] = agent_scopes
        if agent_audience := os.getenv("MYCELIUM_AGENT_AUTH_AUDIENCE"):
            env_config["agent_auth"]["audience"] = agent_audience

        # Metrics overrides
        if collector_url := os.getenv("MYCELIUM_COLLECTOR_URL"):
            env_config["metrics"]["collector_url"] = collector_url

        return env_config

    @classmethod
    def _deep_merge(cls, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            elif value is not None:
                result[key] = value
        return result

    def resolve_scrape_targets(self) -> list[dict]:
        """Return the list of Prometheus scrape targets for the collector.

        Targets are the explicit ``[[metrics.scrape]]`` entries declared in
        ``config.toml`` (e.g. a user's own Prometheus-instrumented service).
        """
        derived: dict[str, dict] = {}
        for explicit in self.metrics.scrape:
            derived[explicit.name] = explicit.model_dump()

        return list(derived.values())

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to appropriate files and write JSON snapshot for JS consumers."""
        config_dict = self.model_dump(mode="json", exclude_none=True)

        if config_path is not None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                toml.dump(config_dict, f)
            # Holds secrets (slim.master_secret, llm.api_key); keep it owner-only.
            config_path.chmod(0o600)
            self._write_json_snapshot(config_path.parent)
            return

        global_path = self._global_config_path or self.get_global_config_path()
        global_path.parent.mkdir(parents=True, exist_ok=True)

        # Global sections: identity, server, llm, engine, runtime, metrics, a2a, adapters
        _global_sections = (
            "identity",
            "server",
            "slim",
            "llm",
            "engine",
            "auth",
            "login",
            "agent_auth",
            "runtime",
            "metrics",
            "a2a",
            "adapters",
        )

        if self._project_config_path:
            global_dict = {k: v for k, v in config_dict.items() if k in _global_sections}
            project_dict = {k: v for k, v in config_dict.items() if k in ("identity", "rooms")}
            with open(self._project_config_path, "w") as f:
                toml.dump(project_dict, f)
        else:
            global_dict = config_dict

        with open(global_path, "w") as f:
            toml.dump(global_dict, f)
        # Holds secrets (slim.master_secret, llm.api_key); keep it owner-only.
        global_path.chmod(0o600)
        self._write_json_snapshot(global_path.parent)

    def _write_json_snapshot(self, config_dir: Path) -> None:
        """Write a config.json snapshot for JS/TS consumers.

        Regenerated from config.toml on every save; edits to config.json are
        silently discarded. We prepend a ``"//"`` header key (the npm/
        package.json convention for in-JSON comments) so anyone opening the
        file sees the warning at the top. See _JSON_HEADER_* for why this
        key name is safe across consumers.
        """
        import json

        snapshot = {
            _JSON_HEADER_KEY: _JSON_HEADER_VALUE,
            **self.model_dump(mode="json", exclude_none=True),
        }
        json_path = config_dir / "config.json"
        with open(json_path, "w", encoding="utf-8") as f:
            # ensure_ascii=False so the header's em-dashes stay readable on `cat`
            # rather than showing as `\u2014`.
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # The snapshot is a full config dump (includes slim.master_secret,
        # llm.api_key); keep it owner-only, same as config.toml.
        json_path.chmod(0o600)

    def get_data_dir(self) -> Path:
        if self.runtime.data_dir:
            return Path(self.runtime.data_dir).expanduser()
        return self.get_global_config_dir()

    def save_to_project(self, project_dir: Path | None = None) -> None:
        """Save room settings to project-local .mycelium/."""
        if project_dir is None:
            project_dir = Path.cwd()

        config_dir = project_dir / ".mycelium"
        config_path = config_dir / "config.toml"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_dict = self.model_dump(mode="json", exclude_none=True)
        project_dict = {k: v for k, v in config_dict.items() if k in ("identity", "rooms")}

        with open(config_path, "w") as f:
            toml.dump(project_dict, f)

        self._project_config_path = config_path

    def init_project(self, project_dir: Path | None = None, room_name: str | None = None) -> Path:
        """Initialize a project-local .mycelium/ directory."""
        if project_dir is None:
            existing = self.find_project_config()
            if existing:
                project_dir = existing.parent.parent
            else:
                project_dir = Path.cwd()

        config_dir = project_dir / ".mycelium"
        config_dir.mkdir(parents=True, exist_ok=True)

        if room_name:
            self.rooms.active = room_name

        self.save_to_project(project_dir)
        return config_dir

    def get_active_room(self) -> str | None:
        return self.rooms.active

    def set_active_room(self, room_name: str) -> None:
        """Set the active room and save configuration."""
        self.rooms.active = room_name
        self.save()

    def clear_active_room(self) -> None:
        self.rooms.active = None
        self.save()

    def get_current_identity(self) -> str:
        import os

        from mycelium.identity import get_current_handle

        # Env var set by Mycelium plugin (or Docker Compose) takes highest priority
        env_handle = os.environ.get("MYCELIUM_AGENT_HANDLE", "").strip()
        if env_handle:
            return env_handle

        try:
            handle = get_current_handle(self)
            if handle:
                return handle
        except Exception:
            pass

        if self.identity.name:
            return self.identity.name
        return "unknown"
