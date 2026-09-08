# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``generate_env_file`` service-port materialization.

``~/.mycelium/.env`` is a derived artifact written by ``mycelium install`` /
``mycelium config apply``.  These tests guard the contract that .env carries
the service ports that compose.yml publishes via ``${MYCELIUM_*_PORT:-default}``.
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


# ── service-port materialization ─────────────────────────────────────────────


def test_env_materializes_all_service_ports() -> None:
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


# ── engine runtime materialization ───────────────────────────────────────────


def test_env_materializes_engine_runtime_default() -> None:
    """Default config writes ENGINE_RUNTIME=backend (the only runtime now)."""
    env = _parse_env(generate_env_file(MyceliumConfig()))
    assert env["ENGINE_RUNTIME"] == "backend"


def test_env_materializes_engine_runtime_legacy_host_coerced() -> None:
    """A legacy ``host`` setting coerces to backend (host runtime was removed with
    the daemon) and still materializes so the backend reads a valid value."""
    from mycelium.config import EngineConfig

    cfg = MyceliumConfig(engine=EngineConfig(runtime="host"))  # ty: ignore[invalid-argument-type]
    env = _parse_env(generate_env_file(cfg))
    assert env["ENGINE_RUNTIME"] == "backend"
