# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Identity management for Mycelium CLI.

Generates and manages handles for agent identification.
Format: DisplayName#session (e.g., "julvalen#a8f3")
"""

import platform
import secrets
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def get_session_path() -> Path:
    """Get the path to the project-local session file."""
    return Path.cwd() / ".mycelium" / "session"


def load_session() -> str | None:
    """Load session ID from project-local .mycelium/session."""
    session_path = get_session_path()
    if session_path.exists():
        return session_path.read_text().strip()
    return None


def save_session(session_id: str) -> None:
    """Save session ID to project-local .mycelium/session."""
    session_path = get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(session_id)


def generate_session_id() -> str:
    """Generate a new random session ID (4-character hex)."""
    return secrets.token_hex(2)


def generate_handle(name: str, session_id: str) -> str:
    """Generate a handle from name and session ID (e.g., 'julvalen#a8f3')."""
    return f"{name}#{session_id}"


def get_current_handle(config: "MyceliumConfig") -> str | None:
    """Get the current handle if identity is configured."""
    if not config.identity.name:
        return None

    session_id = load_session()
    if not session_id:
        return None

    return generate_handle(config.identity.name, session_id)


def get_or_create_identity(config: "MyceliumConfig", name: str | None = None) -> str:
    """Get existing identity or create a new one."""
    identity = config.identity

    session_id = load_session()
    if not session_id:
        session_id = generate_session_id()
        save_session(session_id)

    if name:
        identity.name = name
        config.save()
    elif not identity.name:
        identity.name = _generate_default_name()
        config.save()

    return generate_handle(identity.name, session_id)


def regenerate_identity(config: "MyceliumConfig", name: str | None = None) -> str:
    """Regenerate identity with a new session."""
    identity = config.identity

    session_id = generate_session_id()
    save_session(session_id)

    if name:
        identity.name = name
        config.save()
    elif not identity.name:
        identity.name = _generate_default_name()
        config.save()

    return generate_handle(identity.name, session_id)


def get_or_create_machine_id(config: "MyceliumConfig") -> str:
    """Get or create a stable machine identifier (UUID4)."""
    if config.identity.machine_id:
        return config.identity.machine_id

    machine_id = str(uuid.uuid4())
    config.identity.machine_id = machine_id
    config.save()
    return machine_id


def get_machine_name() -> str:
    """Get the human-readable machine hostname."""
    return platform.node() or "unknown"


def _generate_default_name() -> str:
    """Generate a default agent name using Greek letters."""
    import random

    greek_letters = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
        "xi",
        "omicron",
        "pi",
        "rho",
        "sigma",
        "tau",
        "upsilon",
        "phi",
        "chi",
        "psi",
        "omega",
    ]
    return random.choice(greek_letters)
