# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Daemon configuration — list of rooms to subscribe to, runtime knobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import toml
from pydantic import BaseModel, Field


def daemon_config_path() -> Path:
    """Return the path to ~/.mycelium/cc-daemon.toml (created on first write)."""
    return Path.home() / ".mycelium" / "cc-daemon.toml"


def daemon_socket_path() -> Path:
    """Unix-socket path the health endpoint binds to."""
    return Path.home() / ".mycelium" / "cc-daemon.sock"


def daemon_log_path() -> Path:
    """Daemon stdout/stderr log path (the service unit redirects here)."""
    log_dir = Path.home() / ".mycelium" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "cc-daemon.log"


def daemon_invocation_log_dir(room: str, handle: str) -> Path:
    """Per-invocation transcript directory for an agent in a room.

    Operational logs live OUTSIDE the room's memory namespace so they don't
    pollute the semantic index, `memory ls`, synthesis runs, or room sync.
    Path: ``~/.mycelium/cc-daemon/logs/<room>/<handle>/``.
    """
    log_dir = Path.home() / ".mycelium" / "cc-daemon" / "logs" / room / handle
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class DaemonConfig(BaseModel):
    """Persisted daemon configuration.

    Loaded from ``~/.mycelium/cc-daemon.toml``. Tracks the explicit list of
    rooms the daemon is subscribed to (per the v0 decision against
    auto-discovery) and a few runtime knobs.
    """

    rooms: list[str] = Field(
        default_factory=list,
        description="Rooms to subscribe to. Use `mycelium daemon subscribe <room>` to add.",
    )
    depth_cap: int = Field(
        default=5,
        ge=1,
        description="Maximum chained dispatches per minute per sender — guards against loops.",
    )
    claude_binary: str = Field(
        default="claude",
        description="Path or name of the Claude Code CLI (PATH-resolved by default).",
    )

    @classmethod
    def load(cls) -> DaemonConfig:
        path = daemon_config_path()
        if not path.exists():
            return cls()
        with open(path) as f:
            data: dict[str, Any] = toml.load(f) or {}
        return cls(**data)

    def save(self) -> None:
        path = daemon_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            toml.dump(self.model_dump(), f)
