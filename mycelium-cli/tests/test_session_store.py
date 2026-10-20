# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's sign-in is kept in the system keychain, renewed quietly, and an
agent's pane never gets it."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend

from mycelium import caller, client, session_store
from mycelium.config import MyceliumConfig
from mycelium.tokens import StoredToken, load_token, save_token, token_path

_TOKEN = StoredToken(
    access_token="at-person",
    issuer="https://idp.test",
    client_id="cli",
    refresh_token="rt-person",
    expires_at=time.time() + 3600,
)
_HUB = "https://hub.example.com"


class MemoryKeychain(KeyringBackend):
    """A keychain that lives in this test, never the machine's."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.items.pop((service, username))


class TooSmallKeychain(MemoryKeychain):
    """A keychain that refuses an entry as large as a sign-in (Windows' limit)."""

    def set_password(self, service: str, username: str, password: str) -> None:
        msg = "too large for the credential store"
        raise OSError(msg)


@pytest.fixture
def config(isolated_home: Path) -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = _HUB
    return cfg


@pytest.fixture
def keychain() -> MemoryKeychain:
    kc = MemoryKeychain()
    keyring.set_keyring(kc)
    return kc


def kept(kc: MemoryKeychain) -> dict[str, Any]:
    """The sign-in the keychain holds for the hub, or ``{}``."""
    raw = kc.items.get((session_store.SERVICE, _HUB))
    return json.loads(raw) if raw else {}


def test_a_sign_in_is_kept_in_the_keychain_refresh_token_and_all(config, keychain) -> None:
    assert session_store.save(config, _TOKEN) == session_store.KEYCHAIN
    assert not token_path().exists()
    assert kept(keychain)["refresh_token"] == "rt-person"
    found, where = session_store.load(config)
    assert where == session_store.KEYCHAIN
    assert found == _TOKEN


def test_without_a_keychain_it_goes_in_a_private_file(config) -> None:
    # The suite's default: no keychain at all.
    assert session_store.save(config, _TOKEN) == session_store.FILE
    assert load_token() == _TOKEN
    assert token_path().stat().st_mode & 0o777 == 0o600


def test_an_entry_the_keychain_wont_hold_goes_in_the_file(config) -> None:
    keyring.set_keyring(TooSmallKeychain())
    assert session_store.save(config, _TOKEN) == session_store.FILE
    assert load_token() == _TOKEN


def test_a_file_from_before_moves_into_the_keychain_and_is_deleted(config, keychain) -> None:
    save_token(_TOKEN)
    found, where = session_store.load(config)
    assert (found, where) == (_TOKEN, session_store.KEYCHAIN)
    assert kept(keychain)["access_token"] == "at-person"
    assert not token_path().exists()


def test_a_renewal_is_kept_where_the_sign_in_was(config, keychain, monkeypatch) -> None:
    """An expired access token is renewed with the refresh token, quietly, and
    the new session replaces the old one in the keychain."""
    expired = replace(_TOKEN, expires_at=time.time() - 10)
    session_store.save(config, expired)
    fresh = replace(_TOKEN, access_token="at-new")
    monkeypatch.setattr(client, "_refresh", lambda stored, cfg: fresh)

    assert client.current_token(config) == fresh
    assert kept(keychain)["access_token"] == "at-new"
    assert not token_path().exists()


def test_signing_out_removes_it_from_both(config, keychain) -> None:
    session_store.save(config, _TOKEN)
    save_token(_TOKEN)
    assert session_store.clear(config) is True
    assert kept(keychain) == {}
    assert not token_path().exists()
    assert session_store.clear(config) is False


def test_each_hub_has_its_own_sign_in(config, keychain) -> None:
    session_store.save(config, _TOKEN)
    other = MyceliumConfig()
    other.server.api_url = "https://other.example.com"
    assert session_store.load(other) == (None, None)


def test_an_agents_pane_never_gets_the_persons_sign_in(config, keychain, monkeypatch) -> None:
    session_store.save(config, _TOKEN)
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    assert session_store.load(config) == (None, None)
    with pytest.raises(session_store.InAgentPane):
        session_store.save(config, _TOKEN)


def test_an_agents_pane_cant_act_as_anyone_else(config, monkeypatch) -> None:
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    with pytest.raises(caller.ActingAsOtherError, match="act as @builder only"):
        caller.credential(config, "julia")
    # As itself is fine: it simply has no person's session to fall back on.
    assert caller.credential(config, "builder").value is None


def test_a_pane_herdrs_registry_maps_is_an_agents_even_unmarked(monkeypatch) -> None:
    monkeypatch.setattr(
        caller, "pane_agent", lambda: caller.PaneAgent(pane="w1:p2", handle="scout", room="r")
    )
    assert caller.in_agent_pane() == "scout"
