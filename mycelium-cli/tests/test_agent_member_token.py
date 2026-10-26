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
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from mycelium import agent_credentials, caller
from mycelium.agent_credentials import issue_member_token as real_issue
from mycelium.config import MyceliumConfig


class Hub:
    def __init__(self, *, token: str | None = "signed-for-scout", joins: int = 201) -> None:
        self.token, self.joins = token, joins
        self.asked: list[tuple[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append((request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/joins"):
            if self.joins != 201:
                return httpx.Response(self.joins, json={"detail": "not yours"})
            return httpx.Response(201, json={"code": "abcd-efgh-jkmn"})
        if request.url.path == "/api/joins/redeem":
            return httpx.Response(200, json={"room": "eng", "handle": "scout", "token": self.token})
        return httpx.Response(404)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hub]:
    hub = Hub()
    transport = httpx.MockTransport(lambda r: hub.handler(r))

    @contextmanager
    def client(_config: Any = None, **_kw: Any):
        with httpx.Client(
            base_url="http://hub:8000",
            transport=transport,
            headers={"authorization": "Bearer person"},
        ) as c:
            yield c

    def post(url: str, **kw: Any) -> httpx.Response:
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kw)

    monkeypatch.setattr("mycelium.client.hub_client", client)
    monkeypatch.setattr(httpx, "post", post)
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


def test_with_auth_off_or_a_refusal_there_is_nothing_to_give(hub: Hub) -> None:
    hub.token = None
    assert agent_credentials.agent_token_env(_config(), "eng", "scout") == {}
    hub.token, hub.joins = "t", 403
    assert agent_credentials.agent_token_env(_config(), "eng", "scout") == {}
