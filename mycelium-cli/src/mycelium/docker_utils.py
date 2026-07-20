# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Generate .env files from config.toml — makes .env a derived artifact.

The canonical configuration lives in ~/.mycelium/config.toml.  This module
renders a Docker-compatible .env from the [llm], [runtime], and [server]
sections so that ``docker compose`` picks up the same values without users
having to maintain two files.

One field deliberately *isn't* in config.toml: ``MYCELIUM_IMAGE_TAG``.  It's
operational state — set as a side effect of ``mycelium pull --version`` and
consumed only by compose's ``${MYCELIUM_IMAGE_TAG:-latest}`` substitution.
We round-trip it through the existing .env on regeneration so that
``mycelium config apply`` doesn't silently roll users back to ``:latest``.
"""

from __future__ import annotations

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


def generate_env_file(
    config: MyceliumConfig,
    *,
    image_tag: str | None = None,
) -> str:
    """Render a .env string from the current MyceliumConfig.

    Parameters
    ----------
    config
        Canonical mycelium config — drives every key in the rendered file
        except the operator-managed pins below.
    image_tag
        Optional ``MYCELIUM_IMAGE_TAG`` value to emit verbatim.  Passed in by
        ``write_env_file`` after round-tripping the previous .env so that
        ``mycelium pull --version``'s pin survives ``mycelium config apply``.
        Pass ``None`` to omit the line entirely — compose then falls through
        to its ``${MYCELIUM_IMAGE_TAG:-latest}`` default.

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
        # DATABASE_URL / GRAPH_DB_URL / DATABASE_URL_HOST are materialised here
        # rather than reassembled in compose.yml so that the connection-string
        # recipe lives in exactly one place (MyceliumConfig.database_url).
        #   DATABASE_URL      → backend container (mycelium-db hostname)
        #   GRAPH_DB_URL      → same, but with the plain psycopg driver
        #   DATABASE_URL_HOST → host-side tools (alembic / mycelium doctor /
        #                       mycelium migrate) — resolves localhost:<published port>
        f"DATABASE_URL={config.database_url()}",
        f"GRAPH_DB_URL={config.database_url(async_driver=False)}",
        f"DATABASE_URL_HOST={config.database_url(host_side=True)}",
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
        # Only emit LLM_BASE_URL when actually set — an empty value causes
        # litellm/OpenAI SDK to reject it as UnsupportedProtocol in downstream
        # services (e.g. CFN node) that don't have the backend's validator.
        f"LLM_BASE_URL={config.llm.base_url}"
        if config.llm.base_url
        else "# LLM_BASE_URL not set — using provider default",
        "",
        "# ── Coordination ─────────────────────────────────────────────────────────",
        f"COORDINATION_TICK_TIMEOUT_SECONDS={config.runtime.coordination_tick_timeout_seconds}",
        f"CFN_RETRY_MAX_ATTEMPTS={config.runtime.cfn_retry_max_attempts}",
        f"CFN_VALIDATION_SCORE_INTERVENTION={config.runtime.cfn_validation_score_intervention}",
        f"COGNITION_ENGINES_TIMEOUT_SECONDS={config.runtime.cfn_cognition_engines_timeout_seconds}",
        # SERVER_TIMEOUT_SECONDS must exceed COGNITION_ENGINES_TIMEOUT_SECONDS so cfn-svc's
        # inbound HTTP socket stays alive long enough to forward the CE response.
        f"SERVER_TIMEOUT_SECONDS={config.runtime.cfn_cognition_engines_timeout_seconds + 10}",
        "",
        "# ── IoC CFN ──────────────────────────────────────────────────────────────",
        f"CFN_MGMT_URL={config.runtime.cfn_mgmt_url or ''}",
        f"CFN_SVC_URL={config.runtime.cfn_svc_url or ''}",
        f"WORKSPACE_ID={config.server.workspace_id or config.runtime.workspace_id or ''}",
        f"MAS_ID={config.server.mas_id or ''}",
        f"CFN_DB={config.runtime.cfn_db}",
        f"ADMIN_USER_PASSWORD={config.runtime.admin_user_password}",
        f"CFN_DEV_MODE={'true' if config.runtime.cfn_dev_mode else 'false'}",
        "",
        "# ── Negotiation ──────────────────────────────────────────────────────────",
        f"NEGOTIATION_N_STEPS={config.negotiation.n_steps}",
        "",
        "# ── Knowledge ingest control (CFN shared-memories hook) ─────────────────",
        f"MYCELIUM_INGEST_ENABLED={'true' if config.knowledge_ingest.enabled else 'false'}",
        f"MYCELIUM_INGEST_MAX_INPUT_TOKENS={config.knowledge_ingest.max_input_tokens}",
        f"MYCELIUM_INGEST_DEDUPE_TTL_SECONDS={config.knowledge_ingest.dedupe_ttl_seconds}",
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


def resolve_host_database_url(env: dict[str, str]) -> str | None:
    """Resolve the host-side DATABASE_URL from the best available source.

    Resolution order:
      1. ``DATABASE_URL_HOST`` from ``env`` (new architecture — materialised
         into ``.env`` by ``mycelium config apply``).
      2. ``MyceliumConfig.database_url(host_side=True)`` (derived from
         config.toml, works even if the user hasn't run ``config apply``).
      3. ``None`` — caller decides how to handle (fall back to legacy
         ``DATABASE_URL`` in ``env``, or error).

    Used by ``mycelium migrate``, ``mycelium install`` (migration step), and
    ``mycelium doctor`` to ensure alembic always gets a ``localhost:<port>``
    URL rather than the container-internal ``mycelium-db`` hostname.
    """
    host_url = env.get("DATABASE_URL_HOST")
    if host_url:
        return host_url
    try:
        from mycelium.config import MyceliumConfig

        return MyceliumConfig.load().database_url(host_side=True)
    except Exception:
        return None


def write_env_file(config: MyceliumConfig, env_path: Path | None = None) -> Path:
    """Write (or overwrite) the .env file derived from config.toml.

    Preserves operator-managed pins (currently ``MYCELIUM_IMAGE_TAG``) from
    the existing .env so that ``mycelium config apply`` doesn't silently
    roll users back to ``:latest`` after a ``mycelium pull --version``.

    Returns the path that was written.
    """
    if env_path is None:
        env_path = config.get_global_config_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    preserved = _read_operator_managed_keys(env_path)
    rendered = generate_env_file(config, image_tag=preserved.get("MYCELIUM_IMAGE_TAG"))
    env_path.write_text(rendered, encoding="utf-8")
    return env_path
