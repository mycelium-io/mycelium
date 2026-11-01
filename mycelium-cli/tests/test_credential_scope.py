# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A credential goes only to the hub that issued it."""

from __future__ import annotations

import pytest

from mycelium import client
from mycelium.config import MyceliumConfig


@pytest.fixture
def config(monkeypatch) -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = "https://hub.example.com"
    monkeypatch.setattr(client, "auth_headers", lambda *_a, **_k: {"Authorization": "Bearer t"})
    monkeypatch.setattr("mycelium.caller.find_membership", lambda *_a, **_k: None)
    return cfg


def test_the_issuing_hub_gets_the_credential(config) -> None:
    with client.hub_client(config) as c:
        assert c.headers.get("Authorization") == "Bearer t"
    with client.hub_client(config, base_url="https://hub.example.com:443/") as c:
        assert c.headers.get("Authorization") == "Bearer t"


@pytest.mark.parametrize(
    "elsewhere",
    [
        "https://other.example.com",
        "http://hub.example.com",  # same name, not the same server
        "https://hub.example.com:8443",
        "https://hub.example.com.evil.test",
    ],
)
def test_any_other_address_gets_none(config, elsewhere: str) -> None:
    with client.hub_client(config, base_url=elsewhere) as c:
        assert "Authorization" not in c.headers


def test_the_hub_a_folder_joined_issued_its_credential(config, monkeypatch) -> None:
    class _Member:
        hub = "https://joined.example.com"

    monkeypatch.setattr("mycelium.caller.find_membership", lambda *_a, **_k: _Member())
    assert client.issued_by(config, "https://joined.example.com/api")
    assert not client.issued_by(config, "https://elsewhere.example.com")
