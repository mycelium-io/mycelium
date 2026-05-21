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

from mycelium.config import MyceliumConfig
from mycelium.docker_utils import generate_env_file


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
