# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Top-level daemon orchestrator: load config, fan out SSE subscribers, serve health."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig, daemon_log_path
from mycelium.daemon.dispatch import poll_coordination_sessions, subscribe_room
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

    # Coordination ticks/consensus events are NOTIFY'd only on the session
    # sub-room channel, never on parent rooms. The poller below discovers
    # active sessions and dynamically attaches an SSE listener to each one
    # — mirrors the openclaw plugin's ``setInterval`` strategy. Without it
    # the daemon misses every coordination_tick after a join.
    session_poller = asyncio.create_task(
        poll_coordination_sessions(
            config=mycelium_cfg,
            daemon_cfg=daemon_cfg,
            state=state,
        ),
        name="coordination-session-poller",
    )

    try:
        await state.stopping.wait()
    finally:
        log.info("shutting down")
        session_poller.cancel()
        try:
            await session_poller
        except (asyncio.CancelledError, Exception):
            pass
        for task in sse_tasks:
            task.cancel()
        for task in sse_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Cancel dynamic session sub-room subscriptions discovered at runtime
        # (started by the coordination-session poller). Mirrors the
        # static-task cleanup above so shutdown is symmetric and the
        # daemon doesn't leak SSE connections.
        for task in list(state.session_room_tasks.values()):
            task.cancel()
        for task in list(state.session_room_tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Reap any in-flight cold-spawn subprocesses BEFORE we close the
        # health socket so the operator gets an accurate count in the log.
        # systemd's default ``KillMode=control-group`` covers ``systemctl
        # stop`` (the cgroup kill propagates to children), but an operator
        # who SIGTERM/SIGINTs the daemon's PID directly — or a launchd
        # bootout outside the cgroup — would otherwise leave running
        # cursor-agent / claude processes wandering. Send SIGTERM, give
        # them a couple of seconds, then SIGKILL whatever's left.
        await _terminate_in_flight_spawns(state)
        server.close()
        await server.wait_closed()

    return 0


async def _terminate_in_flight_spawns(state: DaemonState, *, grace_s: float = 3.0) -> None:
    """Send SIGTERM (then SIGKILL after ``grace_s``) to tracked spawns.

    ``grace_s`` is configurable so tests can drive the SIGKILL-escalation
    branch in milliseconds rather than waiting for the 3-second production
    window. Production callers should stick with the default.
    """
    running = list(state.running.values())
    if not running:
        return
    log.info("terminating %d in-flight spawn(s) on shutdown", len(running))
    for rp in running:
        try:
            if rp.process.returncode is None:
                rp.process.terminate()
        except ProcessLookupError:
            continue
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup, log and move on
            log.warning("terminate(%s) failed: %s", rp.process.pid, exc)
    deadline = asyncio.get_running_loop().time() + grace_s
    for rp in running:
        try:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.wait_for(rp.process.wait(), timeout=remaining)
        except TimeoutError:
            try:
                rp.process.kill()
            except ProcessLookupError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("kill(%s) failed: %s", rp.process.pid, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("wait(%s) failed: %s", rp.process.pid, exc)


def main(foreground: bool = False) -> int:
    try:
        return asyncio.run(_amain(foreground))
    except KeyboardInterrupt:
        return 130
