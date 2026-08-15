# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium.slim.member`` — ephemeral join/publish/leave.

Node-free: ``SlimClient`` is replaced with :class:`~tests.conftest.FakeSlimClient`
and ``httpx`` with the recording fakes, so these exercise the join → connect →
listen → publish → close sequence without a live SLIM node or backend.
"""

from __future__ import annotations

import asyncio

import pytest

from mycelium.slim import member
from tests.conftest import FakeHTTPX, FakeResp, FakeSlimClient


@pytest.fixture(autouse=True)
def _patch_slim_client(monkeypatch: pytest.MonkeyPatch, fake_slim_client: type[FakeSlimClient]):
    monkeypatch.setattr(member, "SlimClient", fake_slim_client)
    monkeypatch.setattr(member, "node_reachable", lambda _endpoint: True)
    return fake_slim_client


async def test_publish_once_announces_then_publishes(fake_httpx: FakeHTTPX) -> None:
    await member.publish_once(
        api_url="http://localhost:8000",
        node_endpoint="http://127.0.0.1:46357",
        room="demo",
        handle="julia",
        payload=b"hello wire",
    )

    assert fake_httpx.calls == [
        ("POST", "http://localhost:8000/api/rooms/demo/sessions", {"agent_handle": "julia"})
    ]
    assert FakeSlimClient.published == [b"hello wire"]


def test_publish_once_raises_when_node_unreachable(
    monkeypatch: pytest.MonkeyPatch, fake_httpx: FakeHTTPX
) -> None:
    monkeypatch.setattr(member, "node_reachable", lambda _endpoint: False)

    with pytest.raises(member.SlimSendError, match="unreachable"):
        asyncio.run(
            member.publish_once(
                api_url="http://localhost:8000",
                node_endpoint="http://127.0.0.1:46357",
                room="demo",
                handle="julia",
                payload=b"x",
            )
        )
    assert fake_httpx.calls == []  # never got as far as announcing


def test_publish_once_raises_on_join_timeout(
    monkeypatch: pytest.MonkeyPatch, fake_httpx: FakeHTTPX
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
                handle="julia",
                payload=b"x",
                join_timeout_s=0.05,
            )
        )


async def test_announce_presence_raises_on_http_error(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp(boom=True, status_code=500))
    with pytest.raises(RuntimeError):
        await member.announce_presence("http://localhost:8000", "demo", "julia")
