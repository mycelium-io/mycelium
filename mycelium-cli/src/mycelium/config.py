# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

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
from typing import Any

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
    cognition_fabric_node_url: str | None = Field(
        default=None,
        description="IoC CFN cognition fabric node URL",
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


class RoomConfig(BaseModel):
    """Room management configuration."""

    active: str | None = Field(
        default=None,
        description="Currently active room name",
    )


class KnowledgeIngestConfig(BaseModel):
    """Control surface for the mycelium-knowledge-extract hook → CFN path.

    Every knob in this section is user-facing and exposed via
    ``mycelium config set knowledge_ingest.<key> <value>``. Values are also
    overridable via ``MYCELIUM_INGEST_*`` env vars for ephemeral changes.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch for the knowledge-extract hook. False stops "
            "the hook on entry (no session reads, no POSTs, no CFN spend) and "
            "causes the backend to return 200 with a disabled marker."
        ),
    )
    events: list[str] = Field(
        default_factory=lambda: ["message:sent", "agent:bootstrap"],
        description=(
            "OpenClaw event types that fire the knowledge-extract hook. "
            "'message:sent' fires after the agent's response is delivered "
            "(one finalized turn available per fire). 'agent:bootstrap' "
            "fires on session boot for catch-up. Avoid 'command:new' — "
            "that's the /new slash command (session reset), not a new "
            "agent turn."
        ),
    )
    max_tool_content_bytes: int = Field(
        default=4096,
        description=(
            "Per-tool-call truncation threshold for tc.input and tc.result in "
            "the hook payload. 0 disables truncation. The extractor does not "
            "need full file dumps to pull concepts."
        ),
    )
    skip_in_progress_turn: bool = Field(
        default=True,
        description=(
            "Hook skips the last un-finalized turn to avoid re-sending when "
            "tool results land after the initial POST. Final session turn is "
            "only sent when the next turn arrives or the session closes."
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


class ScrapeTarget(BaseModel):
    """A Prometheus ``/metrics`` endpoint for the collector to poll.

    Configured under ``[[metrics.scrape]]`` in ``config.toml``::

        [[metrics.scrape]]
        name = "cfn-mgmt"
        url  = "http://localhost:9000/metrics"
        kind = "http_red"   # default; rolls up prometheus-fastapi-instrumentator series

    The collector polls every target on the same 30s cadence as the backend
    and stores results under the top-level ``scrape`` key in
    ``~/.mycelium/metrics.json``. Targets unreachable at scrape time are
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
    already in ``runtime.cfn_mgmt_url`` / ``runtime.cognition_fabric_node_url``)
    you don't need to touch this section at all — the collector auto-derives
    scrape targets from those runtime URLs. Use ``[[metrics.scrape]]`` only
    to add *additional* targets (e.g. a user's own Prometheus-instrumented
    service) or to override an auto-derived target by matching its ``name``.
    """

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
    knowledge_ingest: KnowledgeIngestConfig = Field(default_factory=KnowledgeIngestConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
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
        installed ``runtime.cfn_mgmt_url`` / ``runtime.cognition_fabric_node_url``
        values. That way the common case needs zero new configuration, while
        ``[[metrics.scrape]]`` remains an escape hatch for non-CFN targets
        and for overriding an auto-derived entry (match by ``name``).

        Merge rules:
          1. Start from auto-derived CFN targets (below).
          2. Layer explicit ``metrics.scrape`` entries on top, keyed by
             ``name`` — an explicit entry with the same name replaces the
             auto-derived one, so users can change URL/kind without losing
             the rest of the auto set.

        We only emit a target for ``cognition_fabric_node_url`` when the
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
        if _NODE_HAS_METRICS and self.runtime.cognition_fabric_node_url:
            derived["cfn-node"] = {
                "name": "cfn-node",
                "url": self.runtime.cognition_fabric_node_url.rstrip("/") + "/metrics",
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
