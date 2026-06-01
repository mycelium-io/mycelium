# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon configuration — list of rooms to subscribe to, runtime knobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import toml
from pydantic import BaseModel, Field


def daemon_config_path() -> Path:
    """Return the path to ~/.mycelium/daemon.toml (created on first write)."""
    return Path.home() / ".mycelium" / "daemon.toml"


def daemon_socket_path() -> Path:
    """Unix-socket path the health endpoint binds to."""
    return Path.home() / ".mycelium" / "daemon.sock"


def daemon_log_path() -> Path:
    """Daemon stdout/stderr log path (the service unit redirects here)."""
    log_dir = Path.home() / ".mycelium" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "daemon.log"


def daemon_invocation_log_dir(room: str, handle: str) -> Path:
    """Per-invocation transcript directory for an agent in a room.

    Operational logs live OUTSIDE the room's memory namespace so they don't
    pollute the semantic index, `memory ls`, synthesis runs, or room sync.
    Path: ``~/.mycelium/daemon/logs/<room>/<handle>/``.
    """
    log_dir = Path.home() / ".mycelium" / "daemon" / "logs" / room / handle
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class DaemonConfig(BaseModel):
    """Persisted daemon configuration.

    Loaded from ``~/.mycelium/daemon.toml``. Tracks the explicit list of
    rooms the daemon is subscribed to (per the v0 decision against
    auto-discovery) and a few runtime knobs.
    """

    rooms: list[str] = Field(
        default_factory=list,
        description="Rooms to subscribe to. Use `mycelium daemon subscribe <room>` to add.",
    )
    handles: list[str] = Field(
        default_factory=list,
        description=(
            "Cold-spawn agent handles this daemon owns (claude_code + cursor). "
            "Only these are dispatched — a manifest synced from another "
            "machine is ignored. Populated automatically by `mycelium agent "
            "create`. Family is recovered from the manifest's ``adapter`` "
            "field; ownership is family-agnostic."
        ),
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
    cursor_binary: str = Field(
        default="cursor-agent",
        description=(
            "Path or name of the Cursor CLI (PATH-resolved by default). The "
            "daemon-managed install drops a launchd/systemd unit that runs "
            "without a login shell, so a manual ``cursor-agent login`` is a "
            "prerequisite — see the cursor adapter docs."
        ),
    )
    spawn_timeout_s: float = Field(
        default=600.0,
        ge=30.0,
        description=(
            "Maximum wall-clock seconds a single cold-spawn invocation may run "
            "before the daemon SIGTERMs it. Guards against stuck processes "
            "blocking all future dispatches for a handle (the per-handle serial "
            "lock is held for the duration of a spawn). Default: 10 minutes."
        ),
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

    def own_handle(self, handle: str) -> bool:
        """Register *handle* as owned by this daemon. True if newly added."""
        if handle in self.handles:
            return False
        self.handles.append(handle)
        return True

    def disown_handle(self, handle: str) -> bool:
        """Drop *handle* from this daemon's ownership. True if it was present."""
        if handle not in self.handles:
            return False
        self.handles.remove(handle)
        return True

    def binary_for(self, adapter: str) -> str:
        """Return the CLI binary this daemon uses for *adapter*'s cold spawns.

        One method instead of a switch in the dispatch loop. Future cold-spawn
        families (gemini, codex, aider) add a branch here. Unknown adapters
        return an empty string — the family's ``spawn`` implementation is
        responsible for its own default and surfaces a clean "not found"
        error rather than crashing here.
        """
        if adapter == "claude_code":
            return self.claude_binary
        if adapter == "cursor":
            return self.cursor_binary
        return ""
