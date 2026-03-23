"""Shared Docker helpers used by install and config commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

# Mapping from config.toml fields to .env keys
_LLM_ENV_MAP = {
    "model": "LLM_MODEL",
    "api_key": "LLM_API_KEY",
    "base_url": "LLM_BASE_URL",
}

_RUNTIME_ENV_MAP = {
    "db_password": "MYCELIUM_DB_PASSWORD",
    "coordination_tick_timeout_seconds": "COORDINATION_TICK_TIMEOUT_SECONDS",
    "cfn_mgmt_url": "CFN_MGMT_URL",
    "admin_user_password": "ADMIN_USER_PASSWORD",
    "cfn_dev_mode": "CFN_DEV_MODE",
}


def generate_env_file(env_path: Path, config: MyceliumConfig) -> None:
    """Write ~/.mycelium/.env derived from config.toml.

    Reads env.defaults as the base template, then overlays values from
    config.llm and config.runtime. Keys absent from both template and config
    are left as-is. Keys present in config but not in the template are appended.
    """
    import importlib.resources

    defaults_ref = importlib.resources.files("mycelium.docker") / "env.defaults"
    defaults_text = defaults_ref.read_text(encoding="utf-8")

    # Build flat override dict from config
    overrides: dict[str, str] = {}
    for field, env_key in _LLM_ENV_MAP.items():
        val = getattr(config.llm, field, None)
        if val is not None:
            overrides[env_key] = str(val)
    for field, env_key in _RUNTIME_ENV_MAP.items():
        val = getattr(config.runtime, field, None)
        if val is not None:
            overrides[env_key] = str(val).lower() if isinstance(val, bool) else str(val)

    lines = []
    for line in defaults_text.splitlines():
        key = line.split("=")[0].strip() if "=" in line else None
        if key and key in overrides:
            lines.append(f"{key}={overrides[key]}")
        else:
            lines.append(line)

    # Append any override keys not already in the template
    existing_keys = {ln.split("=")[0].strip() for ln in lines if "=" in ln}
    for env_key, val in overrides.items():
        if env_key not in existing_keys:
            lines.append(f"{env_key}={val}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_compose_path() -> Path:
    """Resolve the canonical compose file path.

    For editable installs (dev), walk up from the package source to find the
    repo's services/docker-compose.yml — this keeps build context relative
    paths correct.

    For non-editable installs, extract the bundled compose to ~/.mycelium/docker/.
    """
    import importlib.resources

    if env_path := os.getenv("MYCELIUM_COMPOSE_FILE"):
        return Path(env_path)

    cwd_candidate = Path.cwd() / "services" / "docker-compose.yml"
    if cwd_candidate.exists():
        return cwd_candidate

    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "services" / "docker-compose.yml"
            if candidate.exists():
                return candidate
    except Exception:
        pass

    # Fallback: extract bundled compose (relative build paths will be wrong)
    compose_ref = importlib.resources.files("mycelium.docker") / "compose.yml"
    dest = Path.home() / ".mycelium" / "docker" / "compose.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(compose_ref.read_bytes())
    return dest
