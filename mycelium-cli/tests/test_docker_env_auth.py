# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``[auth]`` → ``.env`` materialization for the HTTP-API JWT gate (#561).

``~/.mycelium/.env`` is the only transport config.toml has into the backend
container, so a setting that doesn't survive this rendering is a setting the
gate never sees. The trust roots in particular are authored as repeatable
``[[auth.issuers]]`` blocks and have to arrive as one JSON line.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mycelium.config import MyceliumConfig, TrustedIssuer
from mycelium.docker_utils import generate_env_file


def _parse_env(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_default_config_ships_the_gate_disabled() -> None:
    """The default install must render an off gate — the try-it path depends on
    it, so this is a contract, not a preference."""
    env = _parse_env(generate_env_file(MyceliumConfig()))
    assert env["AUTH_ENABLED"] == "false"
    assert env["AUTH_ISSUERS"] == ""
    assert env["AUTH_AUDIENCE"] == ""


def test_enabled_gate_materializes_every_setting() -> None:
    cfg = MyceliumConfig()
    cfg.auth.enabled = True
    cfg.auth.audience = "mycelium"
    cfg.auth.localhost_bypass = False
    cfg.auth.handle_claim = "preferred_username"
    cfg.auth.role_claim = "roles"

    env = _parse_env(generate_env_file(cfg))
    assert env["AUTH_ENABLED"] == "true"
    assert env["AUTH_AUDIENCE"] == "mycelium"
    assert env["AUTH_LOCALHOST_BYPASS"] == "false"
    assert env["AUTH_HANDLE_CLAIM"] == "preferred_username"
    assert env["AUTH_ROLE_CLAIM"] == "roles"


def test_issuers_render_as_one_json_line() -> None:
    """Multiple trust roots — the human + agent shape — must survive as JSON on
    a single line, since a multi-line value would truncate at the first newline.
    """
    cfg = MyceliumConfig()
    cfg.auth.enabled = True
    cfg.auth.issuers = [
        TrustedIssuer(issuer="https://sso.example.com/realms/people", role="user"),
        TrustedIssuer(
            issuer="https://sso.example.com/realms/agents",
            jwks_url="https://sso.example.com/realms/agents/protocol/openid-connect/certs",
            role="agent",
        ),
    ]

    rendered = generate_env_file(cfg)
    assert "AUTH_ISSUERS=" in rendered
    value = _parse_env(rendered)["AUTH_ISSUERS"]
    assert "\n" not in value

    parsed = json.loads(value)
    assert [e["issuer"] for e in parsed] == [
        "https://sso.example.com/realms/people",
        "https://sso.example.com/realms/agents",
    ]
    assert [e["role"] for e in parsed] == ["user", "agent"]
    # An unset jwks_url is omitted rather than sent as null, so the backend
    # falls through to OIDC discovery for that root.
    assert "jwks_url" not in parsed[0]
    assert parsed[1]["jwks_url"].endswith("/certs")


def test_issuer_role_must_be_user_or_agent() -> None:
    with pytest.raises(ValidationError):
        TrustedIssuer(issuer="https://sso.example.com/realms/people", role="superuser")


def test_issuer_urls_are_trailing_slash_normalized() -> None:
    """``iss`` is matched by exact string, so a stray trailing slash in config
    would silently reject every token from that issuer."""
    entry = TrustedIssuer(issuer="https://sso.example.com/realms/people/")
    assert entry.issuer == "https://sso.example.com/realms/people"
