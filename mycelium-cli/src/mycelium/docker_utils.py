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
from urllib.parse import urlparse

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def _is_hub_config(config: MyceliumConfig) -> bool:
    """Return True when this config targets a local backend (hub / all-in-one).

    Spokes point ``server.api_url`` at a remote host and do not run a SLIM
    node, so hub-only operations (PSK generation, container management) should
    be skipped for them.
    """
    host = (urlparse(config.server.api_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# Operator-managed keys: not derivable from config.toml, but preserved across
# ``mycelium config apply`` so that side-effecting commands like
# ``mycelium pull --version`` and ``mycelium up --build`` don't get clobbered.
# Add new entries here only when the key has no natural home in MyceliumConfig
# (i.e., it's runtime/ops state, not user-tunable configuration).
_OPERATOR_MANAGED_KEYS: tuple[str, ...] = (
    "MYCELIUM_IMAGE_TAG",
    # Set to "dev" by ``mycelium up --build`` when compose-dev.yml is active so
    # that ``mycelium config apply --restart`` re-injects compose-dev.yml and
    # avoids pulling GHCR images over the locally-built ones.
    "MYCELIUM_BUILD_MODE",
)

_MASTER_SECRET_ENV = "MYCELIUM_SLIM_MASTER_SECRET"

# Config fields that never reach a container, and why. `.env` is the only
# transport from config.toml into the stack, so a field neither rendered by
# ``generate_env_file`` nor listed here is a setting that silently does nothing.
# tests/test_config_env_coverage.py holds the two in step.
LOCAL_ONLY_FIELDS: dict[str, str] = {
    # ── Read straight from the bind-mounted config.toml ─────────────────────
    "metrics.scrape": "collector_main.py reads it from the mounted config.toml",
    "metrics.collector_url": "spoke-side: which collector `mycelium metrics show` reads",
    # ── CLI-side only: never leaves the host ────────────────────────────────
    "identity.name": "the operator's local display name",
    "identity.machine_id": "local machine affinity UUID",
    "identity.autonomous": "whether this CLI runs unattended",
    "server.api_url": "this machine's view of the hub; in-container the backend "
    "gets API_BASE_URL from compose",
    "slim.node_endpoint": "the client's node address; the backend gets "
    "SLIM_NODE_ENDPOINT from compose (the in-network name)",
    "rooms.active": "the room this shell is scoped to",
    "herdr.autowake": "CLI-side wake layer; the backend is herdr-blind",
    "herdr.wake_timeout_ms": "CLI-side wake layer; the backend is herdr-blind",
    "adapters": "registered agent-framework adapters, launched by the CLI",
    "login.issuer": "client half of auth: who this machine logs in against",
    "login.client_id": "client half of auth",
    "login.client_secret": "client half of auth (a secret; never rendered)",
    "login.audience": "client half of auth",
    "login.scopes": "client half of auth",
    "login.redirect_port": "loopback port for the CLI's browser redirect",
    "agent_auth.issuer": "workload half of auth: where agents mint their tokens",
    "agent_auth.scopes": "workload half of auth",
    "agent_auth.audience": "workload half of auth",
}

# Compose variables with no config.toml source. Compose substitutes from the
# process environment when a key is absent from .env, which is how these are
# meant to be set — so `config apply` regenerating .env doesn't drop them.
ENVIRONMENT_SUPPLIED_VARS: dict[str, str] = {
    "SLIM_IMAGE_TAG": "node image pin, overridable for a lockstep bindings bump",
    "MYCELIUM_SLIM_PORT": "published node port; the compose default is the norm",
    "MYCELIUM_OIDC_ISSUER": "browser OIDC login, exported per the Keycloak guide",
    "MYCELIUM_OIDC_INTERNAL_ISSUER": "browser OIDC login",
    "MYCELIUM_OIDC_CLIENT_ID": "browser OIDC login",
    "MYCELIUM_OIDC_AUDIENCE": "browser OIDC login",
    "AUTH_SESSION_SECRET": "frontend cookie sealing key (a secret; not in config.toml)",
    "MYCELIUM_COOKIE_SECURE": "set only for a plain-HTTP appliance deployment",
}


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


def ensure_slim_master_secret(
    config: MyceliumConfig,
    *,
    env_path: Path | None = None,
    allow_generate: bool = True,
) -> bool:
    """Ensure ``config.slim.master_secret`` is set before rendering ``.env``.

    Import order when unset:

    1. Existing ``MYCELIUM_SLIM_MASTER_SECRET`` in ``env_path`` (migration /
       hub at a non-localhost address).
    2. Fresh ``secrets.token_hex(32)`` — only when ``allow_generate`` is
       ``True`` (hub install / apply).  Pass ``allow_generate=False`` on a
       spoke so an existing secret in ``.env`` is promoted into ``config.toml``
       but no new secret is minted.

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

    if not allow_generate:
        return False

    config.slim.master_secret = secrets.token_hex(32)
    return True


def _read_operator_managed_keys(env_path: Path | None) -> dict[str, str]:
    """Extract operator-managed values from an existing ``.env``.

    Returns an empty dict if ``env_path`` is None or the file doesn't exist.
    Used by ``write_env_file`` to preserve pins across regeneration and by
    ``mycelium up`` to surface the effective tag at startup.

    Parsing is intentionally permissive (matches ``_patch_env_image_tag``'s
    behavior): blank/commented lines are skipped, ``KEY=value`` is split on
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
    """Return the ``MYCELIUM_IMAGE_TAG`` value from ``env_path``, or ``None``."""
    return _read_operator_managed_keys(env_path).get("MYCELIUM_IMAGE_TAG")


def read_build_mode(env_path: Path | None) -> str | None:
    """Return ``"dev"`` when the stack was started with ``mycelium up --build``.

    ``None`` (or empty string) means the stack runs pulled GHCR images.
    """
    return _read_operator_managed_keys(env_path).get("MYCELIUM_BUILD_MODE") or None


def patch_build_mode(env_path: Path, mode: str) -> None:
    """Set or clear ``MYCELIUM_BUILD_MODE`` in ``env_path`` in-place.

    Pass ``mode="dev"`` when compose-dev.yml was used (``mycelium up --build``
    with a found overlay); pass ``mode=""`` to clear it so a subsequent pulled
    or installed stack doesn't keep the stale flag.
    """
    if not env_path.exists():
        if mode:
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(f"MYCELIUM_BUILD_MODE={mode}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key == "MYCELIUM_BUILD_MODE":
                if mode:
                    new_lines.append(f"MYCELIUM_BUILD_MODE={mode}")
                # mode="" → drop the line (cleared)
                found = True
                continue
        new_lines.append(line)
    if not found and mode:
        new_lines.append(f"MYCELIUM_BUILD_MODE={mode}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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
    build_mode: str | None = None,
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
        # 'psk' | 'signerjwt'. The backend + CLI both read MYCELIUM_SLIM_IDENTITY;
        # the shared master secret is authored in config.toml ([slim].master_secret)
        # and rendered here. See slim_identity.py.
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
        "# ── Reverse proxy in front of the backend ───────────────────────────────",
        # uvicorn honors X-Forwarded-Proto/-For only from a forwarder it trusts,
        # and trusts loopback alone unless told otherwise. Behind a TLS-terminating
        # proxy the hop arrives from the bridge, so without this every absolute URL
        # the backend builds keeps the http:// scheme it sees (#799). Emitted only
        # when set: an empty value would be read as "trust nobody", which is not the
        # same as uvicorn's loopback default.
        f"FORWARDED_ALLOW_IPS={config.runtime.trusted_proxies}"
        if config.runtime.trusted_proxies
        else "# FORWARDED_ALLOW_IPS not set; uvicorn trusts loopback forwarders only",
        "",
        "# ── A2A bridge ────────────────────────────────────────────────────────────",
        # SSRF guard: by default the bridge refuses card URLs that resolve to
        # private/loopback/link-local addresses. Set allow_private_hosts = true in
        # config.toml (mycelium config set a2a.allow_private_hosts true) to disable
        # this guard for deployments where A2A agents live on an internal network.
        f"A2A_ALLOW_PRIVATE_HOSTS={'1' if config.a2a.allow_private_hosts else ''}",
        "",
    ]

    # ── Operator-managed pins (preserved across `mycelium config apply`) ─────
    # Anything in this block is NOT derived from config.toml; it's set as a
    # side effect of a CLI command (currently `mycelium pull --version` for
    # MYCELIUM_IMAGE_TAG and `mycelium up --build` for MYCELIUM_BUILD_MODE).
    # Emitted last so that compose variable substitution gets a stable,
    # late-binding value.
    if image_tag is not None or build_mode:
        lines.append("# ── Operator-managed pins ─────────────────────────────────────────────────")
        if image_tag is not None:
            lines.append(f"MYCELIUM_IMAGE_TAG={image_tag}")
        if build_mode:
            lines.append(f"MYCELIUM_BUILD_MODE={build_mode}")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_env_file(config: MyceliumConfig, env_path: Path | None = None) -> tuple[Path, bool]:
    """Write (or overwrite) the .env file derived from config.toml.

    Always runs the import path for ``[slim].master_secret``: if the key
    already exists in ``.env`` it is promoted into ``config.toml`` so the
    rendered output stays correct for hubs at non-localhost addresses (LAN IP,
    reverse proxy).  Generation of a *new* secret is only performed on hubs
    (local ``server.api_url``) — spokes have no SLIM node and must not silently
    mint a secret that would diverge from the hub's shared PSK.

    Preserves operator-managed pins (``MYCELIUM_IMAGE_TAG``,
    ``MYCELIUM_BUILD_MODE``) from the existing .env.

    Returns ``(path, secret_was_assigned)`` where ``secret_was_assigned`` is
    ``True`` when a master secret was imported or generated this call.
    """
    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    secret_assigned = ensure_slim_master_secret(
        config,
        env_path=env_path,
        allow_generate=_is_hub_config(config),
    )
    if secret_assigned:
        config.save()

    preserved = _read_operator_managed_keys(env_path)
    rendered = generate_env_file(
        config,
        image_tag=preserved.get("MYCELIUM_IMAGE_TAG"),
        build_mode=preserved.get("MYCELIUM_BUILD_MODE") or None,
    )
    env_path.write_text(rendered, encoding="utf-8")
    return env_path, secret_assigned
