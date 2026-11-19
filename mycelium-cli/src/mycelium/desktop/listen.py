# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the desktop app's hub listens, for the machines paired with it.

The hub decides who it answers (its gate answers another machine only with a
paired machine's token); the app decides where it listens, and starts it
there (``--host``, given once per address):

- **Nothing paired, no code waiting:** ``127.0.0.1``, as always.
- **A code typed in the app, waiting for its machine** (ten minutes at most):
  every address, since nothing says yet which network the machine is on. The
  gate refuses everything there but the pairing knock.
- **Machines paired:** ``127.0.0.1`` and, for each, the address this
  computer has *now* on the network interface the machine came in on. A
  laptop's address on its Wi-Fi changes as it moves; the interface (``en0``,
  ``utun8``) doesn't, so the hub follows it. An interface that's down adds
  nothing, and the hub is never widened to every address in its place.

Which interface each machine came in on is worked out the first time it's
seen, from the address it reached (its entry's ``listen``), and remembered in
``desktop-pairing.json`` beside ``config.toml``.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import toml

LOOPBACK = "127.0.0.1"
EVERY = "0.0.0.0"  # noqa: S104 - only while a code waits, behind the hub's gate
#: Where the interface each paired machine came in on is remembered.
REMEMBERED = "desktop-pairing.json"


@dataclass(frozen=True)
class Address:
    """One of this computer's IPv4 addresses and the interface it's on."""

    interface: str
    address: str


def addresses() -> list[Address]:
    """This computer's IPv4 addresses on its network interfaces, loopback left out."""
    import ifaddr

    found: list[Address] = []
    with contextlib.suppress(Exception):
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if not isinstance(ip.ip, str):
                    continue  # IPv6 comes as a tuple
                with contextlib.suppress(ValueError):
                    if ipaddress.ip_address(ip.ip).is_loopback:
                        continue
                    found.append(Address(interface=str(adapter.name), address=ip.ip))
    return found


def window_open(data_dir: Path, now: float | None = None) -> bool:
    """Whether a code typed in the app waits for its machine (the hub's
    ``pairing/expected.json``; a code ended by wrong tries doesn't)."""
    now = time.time() if now is None else now
    try:
        expected = json.loads((data_dir / "pairing" / "expected.json").read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(expected, dict):
        return False
    return any(
        isinstance(w, dict)
        and not w.get("dropped")
        and isinstance(w.get("until"), (int, float))
        and w["until"] > now
        for w in expected.values()
    )


def paired(config_path: Path) -> dict[str, str]:
    """Each paired machine's id and the address of this computer it reached."""
    try:
        hub = toml.loads(config_path.read_text(encoding="utf-8")).get("hub") or {}
    except (OSError, ValueError, TypeError):
        return {}
    rows = hub.get("paired_machines") if isinstance(hub, dict) else None
    found: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if (
            isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and isinstance(row.get("listen"), str)
        ):
            found[row["id"]] = row["listen"]
    return found


def _remembered(path: Path) -> dict[str, str]:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, str)} if isinstance(found, dict) else {}


def hub_hosts(
    *,
    data_dir: Path,
    config_path: Path,
    remembered: Path | None = None,
    now: float | None = None,
    here: list[Address] | None = None,
) -> list[str]:
    """The addresses the hub should listen on now, in order."""
    if window_open(data_dir, now):
        return [EVERY]
    machines = paired(config_path)
    if not machines:
        return [LOOPBACK]
    here = addresses() if here is None else here
    remembered = remembered or config_path.parent / REMEMBERED
    interfaces = _remembered(remembered)
    learned = False
    for mid, listen in machines.items():
        if mid not in interfaces:
            on = next((a.interface for a in here if a.address == listen), None)
            if on is not None:
                interfaces[mid] = on
                learned = True
    if learned:
        with contextlib.suppress(OSError):
            remembered.write_text(json.dumps(interfaces, indent=2) + "\n")
    hosts = [LOOPBACK]
    for mid in machines:
        on = interfaces.get(mid)
        for a in here:
            if a.interface == on and a.address not in hosts:
                hosts.append(a.address)
    return hosts


def join_addresses(port: int, here: list[Address] | None = None) -> list[dict[str, Any]]:
    """What another machine would give ``runner pair --hub``: one per address
    of this computer, with the interface it's on, for the Add machine dialog."""
    here = addresses() if here is None else here
    return [
        {"interface": a.interface, "address": a.address, "url": f"http://{a.address}:{port}"}
        for a in here
    ]
