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


# ── design-pattern packs ─────────────────────────────────────────────────────


def test_env_offers_no_pattern_pack_by_default() -> None:
    """Out of the box the hub has no pack, accepts a scenario in the request, and
    takes any member kind: a private, trusting setup."""
    env = _parse_env(generate_env_file(MyceliumConfig()))
    assert env["PATTERNS_DIR"] == ""
    assert env["PATTERNS_ALLOW_INLINE"] == "true"
    assert env["PATTERNS_PERSONAS_ONLY"] == "false"


def test_env_materializes_the_pattern_pack_as_an_absolute_path(tmp_path) -> None:
    """``patterns.dir`` is a host path: compose mounts it, so ``~`` and relative
    paths are resolved before they reach .env."""
    from mycelium.config import PatternsConfig

    cfg = MyceliumConfig(patterns=PatternsConfig(dir=str(tmp_path / "pack")))
    env = _parse_env(generate_env_file(cfg))
    assert env["PATTERNS_DIR"] == str((tmp_path / "pack").resolve())

    cfg.patterns.dir = "~/packs/mine"
    env = _parse_env(generate_env_file(cfg))
    assert env["PATTERNS_DIR"].endswith("/packs/mine")
    assert "~" not in env["PATTERNS_DIR"]


def test_env_materializes_a_public_hubs_pattern_limits() -> None:
    from mycelium.config import PatternsConfig

    cfg = MyceliumConfig(patterns=PatternsConfig(allow_inline=False, personas_only=True))
    env = _parse_env(generate_env_file(cfg))
    assert env["PATTERNS_ALLOW_INLINE"] == "false"
    assert env["PATTERNS_PERSONAS_ONLY"] == "true"


def test_the_backend_reads_the_names_the_env_renders() -> None:
    """The names ``.env`` carries are the ones the backend's settings read."""
    import re
    from pathlib import Path

    backend = Path(__file__).parents[2] / "fastapi-backend" / "app" / "config.py"
    if not backend.exists():
        return  # an installed CLI without the backend checkout beside it
    declared = set(re.findall(r"^    (PATTERNS_[A-Z_]+):", backend.read_text(), re.M))
    rendered = {
        k for k in _parse_env(generate_env_file(MyceliumConfig())) if k.startswith("PATTERNS_")
    }
    assert rendered == declared
