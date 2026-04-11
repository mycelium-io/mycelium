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


class MyceliumConfig(BaseModel):
    """Complete Mycelium CLI configuration."""

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rooms: RoomConfig = Field(default_factory=RoomConfig)
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
        env_config: dict[str, Any] = {"server": {}, "rooms": {}, "llm": {}, "runtime": {}}

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

        # Global sections: identity, server, llm, runtime, adapters
        _global_sections = ("identity", "server", "llm", "runtime", "adapters")

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

        This avoids JS hooks needing a TOML parser — they read the JSON snapshot
        which is regenerated every time config is saved.
        """
        import json

        # Export the subset that JS hooks need: server, llm, identity
        snapshot = self.model_dump(mode="json", exclude_none=True)
        json_path = config_dir / "config.json"
        with open(json_path, "w") as f:
            json.dump(snapshot, f, indent=2)
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
