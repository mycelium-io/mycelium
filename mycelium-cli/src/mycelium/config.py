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
from pathlib import Path
from typing import Any, ClassVar

import toml
from pydantic import BaseModel, Field, field_validator

# Header key prepended to every ~/.mycelium/config.json write. Strict JSON
# has no comment syntax; ``"//"`` is the long-standing npm/package.json
# convention for documentation keys and is ignored by every consumer of this
# file (they look up known sections by name: server / llm / knowledge_ingest /
# etc). The key leads so it's the first thing a user sees on `cat`. Long
# term we plan to delete this file entirely and have JS hooks parse
# config.toml directly — see #146 — so this is interim.
_JSON_HEADER_KEY = "//"
_JSON_HEADER_VALUE = (
    "DO NOT EDIT — auto-generated from ~/.mycelium/config.toml on every save. "
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
    workspace_id: str | None = Field(
        default=None,
        description="Default workspace UUID (created during install)",
    )
    mas_id: str | None = Field(
        default=None,
        description="Default MAS UUID (created during install)",
    )
    database_url: str | None = Field(
        default=None,
        description="Database URL override (defaults to backend container default)",
    )

    @field_validator("api_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URLs don't have trailing slashes."""
        return v.rstrip("/")


class LLMConfig(BaseModel):
    """LLM configuration (litellm format)."""

    model: str | None = Field(
        default=None,
        description="LLM model in litellm format (e.g. anthropic/claude-sonnet-4-6)",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for the LLM provider",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL for LLM endpoint (ollama, vllm, etc.)",
    )


class RuntimeConfig(BaseModel):
    """Docker runtime / environment configuration."""

    db_password: str = Field(
        default="password",
        description="Postgres password for the mycelium-db container",
    )
    db_port: int = Field(
        default=5432,
        description="Host port for Postgres",
    )
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
    data_dir: str | None = Field(
        default=None,
        description="Root directory for .mycelium/ data (defaults to ~/.mycelium)",
    )
    coordination_tick_timeout_seconds: int = Field(
        default=30,
        description="Per-round timeout for CognitiveEngine negotiation",
    )
    cfn_mgmt_url: str | None = Field(
        default=None,
        description="IoC CFN management plane URL",
    )
    cfn_svc_url: str | None = Field(
        default=None,
        description="IoC CFN node service URL",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Workspace ID in the CFN mgmt plane",
    )
    cfn_db: str = Field(
        default="cfn_mgmt",
        description="CFN management database name",
    )
    admin_user_password: str = Field(
        default="admin",
        description="Admin user password for CFN mgmt plane",
    )
    cfn_dev_mode: bool = Field(
        default=False,
        description="Enable CFN dev mode",
    )


class NegotiationConfig(BaseModel):
    """Tunables for the CFN-mediated negotiation flow."""

    n_steps: int = Field(
        default=20,
        description=(
            "Maximum SAO rounds per session. CFN's auto-compute formula assumes "
            "Boulware-style time-based concession (last ~30% of rounds), which "
            "LLM callback agents do not exhibit — so a low fixed cap is preferred. "
            "Set to 0 to fall through to CFN's auto-computed budget."
        ),
    )


class DaemonSettings(BaseModel):
    """Daemon behaviour tunables (hub-and-spoke cleanup, GC policy)."""

    auto_gc_orphaned_rooms: bool = Field(
        default=False,
        description=(
            "When True, the daemon automatically removes local room directories "
            "that no longer exist on the hub (detected at startup and on "
            "room_deleted SSE events).  Defaults to False so operators can review "
            "orphans via `mycelium doctor` or `mycelium room gc` before deletion."
        ),
    )


class RoomConfig(BaseModel):
    """Room management configuration."""

    active: str | None = Field(
        default=None,
        description="Currently active room name",
    )


class KnowledgeIngestConfig(BaseModel):
    """Control surface for the channel-message and ``memory set`` → CFN path.

    KXP fires only on deliberate room artifacts; the silent per-turn hook is
    gone. These knobs are user-facing and exposed via
    ``mycelium config set knowledge_ingest.<key> <value>``. Values are also
    overridable via ``MYCELIUM_INGEST_*`` env vars for ephemeral changes.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch. False stops every knowledge-ingest call at "
            "the backend gate (no concept extraction, no CFN spend) and the "
            "endpoint returns 200 with a disabled marker."
        ),
    )
    max_input_tokens: int = Field(
        default=50_000,
        description=(
            "Backend circuit breaker — payloads above this estimated input "
            "token count are refused with 413. Set to 0 to disable."
        ),
    )
    dedupe_ttl_seconds: int = Field(
        default=300,
        description=(
            "Backend content-hash dedupe window. Identical payloads posted "
            "within this many seconds return the cached response_id without "
            "hitting CFN. Set to 0 to disable dedupe entirely."
        ),
    )
    min_content_chars: int = Field(
        default=32,
        description=(
            "Skip ingest for trivially short content. Channel posts like "
            "'ack' or a single emoji produce KG noise without value. Set to "
            "0 to ingest everything."
        ),
    )


class ScrapeTarget(BaseModel):
    """A Prometheus ``/metrics`` endpoint for the collector to poll.

    Configured under ``[[metrics.scrape]]`` in ``config.toml``::

        [[metrics.scrape]]
        name = "cfn-mgmt"
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
        description="Stable, short identifier — used as the dict key in metrics.json and as the panel label.",
        min_length=1,
        max_length=64,
    )
    url: str = Field(
        ...,
        description="Full URL of the Prometheus exposition endpoint (typically ending in /metrics).",
    )
    kind: str = Field(
        default="http_red",
        description="Roll-up strategy. Currently only 'http_red' is supported (HTTP rate/error/duration).",
    )


class MetricsConfig(BaseModel):
    """Configuration for the metrics collector + display.

    For the common case (scraping stock CFN services whose URLs are
    already in ``runtime.cfn_mgmt_url`` / ``runtime.cfn_svc_url``)
    you don't need to touch this section at all — the collector auto-derives
    scrape targets from those runtime URLs. Use ``[[metrics.scrape]]`` only
    to add *additional* targets (e.g. a user's own Prometheus-instrumented
    service) or to override an auto-derived target by matching its ``name``.

    On spoke nodes, set ``collector_url`` to the hub's collector address
    (e.g. ``http://hub-ip:4318``). This makes ``mycelium metrics show``
    fetch data from the hub and sets the default OTLP endpoint for
    adapter plugins — no local collector needed.
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
        description=(
            "Explicit Prometheus /metrics endpoints to scrape. Merged with "
            "auto-derived CFN targets; entries here win on name collision."
        ),
    )


class MyceliumConfig(BaseModel):
    """Complete Mycelium CLI configuration."""

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rooms: RoomConfig = Field(default_factory=RoomConfig)
    daemon: DaemonSettings = Field(default_factory=DaemonSettings)
    knowledge_ingest: KnowledgeIngestConfig = Field(default_factory=KnowledgeIngestConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    negotiation: NegotiationConfig = Field(default_factory=NegotiationConfig)
    adapters: dict[str, Any] = Field(
        default_factory=dict,
        description="Registered agent framework adapters (openclaw, cursor, claude-code, …)",
    )

    model_config = {"arbitrary_types_allowed": True}
    _global_config_path: Path | None = None
    _project_config_path: Path | None = None

    @classmethod
    def get_global_config_dir(cls) -> Path:
        """Get the global configuration directory (~/.mycelium/)."""
        return Path.home() / ".mycelium"

    @classmethod
    def get_global_config_path(cls) -> Path:
        """Get the global configuration file path."""
        return cls.get_global_config_dir() / "config.toml"

    @classmethod
    def get_logs_dir(cls) -> Path:
        """Get the logs directory (~/.mycelium/logs/)."""
        logs_dir = cls.get_global_config_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @classmethod
    def get_project_config_dir(cls) -> Path:
        """Get the project-local configuration directory (./.mycelium/)."""
        return Path.cwd() / ".mycelium"

    @classmethod
    def get_project_config_path(cls) -> Path:
        """Get the project-local configuration file path."""
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
        """Check if project-local .mycelium/ exists."""
        return cls.find_project_config() is not None

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the configuration file path (prefers project-local)."""
        project_config = cls.find_project_config()
        return project_config if project_config else cls.get_global_config_path()

    @classmethod
    def get_config_dir(cls) -> Path:
        """Get the configuration directory path (prefers project-local)."""
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
            "rooms": {},
            "llm": {},
            "runtime": {},
            "knowledge_ingest": {},
            "metrics": {},
        }

        if api_url := os.getenv("MYCELIUM_API_URL"):
            env_config["server"]["api_url"] = api_url
        if workspace_id := os.getenv("MYCELIUM_WORKSPACE_ID"):
            env_config["server"]["workspace_id"] = workspace_id
        if mas_id := os.getenv("MYCELIUM_MAS_ID"):
            env_config["server"]["mas_id"] = mas_id
        if active_room := os.getenv("MYCELIUM_ACTIVE_ROOM"):
            env_config["rooms"]["active"] = active_room

        # LLM overrides
        if llm_model := os.getenv("LLM_MODEL"):
            env_config["llm"]["model"] = llm_model
        if llm_api_key := os.getenv("LLM_API_KEY"):
            env_config["llm"]["api_key"] = llm_api_key
        if llm_base_url := os.getenv("LLM_BASE_URL"):
            env_config["llm"]["base_url"] = llm_base_url

        # Knowledge-ingest overrides — ephemeral escape hatches
        if (v := os.getenv("MYCELIUM_INGEST_ENABLED")) is not None:
            env_config["knowledge_ingest"]["enabled"] = v.lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
        if (v := os.getenv("MYCELIUM_INGEST_MAX_INPUT_TOKENS")) is not None:
            try:
                env_config["knowledge_ingest"]["max_input_tokens"] = int(v)
            except ValueError:
                pass
        if (v := os.getenv("MYCELIUM_INGEST_DEDUPE_TTL_SECONDS")) is not None:
            try:
                env_config["knowledge_ingest"]["dedupe_ttl_seconds"] = int(v)
            except ValueError:
                pass
        if (v := os.getenv("MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES")) is not None:
            try:
                env_config["knowledge_ingest"]["max_tool_content_bytes"] = int(v)
            except ValueError:
                pass

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
        """Return the full list of Prometheus scrape targets for the collector.

        Mirrors how OTLP ingestion works (no config needed — OpenClaw knows
        where to push) by auto-deriving CFN scrape targets from the already-
        installed ``runtime.cfn_mgmt_url`` / ``runtime.cfn_svc_url``
        values. That way the common case needs zero new configuration, while
        ``[[metrics.scrape]]`` remains an escape hatch for non-CFN targets
        and for overriding an auto-derived entry (match by ``name``).

        Merge rules:
          1. Start from auto-derived CFN targets (below).
          2. Layer explicit ``metrics.scrape`` entries on top, keyed by
             ``name`` — an explicit entry with the same name replaces the
             auto-derived one, so users can change URL/kind without losing
             the rest of the auto set.

        We only emit a target for ``cfn_svc_url`` when the
        service actually exposes ``/metrics`` — today it does not (see
        cfn_component_metrics_reconciliation.md), so we leave it out to
        avoid a permanently "degraded" row. Flip ``_NODE_HAS_METRICS`` below
        once that ships.
        """
        # Keep the URL of record in runtime.*; here we just append the
        # Prometheus convention path. If a site runs CFN on a non-default
        # path they can still declare an explicit [[metrics.scrape]].
        _NODE_HAS_METRICS = False

        derived: dict[str, dict] = {}
        if self.runtime.cfn_mgmt_url:
            derived["cfn-mgmt"] = {
                "name": "cfn-mgmt",
                "url": self.runtime.cfn_mgmt_url.rstrip("/") + "/metrics",
                "kind": "http_red",
            }
        if _NODE_HAS_METRICS and self.runtime.cfn_svc_url:
            derived["cfn-node"] = {
                "name": "cfn-node",
                "url": self.runtime.cfn_svc_url.rstrip("/") + "/metrics",
                "kind": "http_red",
            }

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
            self._write_json_snapshot(config_path.parent)
            return

        global_path = self._global_config_path or self.get_global_config_path()
        global_path.parent.mkdir(parents=True, exist_ok=True)

        # Global sections: identity, server, llm, runtime, knowledge_ingest, metrics, adapters
        _global_sections = (
            "identity",
            "server",
            "llm",
            "runtime",
            "knowledge_ingest",
            "metrics",
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
        self._write_json_snapshot(global_path.parent)

    def _write_json_snapshot(self, config_dir: Path) -> None:
        """Write a config.json snapshot for JS/TS consumers.

        Regenerated from config.toml on every save — edits to config.json are
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

    def get_data_dir(self) -> Path:
        """Get the resolved data directory."""
        if self.runtime.data_dir:
            return Path(self.runtime.data_dir).expanduser()
        return self.get_global_config_dir()

    # ── Database URL assembly ────────────────────────────────────────────────
    #
    # Single source of truth for the Postgres connection URL.  Compose, the
    # generated ``~/.mycelium/.env``, and host-side tools (alembic, doctor,
    # migrate) all flow through this method so the URL recipe lives in
    # exactly one place.  The pieces (password, port) come from
    # ``config.toml``; user, hostname, dbname, and async driver are
    # mycelium-architectural and intentionally not user-tunable.
    #
    # ``server.database_url`` in config.toml stays as an explicit override
    # (e.g., pointing at an external Postgres); when set, every consumer
    # honours it verbatim.

    # Constants that describe mycelium's bundled Postgres deployment.
    # Centralised here so they can't drift between compose, alembic, and
    # the CLI helpers.  ClassVar keeps these out of pydantic's field set so
    # they don't show up in config.toml dumps or model_dump() output.
    DB_USER: ClassVar[str] = "postgres"
    DB_NAME: ClassVar[str] = "mycelium"
    DB_CONTAINER_HOST: ClassVar[str] = "mycelium-db"  # resolves inside the compose network
    DB_CONTAINER_PORT: ClassVar[int] = 5432  # fixed inside the compose network

    def database_url(self, *, host_side: bool = False, async_driver: bool = True) -> str:
        """Return the canonical Postgres connection URL.

        Parameters
        ----------
        host_side
            ``True`` → resolve via ``localhost:<published_port>``; appropriate
            for tools running on the host (alembic, ``mycelium doctor``,
            ``mycelium migrate``).
            ``False`` → resolve via ``mycelium-db:5432``; appropriate for
            services running inside the compose network (the backend
            container, the graph indexer, etc.).
        async_driver
            ``True`` → ``postgresql+asyncpg://`` (SQLAlchemy async, used by
            the backend and alembic).
            ``False`` → ``postgresql://`` (psycopg/plain libpq, used by the
            graph-db URL and any non-async consumer).

        If ``server.database_url`` is set in config.toml, it is returned
        verbatim (escape hatch for external/managed Postgres).  Callers that
        need the ``host_side`` vs container distinction lose it in that
        case; that's intentional — if you've pointed mycelium at an
        external DB, there is no "container" alternative.
        """
        override = (self.server.database_url or "").strip()
        if override:
            return override

        if host_side:
            host = "localhost"
            port = self.runtime.db_port
        else:
            host = self.DB_CONTAINER_HOST
            port = self.DB_CONTAINER_PORT

        from urllib.parse import quote

        scheme = "postgresql+asyncpg" if async_driver else "postgresql"
        password = quote(self.runtime.db_password, safe="")
        return f"{scheme}://{self.DB_USER}:{password}@{host}:{port}/{self.DB_NAME}"

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
        """Get the currently active room."""
        return self.rooms.active

    def set_active_room(self, room_name: str) -> None:
        """Set the active room and save configuration."""
        self.rooms.active = room_name
        self.save()

    def clear_active_room(self) -> None:
        """Clear the active room setting."""
        self.rooms.active = None
        self.save()

    def get_current_identity(self) -> str:
        """Get the current identity handle for attribution."""
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
