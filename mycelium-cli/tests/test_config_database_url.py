# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Unit tests for :py:meth:`MyceliumConfig.database_url`.

This method is the **single source of truth** for the Postgres connection
string across mycelium: ``generate_env_file``, ``compose.yml``,
``mycelium doctor``, and ``mycelium migrate`` all flow through it.  These
tests pin down the behaviour so future contributors can't accidentally
fork the assembly logic back across multiple call sites.

Pre-Option-B, the URL was assembled in three different places (compose
inline, doctor via a never-populated config field, alembic via raw
``$DATABASE_URL``) — these regressions are exactly what we're guarding
against.
"""

from __future__ import annotations

from mycelium.config import MyceliumConfig


def _config(**runtime_overrides: object) -> MyceliumConfig:
    """Build a config with defaults plus optional runtime overrides."""
    cfg = MyceliumConfig()
    for key, value in runtime_overrides.items():
        setattr(cfg.runtime, key, value)
    return cfg


# ─── Container-side (default) ────────────────────────────────────────────


def test_container_side_uses_mycelium_db_hostname() -> None:
    """Inside compose, the backend reaches Postgres via the service name."""
    cfg = _config(db_password="password", db_port=5432)
    url = cfg.database_url()  # host_side=False default
    assert "@mycelium-db:5432/" in url, (
        f"container-side URL must use the compose service name, got: {url}"
    )
    assert "localhost" not in url


def test_container_side_ignores_published_port() -> None:
    """The published host port doesn't apply inside the compose network.

    Even if the user remapped 5432→15432 on the host, the backend
    container still talks to mycelium-db:5432 internally.
    """
    cfg = _config(db_password="password", db_port=15432)
    url = cfg.database_url()
    assert ":5432/" in url, f"container port is fixed at 5432, got: {url}"


def test_container_side_uses_async_driver_by_default() -> None:
    cfg = _config(db_password="password")
    assert cfg.database_url().startswith("postgresql+asyncpg://")


def test_container_side_can_emit_plain_postgresql_driver() -> None:
    """The graph-db consumer needs psycopg, not asyncpg."""
    cfg = _config(db_password="password")
    url = cfg.database_url(async_driver=False)
    assert url.startswith("postgresql://")
    assert "+asyncpg" not in url


def test_container_side_injects_password_correctly() -> None:
    cfg = _config(db_password="hunter2")
    url = cfg.database_url()
    assert ":hunter2@" in url


def test_container_side_uses_canonical_user_and_dbname() -> None:
    """user=postgres and dbname=mycelium are architectural, not tunable."""
    cfg = _config(db_password="x")
    url = cfg.database_url()
    assert "postgres:" in url
    assert "/mycelium" in url


# ─── Host-side (alembic / doctor / migrate) ──────────────────────────────


def test_host_side_uses_localhost() -> None:
    cfg = _config(db_password="password", db_port=5432)
    url = cfg.database_url(host_side=True)
    assert "@localhost:" in url, (
        f"host-side URL must reach Postgres via the published port, got: {url}"
    )
    assert "mycelium-db" not in url


def test_host_side_uses_published_port() -> None:
    """Host-side URL must honour the user's published-port override.

    This is a real footgun the old architecture had: doctor would silently
    talk to the wrong port if the user remapped it.
    """
    cfg = _config(db_password="password", db_port=15432)
    url = cfg.database_url(host_side=True)
    assert ":15432/" in url, f"host-side URL must use the published port, got: {url}"


def test_host_side_still_uses_async_driver_for_alembic() -> None:
    """Alembic's env.py expects ``postgresql+asyncpg://``."""
    cfg = _config(db_password="password")
    url = cfg.database_url(host_side=True)
    assert url.startswith("postgresql+asyncpg://")


# ─── Explicit override (escape hatch for external Postgres) ──────────────


def test_explicit_database_url_override_wins() -> None:
    """If the user sets ``server.database_url``, it's returned verbatim."""
    cfg = MyceliumConfig()
    cfg.server.database_url = "postgresql+asyncpg://rds-user:secret@db.example.com:5432/prod"

    for kwargs in (
        {},
        {"host_side": True},
        {"async_driver": False},
        {"host_side": True, "async_driver": False},
    ):
        assert (
            cfg.database_url(**kwargs)
            == "postgresql+asyncpg://rds-user:secret@db.example.com:5432/prod"
        ), f"override must win regardless of kwargs={kwargs}"


def test_blank_override_is_treated_as_unset() -> None:
    """A whitespace-only ``server.database_url`` shouldn't poison the URL.

    Pydantic's optional-string default is None, but config.toml round-trips
    can produce empty strings; we don't want those silently shadowing the
    derived URL.
    """
    cfg = _config(db_password="password")
    cfg.server.database_url = "   "
    url = cfg.database_url()
    assert "mycelium-db" in url


# ─── Constants stay out of pydantic field set ────────────────────────────


def test_db_constants_are_not_pydantic_fields() -> None:
    """ClassVar constants must not leak into config.toml or model_dump.

    If these end up as fields, `mycelium config apply` would write
    DB_USER/DB_NAME into config.toml on every save and users would
    naturally try to edit them — defeating the whole point of having
    fixed architectural constants.
    """
    fields = MyceliumConfig.model_fields
    for name in ("DB_USER", "DB_NAME", "DB_CONTAINER_HOST", "DB_CONTAINER_PORT"):
        assert name not in fields, f"{name} leaked into pydantic field set"

    dumped = MyceliumConfig().model_dump()
    for name in ("DB_USER", "DB_NAME", "DB_CONTAINER_HOST", "DB_CONTAINER_PORT"):
        assert name not in dumped, f"{name} leaked into model_dump output"
