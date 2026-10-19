# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` survives a proxy, loses no message and prints the wake digest.

A wait is made of short requests, so a proxy's idle limit never ends it; a
request that drops is waited again; and a turn the hub hands over unread is
confirmed once it is here.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mycelium.commands import participate
from mycelium.config import MyceliumConfig

_TURN = {
    "prompt": "@agent ship it?",
    "sender": "julia",
    "delivered": {"position": 7, "episode": None},
    "digest": "mycelium wake for @agent in r\n\nNext:    mycelium respond ...",
}


@pytest.fixture
def config() -> MyceliumConfig:
    return MyceliumConfig()


def _requests(monkeypatch, answers: list[Any]) -> list[int]:
    """Answer each long-poll from ``answers`` (a turn, ``None``, or an
    exception to raise), each taking the whole wait it was given on a fake
    clock, and return the waits asked for."""
    waits: list[int] = []
    clock = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    monkeypatch.setattr("time.sleep", lambda s: clock.__setitem__(0, clock[0] + s))

    def fake(_config, _room, _handle, wait, _episode):
        waits.append(wait)
        clock[0] += wait
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(participate, "_await_request", fake)
    return waits


def _confirms(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(
        participate, "_confirm", lambda _c, _r, _h, turn: sent.append(turn.get("delivered"))
    )
    return sent


def test_a_long_wait_is_made_of_requests_a_proxy_lets_through(monkeypatch, config) -> None:
    waits = _requests(monkeypatch, [None, None, dict(_TURN)])
    _confirms(monkeypatch)
    turn = participate._await_once(config, "r", "agent", timeout=0)
    assert turn is not None
    assert turn["prompt"] == "@agent ship it?"
    assert waits == [participate.WAIT_CHUNK_S] * 3


def test_a_dropped_request_is_waited_again(monkeypatch, config) -> None:
    dropped = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    waits = _requests(monkeypatch, [dropped, dict(_TURN)])
    sent = _confirms(monkeypatch)
    assert participate._await_once(config, "r", "agent", timeout=0) is not None
    assert len(waits) == 2
    assert sent == [{"position": 7, "episode": None}]


def test_a_proxy_that_gave_up_on_the_hub_is_waited_again(monkeypatch, config) -> None:
    gateway = httpx.HTTPStatusError(
        "bad gateway",
        request=httpx.Request("GET", "http://hub/await"),
        response=httpx.Response(504),
    )
    _requests(monkeypatch, [gateway, dict(_TURN)])
    _confirms(monkeypatch)
    assert participate._await_once(config, "r", "agent", timeout=0) is not None


def test_a_refusal_is_not_waited_again(monkeypatch, config) -> None:
    refused = httpx.HTTPStatusError(
        "forbidden",
        request=httpx.Request("GET", "http://hub/await"),
        response=httpx.Response(403),
    )
    _requests(monkeypatch, [refused])
    with pytest.raises(httpx.HTTPStatusError):
        participate._await_once(config, "r", "agent", timeout=0)


def test_nothing_within_the_timeout_is_none(monkeypatch, config) -> None:
    waits = _requests(monkeypatch, [None])
    assert participate._await_once(config, "r", "agent", timeout=5) is None
    assert waits == [5]


def test_a_turn_from_a_hub_without_confirmation_is_not_confirmed(monkeypatch, config) -> None:
    posted: list[str] = []

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def post(self, path, **_kw):
            posted.append(path)
            return httpx.Response(200, request=httpx.Request("POST", path))

    monkeypatch.setattr(participate, "hub_client", lambda *_a, **_k: _Client())
    participate._confirm(config, "r", "agent", {"prompt": "hi"})
    assert posted == []
    participate._confirm(config, "r", "agent", dict(_TURN))
    assert posted == ["/api/rooms/r/await/confirm"]


def test_plain_await_prints_the_digest(capsys) -> None:
    participate._print_turn(dict(_TURN), "agent")
    assert capsys.readouterr().out.strip() == _TURN["digest"]
