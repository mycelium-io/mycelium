# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the desktop app's hub listens for the machines paired with it
(``desktop.listen``), and the supervisor starting it there again when that
changes."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mycelium.desktop import listen
from mycelium.desktop import supervisor as sv
from mycelium.desktop.listen import Address
from mycelium.desktop.supervisor import Component, Locator, Supervisor

WIREGUARD = Address("utun8", "10.8.0.2")
WIFI = Address("en0", "192.168.68.52")


@pytest.fixture
def where(tmp_path: Path) -> dict[str, Path]:
    data = tmp_path / "data"
    (data / "pairing").mkdir(parents=True)
    config = tmp_path / "config.toml"
    config.write_text('[server]\napi_url = "http://127.0.0.1:3718"\n')
    return {"data_dir": data, "config_path": config}


def _code_waits(where: dict[str, Path], **extra: Any) -> None:
    waiting = {"until": time.time() + 600, "key": "00", "attempts": 0, **extra}
    (where["data_dir"] / "pairing" / "expected.json").write_text(json.dumps({"ABCD": waiting}))


def _paired(where: dict[str, Path], listen_on: str, mid: str = "1") -> None:
    with where["config_path"].open("a") as f:
        f.write(
            f'\n[[hub.paired_machines]]\nname = "box{mid}"\nid = "{mid}"\nlisten = "{listen_on}"\n'
        )


def test_nothing_paired_and_no_code_waiting_is_this_computer_alone(where):
    assert listen.hub_hosts(**where, here=[WIREGUARD, WIFI]) == ["127.0.0.1"]


def test_while_a_code_waits_every_address(where):
    _code_waits(where)
    assert listen.hub_hosts(**where, here=[WIREGUARD, WIFI]) == ["0.0.0.0"]
    # Ended by wrong tries, or expired: not waiting.
    _code_waits(where, dropped=True)
    assert listen.hub_hosts(**where, here=[WIREGUARD, WIFI]) == ["127.0.0.1"]
    assert not listen.window_open(where["data_dir"], now=time.time() + 601)


def test_once_paired_only_the_network_the_machine_came_in_on(where):
    _paired(where, "10.8.0.2")
    assert listen.hub_hosts(**where, here=[WIREGUARD, WIFI]) == ["127.0.0.1", "10.8.0.2"]


def test_the_hub_follows_that_network_s_address_when_it_changes(where):
    """A laptop that joins another Wi-Fi gets another address on the same
    interface: its paired machines on that network aren't shut out."""
    _paired(where, "192.168.68.52")
    assert listen.hub_hosts(**where, here=[WIFI]) == ["127.0.0.1", "192.168.68.52"]
    moved = Address("en0", "10.0.0.14")
    assert listen.hub_hosts(**where, here=[moved, WIREGUARD]) == ["127.0.0.1", "10.0.0.14"]
    # That network down: this computer alone, never every address in its place.
    assert listen.hub_hosts(**where, here=[WIREGUARD]) == ["127.0.0.1"]


def test_an_address_never_seen_on_any_network_here_listens_nowhere(where):
    _paired(where, "192.0.2.7")
    assert listen.hub_hosts(**where, here=[WIREGUARD, WIFI]) == ["127.0.0.1"]


def test_the_dialog_gets_a_join_address_for_each_network():
    assert listen.join_addresses(3718, here=[WIREGUARD, WIFI]) == [
        {"interface": "utun8", "address": "10.8.0.2", "url": "http://10.8.0.2:3718"},
        {"interface": "en0", "address": "192.168.68.52", "url": "http://192.168.68.52:3718"},
    ]
    # This computer's real ones, as ifaddr reads them: loopback left out.
    assert all(a.address != "127.0.0.1" for a in listen.addresses())


def test_the_hub_is_started_on_each_address(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MYCELIUM_HUB_CMD", raising=False)
    resources = tmp_path / "Resources"
    program = resources / "hub" / "mycelium-hub"
    program.parent.mkdir(parents=True)
    program.write_text("")
    program.chmod(0o755)
    loc = Locator(bundle=tmp_path / "MacOS", repo=None)
    monkeypatch.setattr(loc, "_program", lambda name: program if "hub" in name else None)
    argv, _ = loc.hub(3718, ["127.0.0.1", "10.8.0.2"])
    assert argv == [str(program), "--host", "127.0.0.1", "--host", "10.8.0.2", "--port", "3718"]
    assert loc.hub(3718)[0][1:3] == ["--host", "127.0.0.1"]


SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_the_supervisor_starts_the_hub_again_when_where_it_listens_changes(monkeypatch):
    monkeypatch.setattr(sv, "TICK_S", 0.02)
    monkeypatch.setattr(sv, "LISTEN_CHECK_S", 0.0)
    events: list[dict[str, Any]] = []
    sup = Supervisor(
        "hub",
        emit=events.append,
        env={},
        start_runner=False,
        locator=Locator(None, None),
        look=list,
    )
    wanted = {"hosts": ["127.0.0.1"]}
    monkeypatch.setattr(sup, "_wanted_hub_hosts", lambda: list(wanted["hosts"]))
    started: list[list[str]] = []

    def argv():
        started.append(sup._take_hub_hosts())
        return SLEEP, None

    sup.components = [Component(name="hub", argv=argv, ready=lambda: True)]
    hub = sup.components[0]
    sup._tick(hub)
    first = hub.proc
    assert first is not None
    sup._watch_listening()
    assert hub.proc is first  # nothing changed

    wanted["hosts"] = ["0.0.0.0"]  # a code was typed in the app
    sup._watch_listening()
    assert first.poll() is not None
    sup._tick(hub)
    assert started == [["127.0.0.1"], ["0.0.0.0"]]
    assert any("restarting the hub" in e.get("line", "") for e in events)
    sup._terminate(hub)
