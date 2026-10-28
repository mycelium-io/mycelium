# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium.slim.member`` — ephemeral join/publish/leave.

Node-free: ``SlimClient`` is replaced with :class:`~tests.conftest.FakeSlimClient`
and the hub with a recording stand-in at httpx's async transport, so these
exercise the join → connect → listen → publish → close sequence without a live
SLIM node or backend.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from mycelium.slim import member
from mycelium_backend_client.errors import UnexpectedStatus
from tests.conftest import FakeSlimClient


@pytest.fixture(autouse=True)
def _patch_slim_client(monkeypatch: pytest.MonkeyPatch, fake_slim_client: type[FakeSlimClient]):
    monkeypatch.setattr(member, "SlimClient", fake_slim_client)
    monkeypatch.setattr(member, "node_reachable", lambda _endpoint: True)
    return fake_slim_client


class _AsyncHub:
    """The hub's join route, answering at httpx's async transport.

    ``calls`` keeps each request as ``(method, url, json body)``; ``answer``
    returns the status (the join's real one is 201).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.answer: Callable[[httpx.Request], int] = lambda _r: 201

    async def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, str(request.url), body))
        status = self.answer(request)
        joined = {
            "id": "00000000-0000-0000-0000-000000000001",
            "coordination_session_id": "00000000-0000-0000-0000-000000000002",
            "agent_handle": body.get("agent_handle"),
            "joined_at": "2026-08-24T10:00:00+00:00",
        }
        return httpx.Response(status, json=joined, request=request)


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> _AsyncHub:
    hub = _AsyncHub()
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", lambda _self, request: hub.handle(request)
    )
    monkeypatch.setattr("mycelium.caller.find_membership", lambda *_a, **_k: None)
    return hub


async def test_publish_once_announces_then_publishes(fake_httpx: _AsyncHub) -> None:
    await member.publish_once(
        api_url="http://localhost:8000",
        node_endpoint="http://127.0.0.1:46357",
        room="demo",
        handle="avery",
        payload=b"hello wire",
    )

    assert fake_httpx.calls == [
        ("POST", "http://localhost:8000/api/rooms/demo/sessions", {"agent_handle": "avery"})
    ]
    assert FakeSlimClient.published == [b"hello wire"]


def test_publish_once_raises_when_node_unreachable(
    monkeypatch: pytest.MonkeyPatch, fake_httpx: _AsyncHub
) -> None:
    monkeypatch.setattr(member, "node_reachable", lambda _endpoint: False)

    with pytest.raises(member.SlimSendError, match="unreachable"):
        asyncio.run(
            member.publish_once(
                api_url="http://localhost:8000",
                node_endpoint="http://127.0.0.1:46357",
                room="demo",
                handle="avery",
                payload=b"x",
            )
        )
    assert fake_httpx.calls == []  # never got as far as announcing


def test_publish_once_raises_on_join_timeout(
    monkeypatch: pytest.MonkeyPatch, fake_httpx: _AsyncHub
) -> None:
    async def _hang(self):  # noqa: ANN001 - matches FakeSlimClient.listen_for_session
        await asyncio.sleep(10)
        return "unreachable-session"

    monkeypatch.setattr(FakeSlimClient, "listen_for_session", _hang)

    with pytest.raises(member.SlimSendError, match="timed out"):
        asyncio.run(
            member.publish_once(
                api_url="http://localhost:8000",
                node_endpoint="http://127.0.0.1:46357",
                room="demo",
                handle="avery",
                payload=b"x",
                join_timeout_s=0.05,
            )
        )


async def test_announce_presence_raises_on_http_error(fake_httpx: _AsyncHub) -> None:
    fake_httpx.answer = lambda _r: 500
    with pytest.raises(UnexpectedStatus):
        await member.announce_presence("http://localhost:8000", "demo", "avery")
