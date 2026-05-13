# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Minimal HTTP-over-unix-socket health endpoint.

The doctor and `mycelium daemon status` poll this for liveness + last-run
information without going through the network. Implemented by hand to keep
the daemon's dependency surface flush with the rest of the CLI (httpx +
stdlib) rather than pulling in starlette/asgi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from mycelium.daemon.config import daemon_socket_path
from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon.health")


def health_payload(state: DaemonState) -> dict[str, Any]:
    rooms_subscribed = sorted(state.rooms_connected)
    agents_registered = 0
    for room in state.rooms_configured:
        from mycelium.daemon.dispatch import list_agent_handles

        try:
            agents_registered += len(list_agent_handles(room))
        except Exception:
            pass
    return {
        "status": "ok",
        "uptime_s": int(time.monotonic() - state.started_at),
        "rooms_configured": list(state.rooms_configured),
        "rooms_subscribed": rooms_subscribed,
        "agents_registered": agents_registered,
        "last_dispatch": state.last_dispatch,
        "last_error": state.last_error,
        "errors_last_hour": state.errors_in_last_hour(),
    }


async def _handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: DaemonState
) -> None:
    try:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        except TimeoutError:
            writer.close()
            return

        # Drain headers (we don't need them).
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not line or line in (b"\r\n", b"\n"):
                break

        method_path = request_line.decode("latin-1", errors="replace").strip().split(" ")
        path = method_path[1] if len(method_path) >= 2 else "/"

        if path.split("?", 1)[0] != "/health":
            body = b"not found\n"
            writer.write(
                b"HTTP/1.1 404 Not Found\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
        else:
            payload = json.dumps(health_payload(state), default=str).encode("utf-8")
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + payload
            )
        await writer.drain()
    except Exception as exc:
        log.warning("health handler error: %s", exc)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_health_server(state: DaemonState) -> asyncio.AbstractServer:
    socket_path = daemon_socket_path()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove any stale socket from a previous run.
    if socket_path.exists():
        try:
            socket_path.unlink()
        except OSError:
            pass

    async def cb(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        await _handle_client(r, w, state)

    server = await asyncio.start_unix_server(cb, path=str(socket_path))
    socket_path.chmod(0o600)
    log.info("health socket listening at %s", socket_path)
    return server


def read_health_blocking(timeout: float = 2.0) -> dict[str, Any] | None:
    """Synchronous health probe — used by `mycelium daemon status` + doctor.

    Returns None when the socket isn't present or the daemon isn't responsive.
    """
    import socket

    path: Path = daemon_socket_path()
    if not path.exists():
        return None

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(path))
        s.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        return None
    finally:
        s.close()

    raw = b"".join(chunks)
    sep = raw.find(b"\r\n\r\n")
    if sep == -1:
        return None
    body = raw[sep + 4 :]
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
