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
from mycelium_backend_client.errors import UnexpectedStatus
from mycelium_backend_client.models import AwaitTurn
from tests.conftest import install_stand_in_hub

_TURN = {
    "room": "r",
    "handle": "agent",
    "prompt": "@agent ship it?",
    "sender": "julia",
    "episode": None,
    "topic": None,
    "message_id": None,
    "delivered": {"position": 7, "episode": None},
    "digest": "mycelium wake for @agent in r\n\nNext:    mycelium respond ...",
}


def _turn(**fields: Any) -> AwaitTurn:
    """A fresh ``AwaitTurn`` as the hub hands it over, ``fields`` laid over."""
    return AwaitTurn.from_dict({**_TURN, **fields})


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


def _confirms(monkeypatch) -> list[dict | None]:
    sent: list[dict | None] = []
    monkeypatch.setattr(
        participate,
        "_confirm",
        lambda _c, _r, _h, turn: sent.append(turn.delivered.to_dict() if turn.delivered else None),
    )
    return sent


def test_a_long_wait_is_made_of_requests_a_proxy_lets_through(monkeypatch, config) -> None:
    waits = _requests(monkeypatch, [None, None, _turn()])
    _confirms(monkeypatch)
    turn = participate._await_once(config, "r", "agent", timeout=0)
    assert turn is not None
    assert turn.prompt == "@agent ship it?"
    assert waits == [participate.WAIT_CHUNK_S] * 3


def test_a_dropped_request_is_waited_again(monkeypatch, config) -> None:
    dropped = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    waits = _requests(monkeypatch, [dropped, _turn()])
    sent = _confirms(monkeypatch)
    assert participate._await_once(config, "r", "agent", timeout=0) is not None
    assert len(waits) == 2
    assert sent == [{"position": 7, "episode": None}]


def test_a_proxy_that_gave_up_on_the_hub_is_waited_again(monkeypatch, config) -> None:
    gateway = UnexpectedStatus(504, b"<html>bad gateway</html>")
    _requests(monkeypatch, [gateway, _turn()])
    _confirms(monkeypatch)
    assert participate._await_once(config, "r", "agent", timeout=0) is not None


def test_a_refusal_is_not_waited_again(monkeypatch, config) -> None:
    refused = UnexpectedStatus(403, b'{"detail": "forbidden"}')
    _requests(monkeypatch, [refused])
    with pytest.raises(UnexpectedStatus):
        participate._await_once(config, "r", "agent", timeout=0)


def test_nothing_within_the_timeout_is_none(monkeypatch, config) -> None:
    waits = _requests(monkeypatch, [None])
    assert participate._await_once(config, "r", "agent", timeout=5) is None
    assert waits == [5]


def test_a_turn_from_a_hub_without_confirmation_is_not_confirmed(monkeypatch, config) -> None:
    hub = install_stand_in_hub(monkeypatch)
    hub.answer = lambda _r: {"room": "r", "handle": "agent", "confirmed": True}
    participate._confirm(config, "r", "agent", _turn(prompt="hi", delivered=None, digest=None))
    assert [r.url.path for r in hub.requests if r.method == "POST"] == []
    participate._confirm(config, "r", "agent", _turn())
    assert [r.url.path for r in hub.requests if r.method == "POST"] == [
        "/api/rooms/r/await/confirm"
    ]


def test_a_confirmation_that_failed_rides_on_the_next_await(monkeypatch, config, tmp_path) -> None:
    """A proxy that blocks the confirming POST can't make every await hand
    over the same turn: the position goes with the next await, even from a
    new process, and is forgotten once the hub has it."""
    monkeypatch.setattr(participate.MyceliumConfig, "get_global_config_dir", lambda: tmp_path)

    def answer(request: httpx.Request) -> object:
        if request.method == "POST":
            return 403, {"detail": "blocked"}
        return {"room": "r", "handle": "agent", "message": None}

    hub = install_stand_in_hub(monkeypatch)
    hub.answer = answer
    participate._confirm(config, "r", "agent", _turn())
    participate._await_request(config, "r", "agent", 5, None)
    participate._await_request(config, "r", "agent", 5, None)
    sent = [dict(r.url.params) for r in hub.requests if r.method == "GET"]
    assert sent[0]["confirmed"] == "7"
    assert "confirmed" not in sent[1]


def test_plain_await_prints_the_digest(capsys) -> None:
    participate._print_turn(_turn(), "agent")
    assert capsys.readouterr().out.strip() == _TURN["digest"]


def _answering(monkeypatch, *answers: httpx.Response) -> list[str]:
    """The hub answers each ``/await`` with the next of ``answers``; the paths asked."""
    asked: list[str] = []
    queue = list(answers)

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "service": "hub", "version": "9.9.9"})
        return queue.pop(0)

    install_stand_in_hub(monkeypatch).answer = answer
    return asked


def test_a_proxy_page_on_a_status_the_route_declares_is_waited_again(monkeypatch, config) -> None:
    # A 503 the hub declares, but an HTML page rather than the hub's JSON: a
    # proxy that gave up, the same as its 502.
    page = httpx.Response(503, text="<html>Service Unavailable</html>")
    asked = _answering(monkeypatch, page, httpx.Response(200, json=_TURN))
    _confirms(monkeypatch)
    turn = participate._await_once(config, "r", "agent", timeout=0)
    assert turn is not None
    assert turn.prompt == "@agent ship it?"
    assert asked.count("/api/rooms/r/await") == 2


def test_a_turn_this_cli_cant_read_stops_await_with_both_versions(monkeypatch, config) -> None:
    # The hub's own JSON in a shape this CLI doesn't know: waiting again would be
    # handed the same turn, unconfirmed, forever.
    from mycelium import __version__
    from mycelium.exceptions import MyceliumError

    unreadable = {key: value for key, value in _TURN.items() if key != "prompt"}
    _answering(monkeypatch, httpx.Response(200, json=unreadable))
    with pytest.raises(MyceliumError, match=f"hub 9.9.9, CLI {__version__}"):
        participate._await_once(config, "r", "agent", timeout=0)
