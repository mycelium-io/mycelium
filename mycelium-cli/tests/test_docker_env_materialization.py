# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Unit tests for ``generate_env_file`` DB-URL materialisation.

``~/.mycelium/.env`` is a derived artifact written by ``mycelium install`` /
``mycelium config apply``.  Pre-Option-B it carried only the constituent
pieces (``MYCELIUM_DB_PASSWORD``, ``MYCELIUM_DB_PORT``) and compose.yml
reassembled the URL inline — meaning host-side tools (alembic, doctor,
migrate) had no way to discover the connection string.

These tests guard the contract that .env now carries the fully-assembled
``DATABASE_URL`` (container-side) and ``DATABASE_URL_HOST`` (host-side),
both flowing from the single ``MyceliumConfig.database_url`` recipe.
"""

from __future__ import annotations

import pytest

from mycelium.config import MyceliumConfig
from mycelium.docker_utils import generate_env_file, resolve_host_database_url


def _parse_env(blob: str) -> dict[str, str]:
    """Tiny dotenv parser — avoids a test dep on python-dotenv semantics."""
    out: dict[str, str] = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_env_carries_container_side_database_url() -> None:
    cfg = MyceliumConfig()
    cfg.runtime.db_password = "password"
    env = _parse_env(generate_env_file(cfg))

    assert env["DATABASE_URL"] == (
        "postgresql+asyncpg://postgres:password@mycelium-db:5432/mycelium"
    )


def test_env_carries_host_side_database_url() -> None:
    """Host-side alembic/doctor/migrate read DATABASE_URL_HOST."""
    cfg = MyceliumConfig()
    cfg.runtime.db_password = "password"
    cfg.runtime.db_port = 5432
    env = _parse_env(generate_env_file(cfg))

    assert env["DATABASE_URL_HOST"] == (
        "postgresql+asyncpg://postgres:password@localhost:5432/mycelium"
    )


def test_env_host_side_url_honours_remapped_port() -> None:
    """Real footgun the pre-Option-B architecture had: doctor would talk
    to the wrong port if the user remapped Postgres' published port.
    """
    cfg = MyceliumConfig()
    cfg.runtime.db_password = "password"
    cfg.runtime.db_port = 15432
    env = _parse_env(generate_env_file(cfg))

    assert ":15432/" in env["DATABASE_URL_HOST"]
    assert ":5432/" in env["DATABASE_URL"], (
        "container-side URL must always use 5432 regardless of host remap"
    )


def test_env_carries_graph_db_url_with_psycopg_driver() -> None:
    """Graph indexer needs the synchronous psycopg URL, not asyncpg."""
    cfg = MyceliumConfig()
    cfg.runtime.db_password = "password"
    env = _parse_env(generate_env_file(cfg))

    assert env["GRAPH_DB_URL"] == "postgresql://postgres:password@mycelium-db:5432/mycelium"
    assert "+asyncpg" not in env["GRAPH_DB_URL"]


def test_env_uses_custom_password_consistently_across_all_urls() -> None:
    cfg = MyceliumConfig()
    cfg.runtime.db_password = "hunter2"
    env = _parse_env(generate_env_file(cfg))

    for key in ("DATABASE_URL", "GRAPH_DB_URL", "DATABASE_URL_HOST"):
        assert ":hunter2@" in env[key], f"{key} did not pick up the custom password"
    assert env["MYCELIUM_DB_PASSWORD"] == "hunter2"


def test_env_explicit_override_propagates_to_all_url_variants() -> None:
    """If user sets server.database_url, every URL var in .env honours it."""
    cfg = MyceliumConfig()
    cfg.server.database_url = "postgresql+asyncpg://rds:secret@db.example.com:5432/prod"
    env = _parse_env(generate_env_file(cfg))

    for key in ("DATABASE_URL", "GRAPH_DB_URL", "DATABASE_URL_HOST"):
        assert env[key] == "postgresql+asyncpg://rds:secret@db.example.com:5432/prod", (
            f"{key} ignored server.database_url override"
        )


# ── service-port materialisation ─────────────────────────────────────────────


def test_env_materialises_all_service_ports() -> None:
    """Backend / UI / metrics ports flow from RuntimeConfig into .env.

    compose.yml port-publishes each service via ``${MYCELIUM_*_PORT:-default}``
    and `mycelium up`'s post-start summary reads the same keys back out of
    .env, so any port that isn't written here silently degrades to the
    compose default and the summary lies to the user.
    """
    cfg = MyceliumConfig()
    cfg.runtime.backend_port = 18000
    cfg.runtime.frontend_port = 13000
    cfg.runtime.collector_port = 14318
    env = _parse_env(generate_env_file(cfg))

    assert env["MYCELIUM_BACKEND_PORT"] == "18000"
    assert env["MYCELIUM_UI_PORT"] == "13000"
    assert env["MYCELIUM_METRICS_PORT"] == "14318"


def test_env_metrics_port_defaults_to_4318() -> None:
    """Default config writes MYCELIUM_METRICS_PORT=4318, matching compose.yml."""
    cfg = MyceliumConfig()
    env = _parse_env(generate_env_file(cfg))
    assert env["MYCELIUM_METRICS_PORT"] == "4318"


# ── resolve_host_database_url ────────────────────────────────────────────────


def test_resolve_prefers_database_url_host_from_env() -> None:
    """Tier 1: materialised DATABASE_URL_HOST wins over config derivation."""
    env = {"DATABASE_URL_HOST": "postgresql+asyncpg://postgres:pw@localhost:5432/mycelium"}
    assert resolve_host_database_url(env) == env["DATABASE_URL_HOST"]


def test_resolve_falls_back_to_config_when_env_key_absent() -> None:
    """Tier 2: if .env has no DATABASE_URL_HOST, derive from config.toml."""
    result = resolve_host_database_url({})
    assert result is not None
    assert "localhost" in result


def test_resolve_returns_none_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: when config can't load, return None so caller can decide."""

    def _boom() -> None:
        msg = "synthetic config load failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "mycelium.config.MyceliumConfig.load", staticmethod(_boom)
    )
    assert resolve_host_database_url({}) is None


def test_resolve_ignores_empty_database_url_host() -> None:
    """An empty string in .env shouldn't short-circuit the fallback chain."""
    env = {"DATABASE_URL_HOST": ""}
    result = resolve_host_database_url(env)
    assert result is not None
    assert "localhost" in result
