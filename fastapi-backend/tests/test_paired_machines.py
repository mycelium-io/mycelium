# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Machines paired with the desktop app's hub: the code typed in the app, the
machine's knock, its token, its entry in config.toml, the gate that answers
only paired machines from elsewhere, and where the hub listens."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import socket
import time
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import machine_listen, member_tokens, paired_machines

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
    yield config
    member_tokens.reset_for_tests()


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
    assert (machine["name"], machine["address"]) == ("box", "10.8.0.1")
    # The address of this computer it came in on, which the hub then listens on.
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
        # The right one now finds nothing waiting.
        resp = await box.post("/api/pairing/connect", json=_knock())
    assert resp.status_code == 403
    assert "No code" in resp.json()["detail"]
    assert not paired_machines.window_open()


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
    # From another address than the one it paired from: no.
    assert paired_machines.verify(token, "10.8.0.9") is None

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


def test_where_the_hub_listens(_takes_paired_machines):
    assert machine_listen.wanted() == set()
    paired_machines.expect(CODE)
    assert machine_listen.wanted() == {machine_listen.EVERY}
    paired_machines.add(paired_machines.Machine(name="box", id="1", listen="10.8.0.2"))
    # Once the code is used or expires, only where the machine came in.
    assert machine_listen.wanted(time.time() + paired_machines.WINDOW_S + 1) == {"10.8.0.2"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_listeners_open_and_close_as_machines_are_paired_and_unpaired():
    port = _free_port()
    listeners = machine_listen.Listeners(app, port)
    # A machine "came in" on 127.0.0.1 here, the one address a test can listen on.
    paired_machines.add(paired_machines.Machine(name="box", id="1", listen="127.0.0.1"))
    await listeners.sync()
    assert listeners.hosts == {"127.0.0.1"}
    async with httpx.AsyncClient() as http:
        for _ in range(50):
            try:
                resp = await http.get(f"http://127.0.0.1:{port}/health")
                break
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
        assert resp.status_code == 200
    paired_machines.remove("box")
    await listeners.sync()
    assert listeners.hosts == set()
    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectError):
            await http.get(f"http://127.0.0.1:{port}/health")


async def test_an_address_that_isn_t_there_is_tried_again_not_widened():
    listeners = machine_listen.Listeners(app, _free_port())
    # TEST-NET-1: never one of this computer's addresses.
    paired_machines.add(paired_machines.Machine(name="box", id="1", listen="192.0.2.7"))
    await listeners.sync()
    await listeners.sync()
    assert listeners.hosts == set()
    await listeners.close()
