# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the desktop app's hub listens besides ``127.0.0.1``.

Nowhere, while nothing is paired and no code is waiting. While a code typed in
the app waits for its machine (ten minutes at most), on every address, since
the hub can't know yet which one the machine will use; the gate
(``machine_gate``) refuses anything there but the pairing knock. Once a
machine is paired, on the one address of this computer it came in on (its
entry's ``listen``), and nowhere else.

The listeners run in the hub's own process and event loop, beside the server
on ``127.0.0.1``, and are opened and closed as that changes, without a
restart. An address that isn't there (a VPN that's down) is tried again until
it is; the hub never widens to every address to make up for it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import sys
from typing import Any

from app.services import paired_machines

logger = logging.getLogger(__name__)

#: The port the hub's own server is on, which the desktop app sets.
PORT_ENV = "MYCELIUM_HUB_PORT"
#: Every address, for while a code waits.
EVERY = "0.0.0.0"
#: How often what the hub listens on is checked.
EVERY_S = 2.0


def port() -> int | None:
    try:
        return int(os.environ.get(PORT_ENV, ""))
    except ValueError:
        return None


def wanted(now: float | None = None) -> set[str]:
    """The addresses to listen on besides ``127.0.0.1``."""
    if not paired_machines.enabled():
        return set()
    hosts = {m.listen for m in paired_machines.machines() if m.listen}
    if paired_machines.window_open(now):
        hosts.add(EVERY)
    return hosts


def _linux_addresses() -> list[str]:
    """This computer's IPv4 addresses, for Linux, where a socket on every
    address can't sit beside the one on ``127.0.0.1``."""
    import fcntl
    import struct

    found = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            with contextlib.suppress(OSError):
                raw = fcntl.ioctl(
                    probe.fileno(), 0x8915, struct.pack("256s", name[:15].encode())
                )  # SIOCGIFADDR
                addr = socket.inet_ntoa(raw[20:24])
                if not addr.startswith("127."):
                    found.append(addr)
    finally:
        probe.close()
    return found


def _sockets(host: str, on: int) -> list[socket.socket]:
    """Bound, listening sockets for ``host`` on port ``on``."""
    hosts = [host]
    if host == EVERY and sys.platform.startswith("linux"):
        hosts = _linux_addresses()
    made = []
    try:
        for h in hosts:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            made.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((h, on))
            sock.listen(128)
            sock.setblocking(False)
    except OSError:
        for sock in made:
            sock.close()
        raise
    return made


class Listeners:
    """The hub's listeners besides ``127.0.0.1``, kept to :func:`wanted`."""

    def __init__(self, app: Any, on: int) -> None:
        self.app = app
        self.port = on
        self._running: dict[str, tuple[Any, asyncio.Task]] = {}
        self._failed: set[str] = set()

    @property
    def hosts(self) -> set[str]:
        return set(self._running)

    async def sync(self, now: float | None = None) -> None:
        want = wanted(now)
        for host in sorted(set(self._running) - want):
            await self._close(host)
        for host in sorted(want - set(self._running)):
            self._open(host)

    def _open(self, host: str) -> None:
        import uvicorn

        try:
            socks = _sockets(host, self.port)
        except OSError as e:
            if host not in self._failed:
                logger.warning("pairing: can't listen on %s:%s yet: %s", host, self.port, e)
                self._failed.add(host)
            return
        self._failed.discard(host)
        # No proxy headers: a request's address is its peer's, never one it claims.
        config = uvicorn.Config(self.app, lifespan="off", log_level="warning", proxy_headers=False)
        server = uvicorn.Server(config)
        # ``_serve`` rather than ``serve``: the hub's own server keeps the signals.
        task = asyncio.create_task(server._serve(sockets=socks))
        self._running[host] = (server, task)
        logger.info("pairing: listening on %s:%s for paired machines", host, self.port)

    async def _close(self, host: str) -> None:
        server, task = self._running.pop(host)
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)
        if not task.done():
            task.cancel()
        logger.info("pairing: stopped listening on %s:%s", host, self.port)

    async def close(self) -> None:
        for host in list(self._running):
            await self._close(host)

    async def run(self) -> None:
        try:
            while True:
                try:
                    await self.sync()
                except Exception:
                    logger.exception("pairing: couldn't update where the hub listens")
                await asyncio.sleep(EVERY_S)
        finally:
            await self.close()
