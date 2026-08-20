# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Identity management for Mycelium CLI.

Generates and manages handles for agent identification.
Format: DisplayName#session (e.g., "julvalen#a8f3")
"""

import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def get_session_path() -> Path:
    """Path to the project-local session file."""
    return Path.cwd() / ".mycelium" / "session"


def load_session() -> str | None:
    """Load session ID from project-local .mycelium/session."""
    session_path = get_session_path()
    if session_path.exists():
        return session_path.read_text().strip()
    return None


def save_session(session_id: str) -> None:
    """Write session ID to .mycelium/session."""
    session_path = get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(session_id)


def generate_session_id() -> str:
    """Random 4-character hex session ID."""
    return secrets.token_hex(2)


def generate_handle(name: str, session_id: str) -> str:
    """Handle as name#session_id (e.g., 'julvalen#a8f3')."""
    return f"{name}#{session_id}"


def get_current_handle(config: "MyceliumConfig") -> str | None:
    """Get the current handle if identity is configured."""
    if not config.identity.name:
        return None

    session_id = load_session()
    if not session_id:
        return None

    return generate_handle(config.identity.name, session_id)
