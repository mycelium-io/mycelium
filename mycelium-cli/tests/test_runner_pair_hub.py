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


def test_a_machine_that_paired_uses_that_hub_in_place_of_its_config(monkeypatch, _home: Path):
    """One rule: the paired hub takes the place of this machine's config, and
    says so; the environment still wins, so another hub is reachable on purpose."""
    from mycelium.config import MyceliumConfig

    config_file = _home / ".mycelium" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('[server]\napi_url = "http://10.8.0.1:8000"\n')
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    config = MyceliumConfig.load()
    assert config.server.api_url == HUB
    assert caller.hub(config) == caller.Answer(HUB, caller.PAIRED)

    # This machine's own hub, named on purpose: the environment wins.
    monkeypatch.setenv("MYCELIUM_API_URL", "http://10.8.0.1:8000")
    config = MyceliumConfig.load()
    assert config.server.api_url == "http://10.8.0.1:8000"
    assert caller.hub(config) == caller.Answer("http://10.8.0.1:8000", caller.ENVIRONMENT)


def test_nothing_switches_hub_because_a_connection_failed(monkeypatch):
    """An agent given a hub that isn't answering (a hub restarting) keeps it."""
    from mycelium.config import MyceliumConfig

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    monkeypatch.setenv("MYCELIUM_API_URL", dead)
    assert MyceliumConfig.load().server.api_url == dead


def test_a_folder_that_joined_a_hub_keeps_its_own(monkeypatch, _home: Path):
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    monkeypatch.setattr(caller, "find_membership", lambda: object())
    assert caller.paired_hub() is None


def test_a_save_doesn_t_write_the_paired_hub_into_this_machine_s_config(_home: Path):
    import tomllib

    from mycelium.config import MyceliumConfig

    path = _home / ".mycelium" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[server]\napi_url = "http://127.0.0.1:3718"\n')
    pairing.save_paired_hub(pairing.PairedHub(hub=HUB, name="box", token="t0k"))
    config = MyceliumConfig.load()
    assert config.server.api_url == HUB
    config.save()
    assert tomllib.loads(path.read_text())["server"]["api_url"] == "http://127.0.0.1:3718"


def test_a_cli_save_leaves_the_hub_s_paired_machines_as_they_are_on_disk(_home: Path):
    """The hub adds and removes these while CLI commands run: a save must
    neither write an empty list (no table may follow it) nor put back a
    machine unpaired since the config was loaded."""
    import tomllib

    from mycelium.config import MyceliumConfig

    path = _home / ".mycelium" / "config.toml"
    MyceliumConfig().save(path)
    assert "paired_machines" not in path.read_text()

    entry = '\n[[hub.paired_machines]]\nname = "box"\nid = "1"\naddress = "10.8.0.1"\n'
    path.write_text(path.read_text() + entry)
    loaded = MyceliumConfig.load(path)
    # The hub takes the box out after this command loaded its config...
    path.write_text(path.read_text().replace(entry, "\n"))
    loaded.save(path)
    # ...and the command's save doesn't put it back.
    assert "paired_machines" not in path.read_text()

    # One the hub added after the load is kept.
    path.write_text(path.read_text() + entry)
    loaded.save(path)
    assert tomllib.loads(path.read_text())["hub"]["paired_machines"][0]["name"] == "box"


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


def test_pairing_says_whether_the_running_runner_will_move(monkeypatch):
    """A runner whose environment names a hub stays there (the environment
    wins), so pairing says so rather than promising it moves."""
    from mycelium.commands import runner as cmd

    monkeypatch.setattr(cmd, "running_pid", lambda: 4242)
    monkeypatch.setattr(cmd, "_env_of", lambda _pid: {"MYCELIUM_API_URL": "http://10.8.0.1:8000"})
    said = cmd._runner_moves()
    assert "MYCELIUM_API_URL set (http://10.8.0.1:8000)" in said
    assert "stays on that hub" in said
    monkeypatch.setattr(cmd, "_env_of", lambda _pid: {"PATH": "/usr/bin"})
    assert cmd._runner_moves() == "The runner moves there at its next heartbeat."
