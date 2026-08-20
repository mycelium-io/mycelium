# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Generate .env files from config.toml, making .env a derived artifact.

The canonical configuration lives in ~/.mycelium/config.toml.  This module
renders a Docker-compatible .env from the [llm], [runtime], [server], [engine],
and [auth] sections so that ``docker compose`` picks up the same values without
users having to maintain two files.

One field deliberately *isn't* in config.toml: ``MYCELIUM_IMAGE_TAG``.  It's
operational state, set as a side effect of ``mycelium pull --version`` and
consumed only by compose's ``${MYCELIUM_IMAGE_TAG:-latest}`` substitution.
We round-trip it through the existing .env on regeneration so that
``mycelium config apply`` doesn't silently roll users back to ``:latest``.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


# Operator-managed keys: not derivable from config.toml, but preserved across
# ``mycelium config apply`` so that side-effecting commands like
# ``mycelium pull --version`` don't get clobbered.  Add new entries here only
# when the key has no natural home in MyceliumConfig (i.e., it's runtime/ops
# state, not user-tunable configuration).
_OPERATOR_MANAGED_KEYS: tuple[str, ...] = ("MYCELIUM_IMAGE_TAG",)

_MASTER_SECRET_ENV = "MYCELIUM_SLIM_MASTER_SECRET"


def _read_env_value(env_path: Path | None, key: str) -> str | None:
    """Return a single key from an existing ``.env``, or ``None``."""
    if env_path is None or not env_path.exists():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, value = stripped.partition("=")
            if k.strip() == key:
                cleaned = value.strip().strip('"').strip("'")
                return cleaned or None
    except OSError:
        return None
    return None


def ensure_slim_master_secret(config: MyceliumConfig, *, env_path: Path | None = None) -> bool:
    """Ensure ``config.slim.master_secret`` is set before rendering ``.env``.

    Import order when unset:

    1. Existing ``MYCELIUM_SLIM_MASTER_SECRET`` in ``env_path`` (migration)
    2. Fresh ``secrets.token_hex(32)`` (first hub install / apply)

    Returns ``True`` when a value was imported or generated (caller should
    ``config.save()``).
    """
    if config.slim.master_secret:
        return False

    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"

    imported = _read_env_value(env_path, _MASTER_SECRET_ENV)
    if imported:
        config.slim.master_secret = imported
        return True

    config.slim.master_secret = secrets.token_hex(32)
    return True


def _read_operator_managed_keys(env_path: Path | None) -> dict[str, str]:
    """Extract operator-managed values from an existing ``.env``.

    Returns an empty dict if ``env_path`` is None or the file doesn't exist.
    Used by ``write_env_file`` to preserve pins across regeneration and by
    ``mycelium up`` to surface the effective tag at startup.

    Parsing is intentionally permissive (matches ``_patch_env_image_tag``'s
    behaviour): blank/commented lines are skipped, ``KEY=value`` is split on
    the first ``=``, and surrounding whitespace is stripped.
    """
    if env_path is None or not env_path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in _OPERATOR_MANAGED_KEYS:
                out[key] = value.strip()
    except OSError:
        # Best-effort: callers always have a sensible fallback.
        return {}
    return out


def read_pinned_image_tag(env_path: Path | None) -> str | None:
    """Return the ``MYCELIUM_IMAGE_TAG`` value from ``env_path``, or None.

    Public helper so that ``mycelium up`` can surface the effective tag
    without rebuilding the parser.
    """
    return _read_operator_managed_keys(env_path).get("MYCELIUM_IMAGE_TAG")


def _render_auth_issuers(config: MyceliumConfig) -> str:
    """Trust roots as a single-line JSON array for ``AUTH_ISSUERS``.

    Emitted empty when none are configured, so compose substitution and the
    backend's ``env_ignore_empty`` both fall through to "no trusted issuers"
    rather than to a literal ``[]`` string.
    """
    if not config.auth.issuers:
        return ""
    return json.dumps(
        [entry.model_dump(exclude_none=True) for entry in config.auth.issuers],
        separators=(",", ":"),
    )


def generate_env_file(
    config: MyceliumConfig,
    *,
    image_tag: str | None = None,
) -> str:
    """Render a .env string from the current MyceliumConfig.

    Parameters
    ----------
    config
        Canonical mycelium config; drives every key in the rendered file
        except the operator-managed pins below.
    image_tag
        Optional ``MYCELIUM_IMAGE_TAG`` value to emit verbatim.  Passed in by
        ``write_env_file`` after round-tripping the previous .env so that
        ``mycelium pull --version``'s pin survives ``mycelium config apply``.
        Pass ``None`` to omit the line entirely; compose then falls through
        to its ``${MYCELIUM_IMAGE_TAG:-latest}`` default.

    The output is suitable for ``docker compose --env-file``.  Keys that have
    no value in config are emitted as empty (``KEY=``) so that downstream
    compose variable substitution falls through to its defaults.
    """
    lines: list[str] = [
        "# Auto-generated from ~/.mycelium/config.toml. Do not edit manually.",
        "# Regenerate with: mycelium config apply",
        "",
        "# ── Backend ──────────────────────────────────────────────────────────────",
        f"MYCELIUM_BACKEND_PORT={config.runtime.backend_port}",
        f"MYCELIUM_UI_PORT={config.runtime.frontend_port}",
        f"MYCELIUM_METRICS_PORT={config.runtime.collector_port}",
        f"MYCELIUM_DATA_DIR={config.runtime.data_dir or str(Path.home() / '.mycelium')}",
        "",
        "# ── LLM ──────────────────────────────────────────────────────────────────",
        f"LLM_MODEL={config.llm.model or ''}",
        f"LLM_API_KEY={config.llm.api_key or ''}",
        # Only emit LLM_BASE_URL when actually set; an empty value causes the
        # OpenAI SDK to reject it as UnsupportedProtocol in downstream
        # services that don't have the backend's validator.
        f"LLM_BASE_URL={config.llm.base_url}"
        if config.llm.base_url
        else "# LLM_BASE_URL not set, using provider default",
        "",
        "# ── Engine ───────────────────────────────────────────────────────────────",
        # Where a registered `engine` runs its NEGMAS/Pi drive; backend-only.
        # Always `backend`.
        f"ENGINE_RUNTIME={config.engine.runtime}",
        "",
        "# ── Auth (HTTP-API JWT gate; off unless auth.enabled is set) ─────────────",
        f"AUTH_ENABLED={str(config.auth.enabled).lower()}",
        # Trust roots travel as one JSON array because env is the only transport
        # into the container; the repeatable [[auth.issuers]] blocks in
        # config.toml are the authored form.
        f"AUTH_ISSUERS={_render_auth_issuers(config)}",
        f"AUTH_AUDIENCE={config.auth.audience or ''}",
        f"AUTH_LOCALHOST_BYPASS={str(config.auth.localhost_bypass).lower()}",
        f"AUTH_HANDLE_CLAIM={config.auth.handle_claim}",
        f"AUTH_ROLE_CLAIM={config.auth.role_claim}",
        f"AUTH_LEEWAY_S={config.auth.leeway_s}",
        f"AUTH_JWKS_TTL_S={config.auth.jwks_ttl_s}",
        "",
        "# ── SLIM channel identity (off by default, #567) ─────────────────────────",
        # 'psk' | 'signerjwt' | 'spire'. The backend + CLI both read
        # MYCELIUM_SLIM_IDENTITY; the shared master secret is authored in
        # config.toml ([slim].master_secret) and rendered here. SPIRE socket/trust-
        # domain envs stay operator-managed (out of band). See slim_identity.py.
        f"MYCELIUM_SLIM_IDENTITY={config.slim.identity}",
        f"MYCELIUM_SLIM_MASTER_SECRET={config.slim.master_secret or ''}",
        "",
        "# ── Frontend dev-mode cross-origin allowlist ─────────────────────────────",
        # Next.js dev server blocks cross-origin requests by default. When running
        # the UI behind a public IP or NAT (e.g. an EC2 instance accessed from a
        # laptop) the browser's origin differs from localhost and the dev server
        # returns 403 on internal endpoints. Set runtime.allowed_dev_origins in
        # config.toml (or `mycelium config set runtime.allowed_dev_origins IP`)
        # to allowlist those origins. Comma-separated list; empty = no extra origins.
        # Production builds don't need this — browsers always hit their own origin.
        f"MYCELIUM_ALLOWED_DEV_ORIGINS={config.runtime.allowed_dev_origins}",
        "",
    ]

    # ── Operator-managed pins (preserved across `mycelium config apply`) ─────
    # Anything in this block is NOT derived from config.toml; it's set as a
    # side effect of a CLI command (currently only `mycelium pull --version`,
    # which writes MYCELIUM_IMAGE_TAG via _patch_env_image_tag).  Emitted last
    # so that compose variable substitution gets a stable, late-binding value.
    if image_tag is not None:
        lines.extend(
            [
                "# ── Operator-managed pins (managed by `mycelium pull --version`) ────────",
                f"MYCELIUM_IMAGE_TAG={image_tag}",
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def write_env_file(config: MyceliumConfig, env_path: Path | None = None) -> tuple[Path, bool]:
    """Write (or overwrite) the .env file derived from config.toml.

    Ensures ``[slim].master_secret`` is set (import or generate) and persists
    it to ``config.toml`` when newly assigned. Preserves operator-managed pins
    (currently ``MYCELIUM_IMAGE_TAG``) from the existing .env.

    Returns ``(path, secret_was_assigned)`` where ``secret_was_assigned`` is
    ``True`` when a master secret was imported or generated this call.
    """
    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    secret_assigned = ensure_slim_master_secret(config, env_path=env_path)
    if secret_assigned:
        config.save()

    preserved = _read_operator_managed_keys(env_path)
    rendered = generate_env_file(config, image_tag=preserved.get("MYCELIUM_IMAGE_TAG"))
    env_path.write_text(rendered, encoding="utf-8")
    return env_path, secret_assigned
