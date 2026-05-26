# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Top-level daemon orchestrator: load config, fan out SSE subscribers, serve health."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig, daemon_log_path
from mycelium.daemon.dispatch import subscribe_room
from mycelium.daemon.health import start_health_server
from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon")


def _setup_logging(foreground: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if not foreground:
        try:
            handlers.append(logging.FileHandler(daemon_log_path()))
        except OSError:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


async def _amain(foreground: bool) -> int:
    _setup_logging(foreground)

    mycelium_cfg = MyceliumConfig.load()
    daemon_cfg = DaemonConfig.load()

    state = DaemonState()
    state.rooms_configured = list(daemon_cfg.rooms)

    if not daemon_cfg.rooms:
        log.warning(
            "no rooms configured — add some with `mycelium daemon subscribe <room>`. "
            "Health endpoint will stay up so doctor can see me."
        )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, state.stopping.set)
        except NotImplementedError:
            # Windows or unusual environment — fall through to KeyboardInterrupt.
            pass

    server = await start_health_server(state)
    log.info("mycelium-cc-daemon started (rooms=%d)", len(daemon_cfg.rooms))

    sse_tasks = [
        asyncio.create_task(
            subscribe_room(
                config=mycelium_cfg,
                daemon_cfg=daemon_cfg,
                state=state,
                room_name=room,
            ),
            name=f"sse[{room}]",
        )
        for room in daemon_cfg.rooms
    ]

    try:
        await state.stopping.wait()
    finally:
        log.info("shutting down")
        for task in sse_tasks:
            task.cancel()
        for task in sse_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        server.close()
        await server.wait_closed()

    return 0


def main(foreground: bool = False) -> int:
    try:
        return asyncio.run(_amain(foreground))
    except KeyboardInterrupt:
        return 130
