# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the desktop app's hub answers from another machine: a paired one's
requests, and nothing else (``paired_machines``).

A request from this computer passes as before. One from anywhere else passes
only when it carries a paired machine's token from that machine's address, or
when it is the pairing knock itself, which the route checks against a code
typed in the app. Everything else is refused here, before any route or
parser sees it. A hub that doesn't take paired machines lets everything
through, as its own auth settings say.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from app.services import paired_machines

REFUSAL = {
    "detail": (
        "This hub answers only machines paired with it. On this machine, run "
        "`mycelium runner pair --hub <the hub's address>` and type the code it "
        "prints in the app."
    )
}


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _header(scope: dict[str, Any], name: str) -> str | None:
    want = name.lower().encode()
    for key, value in scope.get("headers") or []:
        if key.lower() == want:
            return value.decode("latin-1")
    return None


class MachineGate:
    """ASGI middleware: another machine's request passes only when paired."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket") or not paired_machines.enabled():
            await self.app(scope, receive, send)
            return
        peer = (scope.get("client") or (None,))[0]
        if is_loopback(peer):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope.get("path") == paired_machines.CONNECT_PATH:
            await self.app(scope, receive, send)
            return
        token = _header(scope, paired_machines.MACHINE_HEADER)
        if paired_machines.verify(token, peer) is not None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps(REFUSAL).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
