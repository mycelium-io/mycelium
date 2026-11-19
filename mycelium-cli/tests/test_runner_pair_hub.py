# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A machine joining the desktop app's hub by pairing (``runner pair --hub``):
its knock, the token it keeps, which requests carry it, and the hub its
agents and runner use once it has one."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
from pathlib import Path

import httpx
import pytest

from mycelium import caller, client
from mycelium.runner import pairing

CODE = "ABCDEFGHJKMN"
HUB = "http://10.8.0.2:3718"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MYCELIUM_API_URL", raising=False)
    return tmp_path


def _hub_answers(status: int, body: dict) -> tuple[httpx.MockTransport, list[dict]]:
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle), seen


def test_a_knock_proves_the_code_without_sending_it():
    body = pairing.knock_body("abcd-efgh-jkmn", "box")
    assert body["offer"] == "ABCD"
    assert CODE not in json.dumps(body)
    # The hub checks it the same way: an HMAC keyed by the code's key.
    key = hashlib.pbkdf2_hmac("sha256", CODE.encode(), b"mycelium-pair:ABCD", 200_000, 32)
    message = f"mycelium-connect-v1\nABCD\nbox\n{body['at']}\n{body['nonce']}".encode()
    want = pairing.b64url(hmac.new(key, message, "sha256").digest())
    assert body["proof"] == want
    # A fresh nonce every knock.
    assert pairing.knock_body(CODE, "box")["nonce"] != body["nonce"]


def test_a_knock_says_what_the_hub_said_until_it_joins():
    waiting, _ = _hub_answers(
        403, {"detail": "No code for this machine is waiting on the hub yet."}
    )
    said = pairing.knock(HUB, CODE, "box", transport=waiting)
    assert isinstance(said, str)
    assert said.startswith("No code")

    joined, seen = _hub_answers(200, {"token": "t0k", "machine": {"name": "box", "id": "1"}})
    got = pairing.knock(HUB, CODE, "box", transport=joined)
    assert got == pairing.PairedHub(hub=HUB, name="box", token="t0k")
    assert seen[0]["name"] == "box"


def test_a_hub_that_isn_t_there_is_said_plainly():
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    said = pairing.knock(HUB, CODE, "box", transport=httpx.MockTransport(down))
    assert isinstance(said, str)
    assert said.startswith(f"can't reach {HUB}")


def test_the_token_is_kept_for_this_user_only_and_can_be_forgotten(_home: Path):
    assert pairing.paired_hub() is None
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    path = _home / ".mycelium" / "paired-hub.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert pairing.paired_hub() == pairing.PairedHub(hub=HUB, name="box", token="t0k")
    pairing.forget_paired_hub()
    assert pairing.paired_hub() is None


def test_only_requests_to_the_paired_hub_carry_the_token():
    assert client.machine_headers(HUB) == {}
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    assert client.machine_headers(HUB + "/api/rooms") == {"X-Mycelium-Machine": "t0k"}
    assert client.machine_headers("http://10.8.0.9:3718") == {}
    assert client.machine_headers("http://127.0.0.1:3718") == {}


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_an_agent_started_on_a_tunnel_finds_the_paired_hub_once_the_tunnel_is_gone(monkeypatch):
    dead = f"http://127.0.0.1:{_closed_port()}"
    # Not paired: the address it was given stands.
    assert caller.follow_paired_hub(dead) == dead
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    assert caller.follow_paired_hub(dead) == HUB

    from mycelium.config import MyceliumConfig

    monkeypatch.setenv("MYCELIUM_API_URL", dead)
    config = MyceliumConfig.load()
    assert config.server.api_url == HUB
    assert caller.hub(config) == caller.Answer(HUB, caller.PAIRED)


def test_a_local_address_that_answers_or_a_remote_one_is_kept():
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen(1)
        alive = f"http://127.0.0.1:{listening.getsockname()[1]}"
        assert caller.follow_paired_hub(alive) == alive
    assert caller.follow_paired_hub("http://hub.example.com:8000") == "http://hub.example.com:8000"


def test_the_runner_moves_to_the_hub_this_machine_paired_with(tmp_path: Path):
    from mycelium.config import MyceliumConfig
    from mycelium.runner.daemon import Runner

    config = MyceliumConfig()
    config.server.api_url = "http://127.0.0.1:3718"
    runner = Runner.__new__(Runner)
    runner.config = config
    runner.connected = True

    class Log:
        def print(self, *_a, **_k) -> None:
            pass

    runner.log = Log()
    runner._follow_paired_hub()
    assert config.server.api_url == "http://127.0.0.1:3718"

    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    runner._follow_paired_hub()
    assert config.server.api_url == HUB
    assert runner.connected is False
