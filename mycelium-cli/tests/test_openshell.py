# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the OpenShell gateway recipe (pure builders).

The docker/CLI-touching orchestration is validated live (it needs Docker); these
pin the deterministic pieces: the gateway config, the mirrored docker-run
invocation, the metrics scrape target, and JWT keygen.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mycelium import openshell

# ── gateway.toml ─────────────────────────────────────────────────────────────


def test_render_gateway_toml_has_required_sections() -> None:
    toml = openshell.render_gateway_toml()
    # Docker driver needs gateway JWT auth with a signing keypair.
    assert "[openshell.gateway.gateway_jwt]" in toml
    assert 'signing_key_path = "/etc/openshell/jwt/signing.pem"' in toml
    assert "ttl_secs         = 0" in toml
    # Local single-user: unauthenticated CLI access.
    assert "allow_unauthenticated_users = true" in toml
    # Docker compute driver over the mounted socket.
    assert 'compute_drivers = ["docker"]' in toml
    assert 'socket_path   = "/var/run/docker.sock"' in toml


# ── docker run invocation ────────────────────────────────────────────────────


def test_build_gateway_run_command_mirrors_paths_and_mounts() -> None:
    state, jwt, cfg, sup = (
        Path("/h/state"),
        Path("/h/jwt"),
        Path("/h/gateway.toml"),
        Path("/h/supervisor/openshell-sandbox"),
    )
    cmd = openshell.build_gateway_run_command(state=state, jwt=jwt, config=cfg, supervisor=sup)
    joined = " ".join(cmd)

    # root (docker.sock access) + the container name + image last.
    assert "--user" in cmd and "0:0" in cmd
    assert cmd[-1] == openshell.GATEWAY_IMAGE
    assert openshell.GATEWAY_CONTAINER in cmd
    # HOME points at the mirrored state dir; state is mounted host==container.
    assert "HOME=/h/state" in cmd
    assert "/h/state:/h/state" in cmd
    # supervisor is mirrored host==container (Docker mounts it into sandboxes).
    assert "/h/supervisor/openshell-sandbox:/h/supervisor/openshell-sandbox:ro" in cmd
    # config + jwt + docker socket mounts.
    assert "/h/gateway.toml:/etc/openshell/gateway.toml:ro" in cmd
    assert "/h/jwt:/etc/openshell/jwt:ro" in cmd
    assert "/var/run/docker.sock:/var/run/docker.sock" in cmd
    # TLS off for local; db under the mirrored state dir with create flag.
    assert "OPENSHELL_DISABLE_TLS=true" in cmd
    assert "OPENSHELL_DB_URL=sqlite:/h/state/openshell.db?mode=rwc" in cmd
    # metrics port on by default.
    assert f"OPENSHELL_METRICS_PORT={openshell.METRICS_PORT}" in cmd
    assert f"127.0.0.1:{openshell.METRICS_PORT}:{openshell.METRICS_PORT}" in joined


def test_build_gateway_run_command_no_metrics() -> None:
    cmd = openshell.build_gateway_run_command(
        state=Path("/s"),
        jwt=Path("/j"),
        config=Path("/c"),
        supervisor=Path("/sup"),
        enable_metrics=False,
    )
    assert not any("METRICS_PORT" in a for a in cmd)
    assert not any(str(openshell.METRICS_PORT) in a for a in cmd)


# ── metrics scrape target ────────────────────────────────────────────────────


def test_ensure_scrape_target_adds_grpc_red_then_idempotent() -> None:
    from mycelium.config import MyceliumConfig

    cfg = MyceliumConfig()
    assert cfg.metrics.scrape == []

    added = openshell.ensure_scrape_target(cfg)
    assert added is True
    (t,) = cfg.metrics.scrape
    assert t.name == "openshell-gateway"
    assert t.kind == "grpc_red"
    assert str(openshell.METRICS_PORT) in t.url

    # Second call is a no-op (no duplicate).
    assert openshell.ensure_scrape_target(cfg) is False
    assert len(cfg.metrics.scrape) == 1


# ── JWT keygen ───────────────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")
def test_generate_jwt_keypair_writes_ed25519(tmp_path: Path) -> None:
    openshell.generate_jwt_keypair(tmp_path)
    signing = (tmp_path / "signing.pem").read_text()
    public = (tmp_path / "public.pem").read_text()
    assert "PRIVATE KEY" in signing
    assert "PUBLIC KEY" in public
    assert (tmp_path / "kid").read_text() == "mycelium"

    # Idempotent — a second call keeps the same keys (never rotate live tokens).
    before = signing
    openshell.generate_jwt_keypair(tmp_path)
    assert (tmp_path / "signing.pem").read_text() == before
