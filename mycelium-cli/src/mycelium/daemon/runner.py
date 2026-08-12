# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Top-level daemon orchestrator: load config, fan out SSE subscribers, serve health."""

from __future__ import annotations

import asyncio
import logging
import signal

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig, daemon_log_path
from mycelium.daemon.dispatch import (
    poll_coordination_sessions,
    reconcile_local_rooms,
    subscribe_room,
)
from mycelium.daemon.health import start_health_server
from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon")


def _setup_logging(foreground: bool) -> None:
    if foreground:
        handlers: list[logging.Handler] = [logging.StreamHandler()]
    else:
        # Under systemd/launchd the unit file already routes stdout+stderr to
        # `daemon_log_path()` via `StandardOutput=append:` /
        # `StandardOutPath`. If we *also* attach a Python ``FileHandler`` for
        # the same path every record lands in the file twice — once via the
        # supervisor's stdout capture (the StreamHandler) and once via the
        # FileHandler. Pick exactly one sink: write through the FileHandler
        # and let the supervisor's stdout/stderr append be a no-op. If the
        # file can't be opened (e.g. permission denied) we fall back to
        # stderr so the operator still sees the failure.
        try:
            handlers = [logging.FileHandler(daemon_log_path())]
        except OSError:
            handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


async def _reconcile_rooms(
    *,
    mycelium_cfg: MyceliumConfig,
    state: DaemonState,
    sse_tasks: dict[str, asyncio.Task[None]],
) -> None:
    """Add/remove SSE tasks to match the current DaemonConfig on disk.

    Also refreshes the handles list so newly created agents are dispatched
    without a full daemon restart.
    """
    daemon_cfg = DaemonConfig.load()
    desired = set(daemon_cfg.rooms)
    current = set(sse_tasks.keys())

    # Exclude tombstoned rooms from desired so their completed SSE tasks are
    # cleaned up even when _handle_room_deleted could not update the config file.
    # Tombstones are never cleared at hot-reload time — they are set by 404,
    # room_deleted events, or startup reconcile, and cleared only on restart
    # (when fresh reconcile can confirm hub status with a live request).
    effective_desired = desired - state.rooms_deleted

    # Refresh handles on the live daemon_cfg so dispatch sees new agents
    if state.daemon_cfg is not None:
        state.daemon_cfg.handles = daemon_cfg.handles
        state.daemon_cfg.rooms = daemon_cfg.rooms

    for room in effective_desired - current:
        log.info("hot-reload: subscribing to %s", room)
        sse_tasks[room] = asyncio.create_task(
            subscribe_room(
                config=mycelium_cfg,
                daemon_cfg=state.daemon_cfg or daemon_cfg,
                state=state,
                room_name=room,
            ),
            name=f"sse[{room}]",
        )

    for room in current - effective_desired:
        log.info("hot-reload: unsubscribing from %s", room)
        task = sse_tasks.pop(room)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        state.rooms_connected.discard(room)

    state.rooms_configured = list(effective_desired)
    log.info(
        "hot-reload complete: rooms=%d, handles=%d",
        len(effective_desired),
        len(daemon_cfg.handles),
    )


async def _reload_watcher(
    *,
    mycelium_cfg: MyceliumConfig,
    state: DaemonState,
    sse_tasks: dict[str, asyncio.Task[None]],
) -> None:
    """Wait for reload_requested events and reconcile room subscriptions."""
    while not state.stopping.is_set():
        await state.reload_requested.wait()
        state.reload_requested.clear()
        if state.stopping.is_set():
            break
        await _reconcile_rooms(
            mycelium_cfg=mycelium_cfg,
            state=state,
            sse_tasks=sse_tasks,
        )


async def _amain(foreground: bool) -> int:
    _setup_logging(foreground)

    mycelium_cfg = MyceliumConfig.load()
    daemon_cfg = DaemonConfig.load()

    state = DaemonState()
    state.rooms_configured = list(daemon_cfg.rooms)
    state.daemon_cfg = daemon_cfg

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
            pass

    try:
        loop.add_signal_handler(signal.SIGHUP, state.reload_requested.set)
    except (NotImplementedError, AttributeError):
        pass

    server = await start_health_server(state)
    log.info("mycelium-daemon started (rooms=%d)", len(daemon_cfg.rooms))

    # Pull-based reconciliation: verify local room dirs against the hub so
    # rooms deleted while this spoke was offline are surfaced (or auto-cleaned
    # when daemon.auto_gc_orphaned_rooms is True).
    # The returned set of orphaned room names seeds state.rooms_deleted so
    # _reconcile_rooms never spawns 404-retry SSE tasks for rooms that are gone.
    try:
        orphaned_rooms = await reconcile_local_rooms(mycelium_cfg)
    except Exception as exc:
        log.warning("Startup room reconcile raised unexpectedly: %s", exc)
        orphaned_rooms: set[str] = set()

    state.rooms_deleted.update(orphaned_rooms)

    # Reload so the in-memory daemon_cfg reflects whatever reconcile_local_rooms
    # wrote to disk (it may have removed orphaned rooms from the subscription list).
    try:
        daemon_cfg = DaemonConfig.load()
        state.rooms_configured = list(daemon_cfg.rooms)
        state.daemon_cfg = daemon_cfg
    except Exception as exc:
        log.warning("Could not reload daemon config after startup reconcile: %s", exc)

    sse_tasks: dict[str, asyncio.Task[None]] = {
        room: asyncio.create_task(
            subscribe_room(
                config=mycelium_cfg,
                daemon_cfg=daemon_cfg,
                state=state,
                room_name=room,
            ),
            name=f"sse[{room}]",
        )
        for room in daemon_cfg.rooms
        if room not in state.rooms_deleted
    }

    session_poller = asyncio.create_task(
        poll_coordination_sessions(
            config=mycelium_cfg,
            daemon_cfg=daemon_cfg,
            state=state,
        ),
        name="coordination-session-poller",
    )

    reload_task = asyncio.create_task(
        _reload_watcher(
            mycelium_cfg=mycelium_cfg,
            state=state,
            sse_tasks=sse_tasks,
        ),
        name="reload-watcher",
    )

    try:
        await state.stopping.wait()
    finally:
        log.info("shutting down")
        reload_task.cancel()
        try:
            await reload_task
        except (asyncio.CancelledError, Exception):
            pass
        session_poller.cancel()
        try:
            await session_poller
        except (asyncio.CancelledError, Exception):
            pass
        for task in sse_tasks.values():
            task.cancel()
        for task in sse_tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(state.session_room_tasks.values()):
            task.cancel()
        for task in list(state.session_room_tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
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
