# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The hub as one program, for the desktop app to bundle (``mycelium-hub``).

PyInstaller builds this into a standalone directory the app ships in its
Resources; ``mycelium desktop serve`` starts it, from a checkout too. Settings
come from the environment, as in the container.

``--host`` can be given more than once: the desktop app's hub listens on
``127.0.0.1`` and, once a machine is paired with it, on the address that
machine reaches it at (``desktop/supervisor.py`` decides which).
"""

import argparse
import multiprocessing
import socket


def _listening(hosts: list[str], port: int) -> list[socket.socket]:
    """A bound, listening socket for each of ``hosts`` on ``port``."""
    made: list[socket.socket] = []
    try:
        for host in hosts:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            made.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(2048)
    except OSError:
        for sock in made:
            sock.close()
        raise
    return made


def main() -> None:
    import uvicorn

    from app.main import app

    parser = argparse.ArgumentParser(prog="mycelium-hub")
    parser.add_argument("--host", action="append", help="An address to listen on (repeatable)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    hosts = list(dict.fromkeys(args.host or ["127.0.0.1"]))
    if len(hosts) == 1:
        uvicorn.run(app, host=hosts[0], port=args.port, log_level="info")
        return
    # Several addresses: one server on a socket for each. A request's address
    # is always its peer's, never one it claims.
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", proxy_headers=False))
    server.run(sockets=_listening(hosts, args.port))


if __name__ == "__main__":
    # The voice worker (app/services/voice_worker.py) is this same program,
    # started again by multiprocessing; this hands it to its job before the
    # hub's own startup, which is also why the app is imported in main().
    multiprocessing.freeze_support()
    main()
