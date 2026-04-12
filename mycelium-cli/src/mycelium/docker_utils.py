# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Generate .env files from config.toml — makes .env a derived artifact.

The canonical configuration lives in ~/.mycelium/config.toml.  This module
renders a Docker-compatible .env from the [llm], [runtime], and [server]
sections so that ``docker compose`` picks up the same values without users
having to maintain two files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def generate_env_file(config: MyceliumConfig) -> str:
    """Render a .env string from the current MyceliumConfig.

    The output is suitable for ``docker compose --env-file``.  Keys that have
    no value in config are emitted as empty (``KEY=``) so that downstream
    compose variable substitution falls through to its defaults.
    """
    lines: list[str] = [
        "# Auto-generated from ~/.mycelium/config.toml — do not edit manually.",
        "# Regenerate with: mycelium config apply",
        "",
        "# ── Postgres ─────────────────────────────────────────────────────────────",
        f"MYCELIUM_DB_PASSWORD={config.runtime.db_password}",
        f"MYCELIUM_DB_PORT={config.runtime.db_port}",
        "",
        "# ── Backend ──────────────────────────────────────────────────────────────",
        f"MYCELIUM_BACKEND_PORT={config.runtime.backend_port}",
        f"MYCELIUM_DATA_DIR={config.runtime.data_dir or str(Path.home() / '.mycelium')}",
        "",
        "# ── LLM ──────────────────────────────────────────────────────────────────",
        f"LLM_MODEL={config.llm.model or ''}",
        f"LLM_API_KEY={config.llm.api_key or ''}",
        # Only emit LLM_BASE_URL when actually set — an empty value causes
        # litellm/OpenAI SDK to reject it as UnsupportedProtocol in downstream
        # services (e.g. CFN node) that don't have the backend's validator.
        f"LLM_BASE_URL={config.llm.base_url}"
        if config.llm.base_url
        else "# LLM_BASE_URL not set — using provider default",
        "",
        "# ── Coordination ─────────────────────────────────────────────────────────",
        f"COORDINATION_TICK_TIMEOUT_SECONDS={config.runtime.coordination_tick_timeout_seconds}",
        "",
        "# ── IoC CFN ──────────────────────────────────────────────────────────────",
        f"CFN_MGMT_URL={config.runtime.cfn_mgmt_url or ''}",
        f"COGNITION_FABRIC_NODE_URL={config.runtime.cognition_fabric_node_url or ''}",
        f"WORKSPACE_ID={config.runtime.workspace_id or ''}",
        f"CFN_DB={config.runtime.cfn_db}",
        f"ADMIN_USER_PASSWORD={config.runtime.admin_user_password}",
        f"CFN_DEV_MODE={'true' if config.runtime.cfn_dev_mode else 'false'}",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_env_file(config: MyceliumConfig, env_path: Path | None = None) -> Path:
    """Write (or overwrite) the .env file derived from config.toml.

    Returns the path that was written.
    """
    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(generate_env_file(config), encoding="utf-8")
    return env_path
