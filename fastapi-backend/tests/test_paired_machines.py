# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Machines paired with the desktop app's hub: the code typed in the app, the
machine's knock, its token, its entry in config.toml, the gate that answers
only paired machines from elsewhere, and where the hub listens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import socket
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import member_tokens, paired_machines, runners

CODE = "ABCDEFGHJKMN"
BOX = ("10.8.0.1", 40000)
STRANGER = ("192.168.1.50", 40000)
HERE = ("127.0.0.1", 40000)


@pytest.fixture(autouse=True)
def _takes_paired_machines(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('[server]\napi_url = "http://127.0.0.1:3718"\n\n# mine\n')
    monkeypatch.setenv(paired_machines.CONFIG_ENV, str(config))
    monkeypatch.setattr(paired_machines, "_cache", (None, []))
    member_tokens.reset_for_tests()
    runners.registry.clear()
    yield config
    runners.registry.clear()
    member_tokens.reset_for_tests()


def _hello(runner_id: str, label: str) -> dict:
    return {
        "id": runner_id,
        "label": label,
        "owner": "julia",
        "platform": "linux-x86_64",
        "version": "1.0.0",
        "herdr": True,
        "roots": ["/home/agents/work"],
        "frameworks": [],
    }


async def test_a_paired_machine_reaches_only_its_own_runner():
    """This computer's runner starts what its hub queues without asking, so a
    paired machine must never be able to queue anything for it."""
    paired = await _pair()
    box = {paired_machines.MACHINE_HEADER: paired["token"]}
    async with _client(HERE) as here:
        assert (await here.post("/api/runners", json=_hello("mac-1", "Mac"))).status_code < 300
    async with _client(BOX) as remote:
        assert (
            await remote.post("/api/runners", json=_hello("box-1", "box"), headers=box)
        ).status_code < 300
        # Its own runner: through the gate.
        own = await remote.post("/api/runners/box-1/scan", headers=box)
        assert own.status_code != 403, own.text
        # This computer's runner: refused, whatever it asks.
        for method, path in (
            ("post", "/api/runners/mac-1/scan"),
            ("post", "/api/runners/mac-1/launch"),
            ("post", "/api/runners/mac-1/restart"),
            ("get", "/api/runners/mac-1/jobs/next"),
            ("get", "/api/runners/mac-1"),
        ):
            resp = await getattr(remote, method)(path, headers=box)
            assert resp.status_code == 403, (path, resp.status_code)
            assert "its own runner" in resp.json()["detail"]
        # Nor can it say hello as this computer's runner, to take its jobs.
        taken = await remote.post("/api/runners", json=_hello("mac-1", "Mac"), headers=box)
        assert taken.status_code == 403
    assert runners.registry.machine_of("mac-1") is None
    assert runners.registry.machine_of("box-1") == "box"


def test_every_way_of_queueing_work_checks_whose_runner_it_is():
    """Routes outside /runners queue jobs too (rename, pause, interrupt): the
    registry is where every one of them goes, so the check is there."""
    from app.schemas import RunnerHello

    runners.registry.hello(RunnerHello(**_hello("mac-1", "Mac")))
    mark = paired_machines._calling.set("box")
    try:
        with pytest.raises(runners.RunnerRefused):
            runners.registry.enqueue("mac-1", "launch", {}, created_by=None)
    finally:
        paired_machines._calling.reset(mark)
    # From this computer it queues as before.
    assert runners.registry.enqueue("mac-1", "scan", {}, created_by=None).runner == "mac-1"


def test_this_computer_s_runner_takes_its_id_back_from_a_machine_that_said_hello_first():
    from app.schemas import RunnerHello

    mark = paired_machines._calling.set("box")
    try:
        runners.registry.hello(RunnerHello(**_hello("mac-1", "claimed")))
    finally:
        paired_machines._calling.reset(mark)
    assert runners.registry.machine_of("mac-1") == "box"
    runners.registry.hello(RunnerHello(**_hello("mac-1", "Mac")))
    assert runners.registry.machine_of("mac-1") is None


async def test_a_paired_machine_can_t_change_this_computer_s_settings(monkeypatch):
    import json

    from app.services import hub_config

    hub_config.reset()
    monkeypatch.setenv("MYCELIUM_HUB_MODE", "desktop")
    monkeypatch.setenv("MYCELIUM_CONFIG_CLI", json.dumps(["/app/mycelium"]))
    ran: list = []
    monkeypatch.setattr(hub_config, "_run", lambda argv, stdin: ran.append(argv))
    paired = await _pair()
    # Saying it's this computer doesn't make it so.
    looks_local = {
        paired_machines.MACHINE_HEADER: paired["token"],
        "host": "127.0.0.1",
        "origin": "http://127.0.0.1:3717",
    }
    async with _client(BOX) as remote:
        saved = await remote.patch(
            "/api/hub/settings", json={"changes": {"verifier.enabled": True}}, headers=looks_local
        )
        restarted = await remote.post("/api/hub/restart", headers=looks_local)
    assert (saved.status_code, restarted.status_code) == (403, 403)
    assert ran == []
    hub_config.reset()


def _client(peer: tuple[str, int], server: tuple[str, int] = ("10.8.0.2", 3718)) -> AsyncClient:
    transport = ASGITransport(app=app, client=peer)
    return AsyncClient(transport=transport, base_url=f"http://{server[0]}:{server[1]}")


def _knock(name: str = "box", *, code: str = CODE, at: int | None = None) -> dict:
    at = int(time.time()) if at is None else at
    nonce = "n0nce-" + str(at)
    key = hashlib.pbkdf2_hmac(
        "sha256", code.encode(), f"mycelium-pair:{code[:4]}".encode(), 200_000, 32
    )
    mac = hmac.new(key, paired_machines.connect_message(code[:4], name, at, nonce), "sha256")
    proof = base64.urlsafe_b64encode(mac.digest()).rstrip(b"=").decode()
    return {"offer": code[:4], "name": name, "at": at, "nonce": nonce, "proof": proof}


async def _pair(name: str = "box", peer=BOX) -> dict:
    async with _client(HERE) as here:
        assert (
            await here.post("/api/pairing/expect", json={"code": "abcd-efgh-jkmn"})
        ).status_code == 200
    async with _client(peer) as box:
        resp = await box.post("/api/pairing/connect", json=_knock(name))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_machine_that_proves_the_code_typed_in_the_app_is_paired(_takes_paired_machines):
    paired = await _pair()
    machine = paired["machine"]
    # The token is the lock: the machine's own address is a person's to add.
    assert (machine["name"], machine["address"]) == ("box", None)
    # The address of this computer it came in on, which the app then listens on.
    assert machine["listen"] == "10.8.0.2"
    text = _takes_paired_machines.read_text()
    # Written by pairing, and everything the person wrote is left as it was.
    assert text.startswith('[server]\napi_url = "http://127.0.0.1:3718"\n\n# mine\n')
    assert "[[hub.paired_machines]]" in text
    assert [m.name for m in paired_machines.machines()] == ["box"]

    async with _client(BOX) as box:
        ok = await box.get("/health", headers={paired_machines.MACHINE_HEADER: paired["token"]})
        refused = await box.get("/health")
    assert ok.status_code == 200
    assert refused.status_code == 403
    assert "mycelium runner pair --hub" in refused.json()["detail"]


async def test_nothing_from_another_machine_gets_in_without_a_paired_token():
    async with _client(STRANGER) as stranger:
        for path in ("/health", "/api/rooms", "/api/pairing/machines", "/docs"):
            assert (await stranger.get(path)).status_code == 403, path
        # A knock with no code typed in the app.
        assert (await stranger.post("/api/pairing/connect", json=_knock())).status_code == 403
    async with _client(HERE) as here:
        assert (await here.get("/health")).status_code == 200


async def test_only_this_computer_can_open_the_window_or_list_and_remove_machines():
    async with _client(BOX) as box:
        # Refused at the gate, before the route.
        assert (await box.post("/api/pairing/expect", json={"code": CODE})).status_code == 403
    await _pair()
    async with _client(HERE) as here:
        assert [m["name"] for m in (await here.get("/api/pairing/machines")).json()] == ["box"]
        assert (await here.delete("/api/pairing/machines/box")).status_code == 204
        assert (await here.get("/api/pairing/machines")).json() == []


async def test_a_wrong_proof_counts_against_the_code_and_five_end_it():
    async with _client(HERE) as here:
        await here.post("/api/pairing/expect", json={"code": CODE})
    wrong = _knock(code="ABCDQQQQQQQQ")
    async with _client(BOX) as box:
        for _ in range(paired_machines.MAX_ATTEMPTS):
            assert (await box.post("/api/pairing/connect", json=wrong)).status_code == 403
        # The right one is now refused too, and told why.
        resp = await box.post("/api/pairing/connect", json=_knock())
    assert resp.status_code == 403
    assert "dropped after too many wrong tries" in resp.json()["detail"]
    # Nothing waits any more, so the hub stops listening on every address.
    assert not paired_machines.window_open()


async def test_a_knock_from_this_computer_is_refused():
    """A tunnel on this computer makes another machine look like this one, and
    a token from a loopback knock would be good from any address."""
    async with _client(HERE) as here:
        await here.post("/api/pairing/expect", json={"code": CODE})
        resp = await here.post("/api/pairing/connect", json=_knock())
    assert resp.status_code == 403
    assert "not a tunnel" in resp.json()["detail"]
    assert paired_machines.machines() == []
    # The code still waits for the machine's own address.
    assert paired_machines.window_open()


async def test_pairing_into_a_config_the_cli_saved(_takes_paired_machines):
    """What the CLI wrote before it stopped writing the key: an empty list
    under [hub], which no [[hub.paired_machines]] table may follow."""
    _takes_paired_machines.write_text(
        '[server]\napi_url = "http://127.0.0.1:3718"\n\n[hub]\npaired_machines = []\n\n'
        "[statusline]\nwidget = []\n"
    )
    paired = await _pair()
    assert [m.name for m in paired_machines.machines()] == ["box"]
    assert paired_machines.verify(paired["token"], "10.8.0.1") is not None
    import tomllib

    parsed = tomllib.loads(_takes_paired_machines.read_text())
    assert parsed["server"]["api_url"] == "http://127.0.0.1:3718"
    assert parsed["statusline"]["widget"] == []


async def test_a_knock_from_the_wrong_time_or_after_the_window_is_refused():
    async with _client(HERE) as here:
        await here.post("/api/pairing/expect", json={"code": CODE})
    async with _client(BOX) as box:
        stale = await box.post("/api/pairing/connect", json=_knock(at=int(time.time()) - 3600))
    assert stale.status_code == 403
    assert paired_machines.window_open()
    assert not paired_machines.window_open(time.time() + paired_machines.WINDOW_S + 1)


async def test_a_code_works_once():
    await _pair()
    async with _client(BOX) as box:
        again = await box.post("/api/pairing/connect", json=_knock())
    assert again.status_code == 403


async def test_removing_the_entry_or_pairing_again_ends_the_old_token(_takes_paired_machines):
    first = await _pair()
    token = first["token"]
    assert paired_machines.verify(token, "10.8.0.1") is not None

    second = await _pair()
    assert paired_machines.verify(token, "10.8.0.1") is None
    assert paired_machines.verify(second["token"], "10.8.0.1") is not None
    assert _takes_paired_machines.read_text().count("[[hub.paired_machines]]") == 1

    # Taking the entry out by hand works the same.
    paired_machines.remove("box")
    assert paired_machines.verify(second["token"], "10.8.0.1") is None


async def test_a_machine_can_leave_with_its_own_token():
    paired = await _pair()
    async with _client(BOX) as box:
        headers = {paired_machines.MACHINE_HEADER: paired["token"]}
        assert (await box.delete("/api/pairing/self", headers=headers)).status_code == 204
        assert (await box.get("/health", headers=headers)).status_code == 403
    assert paired_machines.machines() == []


def test_a_member_token_is_never_a_machine_token():
    paired_machines.add(paired_machines.Machine(name="box", id="abc"))
    member, _ = member_tokens.mint("box", "room")
    assert paired_machines.verify(member, None) is None


def test_removing_an_entry_keeps_everything_else_in_the_file(_takes_paired_machines):
    paired_machines.add(paired_machines.Machine(name="box", id="1", address="10.8.0.1"))
    paired_machines.add(paired_machines.Machine(name="laptop", id="2"))
    with _takes_paired_machines.open("a") as f:
        f.write('\n[[statusline.widget]]\nlabel = "disk"\ntext = "ok"\n')
    paired_machines.remove("box")
    text = _takes_paired_machines.read_text()
    assert "# mine" in text and 'label = "disk"' in text
    assert [m.name for m in paired_machines.machines()] == ["laptop"]


async def test_a_hub_that_takes_no_paired_machines_is_as_before(monkeypatch):
    monkeypatch.delenv(paired_machines.CONFIG_ENV)
    async with _client(STRANGER) as stranger:
        assert (await stranger.get("/health")).status_code == 200
        assert (await stranger.post("/api/pairing/expect", json={"code": CODE})).status_code == 404


def test_an_address_a_person_adds_limits_the_token_to_it():
    """Pairing doesn't set the machine's own address (a laptop's changes);
    a person can, and then the token works from there alone."""
    paired_machines.add(paired_machines.Machine(name="box", id="1", address="10.8.0.1"))
    token = paired_machines.mint(paired_machines.machines()[0])
    assert paired_machines.verify(token, "10.8.0.1") is not None
    assert paired_machines.verify(token, "10.8.0.9") is None


def test_the_hub_listens_on_every_address_it_is_given():
    """``hub_entry --host a --host b``: a socket on each, on one port."""
    import hub_entry

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    hosts = ["127.0.0.1"]
    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6) as six:
                six.bind(("::1", 0))
            hosts.append("::1")
        except OSError:
            pass
    socks = hub_entry._listening(hosts, port)
    try:
        assert [s.getsockname()[:2] for s in socks] == [(h, port) for h in hosts]
    finally:
        for s in socks:
            s.close()
    # An address this computer doesn't have isn't listened on, and nothing is left open.
    with pytest.raises(OSError):
        hub_entry._listening(["127.0.0.1", "192.0.2.7"], port)
    with socket.socket() as again:
        again.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        again.bind(("127.0.0.1", port))
