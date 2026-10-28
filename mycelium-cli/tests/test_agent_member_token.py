# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent started on this machine gets its own token from the hub.

On a hub with auth on, an agent's pane can't use the person's sign-in, so
whoever starts the agent asks the hub for a join code for it and redeems it.
The token is kept in a file only its owner can read, and the pane is given the
file's path, never the token.
"""

from __future__ import annotations

import stat
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from mycelium import agent_credentials, caller
from mycelium.agent_credentials import issue_member_token as real_issue
from mycelium.config import MyceliumConfig
from tests.conftest import install_stand_in_hub


class Hub:
    def __init__(self, *, token: str | None = "signed-for-scout", joins: int = 201) -> None:
        self.token, self.joins = token, joins
        self.asked: list[tuple[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append((request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/joins"):
            if self.joins != 201:
                return httpx.Response(self.joins, json={"detail": "not yours"})
            join = {"code": "abcd-efgh-jkmn", "room": "eng", "handle": "scout"}
            return httpx.Response(201, json=join | {"expires_at": "2026-08-24T10:00:00+00:00"})
        if request.url.path == "/api/joins/redeem":
            return httpx.Response(200, json={"room": "eng", "handle": "scout", "token": self.token})
        return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hub]:
    hub = Hub()
    install_stand_in_hub(monkeypatch).answer = hub.handler
    # This machine is signed in as a person, whose login the typed client carries.
    monkeypatch.setattr(
        "mycelium.client.auth_headers", lambda *_a, **_k: {"Authorization": "Bearer person"}
    )
    # The suite turns issuing off; these tests are the ones that use it.
    monkeypatch.setattr(agent_credentials, "issue_member_token", real_issue)
    yield hub


def _config() -> MyceliumConfig:
    config = MyceliumConfig()
    config.server.api_url = "http://hub:8000"
    return config


def test_the_agent_gets_its_own_token_in_a_file_only_its_owner_reads(hub: Hub) -> None:
    env = agent_credentials.agent_token_env(_config(), "eng", "@Scout")
    path = env[agent_credentials.STATIC_TOKEN_FILE_ENV]
    assert path.endswith("member-tokens/eng/scout.token")
    with open(path) as fh:
        assert fh.read() == "signed-for-scout"
    import os

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # The code is asked for as the person; the redeem carries nobody's login.
    assert hub.asked == [
        ("/api/rooms/eng/joins", "Bearer person"),
        ("/api/joins/redeem", None),
    ]


def test_a_pane_given_the_file_acts_as_its_agent_with_that_token(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = agent_credentials.agent_token_env(_config(), "eng", "scout")
    for name, value in {
        **env,
        "MYCELIUM_AGENT_HANDLE": "scout",
        "MYCELIUM_AGENT_PANE": "scout",
    }.items():
        monkeypatch.setenv(name, value)
    answer = caller.credential(_config())
    assert answer.value == "signed-for-scout"
    assert answer.source == caller.ENVIRONMENT


def test_with_auth_off_there_is_nothing_to_give(hub: Hub) -> None:
    hub.token = None
    assert agent_credentials.agent_token_env(_config(), "eng", "scout") == {}


def test_a_hub_that_refuses_this_machine_says_why_rather_than_giving_nothing(hub: Hub) -> None:
    # Signed out here: the agent could do nothing on this hub, so the start is
    # told to say so rather than starting it anyway.
    hub.joins = 401
    with pytest.raises(agent_credentials.MemberTokenRefused) as signed_out:
        agent_credentials.agent_token_env(_config(), "eng", "scout")
    assert signed_out.value.signed_out
    assert "isn't signed in to http://hub:8000" in signed_out.value.reason()
    assert "`mycelium login`" in signed_out.value.reason()
    # Signed in as someone who doesn't own it: the hub's own words, and who to ask.
    hub.joins = 403
    with pytest.raises(agent_credentials.MemberTokenRefused) as not_yours:
        agent_credentials.agent_token_env(_config(), "eng", "scout")
    assert not not_yours.value.signed_out
    assert "not yours" in not_yours.value.reason()
    assert "its owner's computer" in not_yours.value.reason()
