# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Top-level daemon orchestrator: load config, fan out SLIM connectors, serve health."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from mycelium.config import MyceliumConfig
from mycelium.daemon.config import DaemonConfig, daemon_log_path
from mycelium.daemon.connector import connector_targets, run_connector
from mycelium.daemon.health import start_health_server
from mycelium.daemon.state import DaemonState

log = logging.getLogger("mycelium.daemon")

# A connector task is keyed by (room, handle) — one SLIM member subscription per
# owned handle per room.
ConnectorKey = tuple[str, str]


def _setup_logging(foreground: bool) -> None:
    if foreground:
        # Line-buffer stdout so connector/wake logs are visible immediately when
        # stdout is a pipe (not a TTY) — otherwise block-buffering hides them and
        # "nothing happening" looks like a hang (§H). ``reconfigure`` exists on the
        # real TextIOWrapper but not the ``TextIO`` type, so reach it dynamically.
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(line_buffering=True)
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


def _start_connector(
    *,
    mycelium_cfg: MyceliumConfig,
    daemon_cfg: DaemonConfig,
    state: DaemonState,
    room: str,
    handle: str,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        run_connector(
            config=mycelium_cfg,
            daemon_cfg=daemon_cfg,
            state=state,
            room=room,
            handle=handle,
        ),
        name=f"connector[{room}/{handle}]",
    )


async def _reconcile_connectors(
    *,
    mycelium_cfg: MyceliumConfig,
    state: DaemonState,
    connectors: dict[ConnectorKey, asyncio.Task[None]],
) -> None:
    """Add/remove SLIM connectors to match the current DaemonConfig on disk.

    Picks up newly created agents (and dropped rooms/handles) without a full
    daemon restart — the SIGHUP path `mycelium agent create` triggers.
    """
    daemon_cfg = DaemonConfig.load()

    # Refresh the live daemon_cfg so in-flight connectors see new handles.
    if state.daemon_cfg is not None:
        state.daemon_cfg.handles = daemon_cfg.handles
        state.daemon_cfg.rooms = daemon_cfg.rooms

    desired = set(
        connector_targets(
            state.daemon_cfg or daemon_cfg, engine_runtime=mycelium_cfg.engine.runtime
        )
    )
    current = set(connectors.keys())

    for room, handle in desired - current:
        log.info("hot-reload: connecting %s/%s", room, handle)
        connectors[room, handle] = _start_connector(
            mycelium_cfg=mycelium_cfg,
            daemon_cfg=state.daemon_cfg or daemon_cfg,
            state=state,
            room=room,
            handle=handle,
        )

    for key in current - desired:
        room, handle = key
        log.info("hot-reload: disconnecting %s/%s", room, handle)
        task = connectors.pop(key)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    state.rooms_configured = list(daemon_cfg.rooms)
    log.info(
        "hot-reload complete: rooms=%d, handles=%d, connectors=%d",
        len(daemon_cfg.rooms),
        len(daemon_cfg.handles),
        len(connectors),
    )


async def _reload_watcher(
    *,
    mycelium_cfg: MyceliumConfig,
    state: DaemonState,
    connectors: dict[ConnectorKey, asyncio.Task[None]],
) -> None:
    """Wait for reload_requested events and reconcile connectors."""
    while not state.stopping.is_set():
        await state.reload_requested.wait()
        state.reload_requested.clear()
        if state.stopping.is_set():
            break
        await _reconcile_connectors(
            mycelium_cfg=mycelium_cfg,
            state=state,
            connectors=connectors,
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

    targets = connector_targets(daemon_cfg, engine_runtime=mycelium_cfg.engine.runtime)
    log.info(
        "mycelium-daemon started (rooms=%d, connectors=%d)", len(daemon_cfg.rooms), len(targets)
    )

    connectors: dict[ConnectorKey, asyncio.Task[None]] = {
        (room, handle): _start_connector(
            mycelium_cfg=mycelium_cfg,
            daemon_cfg=daemon_cfg,
            state=state,
            room=room,
            handle=handle,
        )
        for room, handle in targets
    }

    reload_task = asyncio.create_task(
        _reload_watcher(
            mycelium_cfg=mycelium_cfg,
            state=state,
            connectors=connectors,
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
        for task in connectors.values():
            task.cancel()
        for task in connectors.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await _terminate_in_flight_spawns(state)
        # Drop the process-wide SLIM dataplane connection (all connectors shared
        # one conn_id per endpoint).
        from mycelium.slim.client import close_connection

        await close_connection(mycelium_cfg.slim.node_endpoint)
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


def _acquire_singleton_lock():
    """Take an exclusive advisory lock so only one daemon runs per host (§H).

    Returns the held file object (keep it open for the process lifetime) or
    ``None`` if another daemon already holds it. No-ops (returns a sentinel) where
    ``fcntl`` is unavailable.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-unix
        return True
    from mycelium.daemon.config import daemon_lock_path

    path = daemon_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = path.open("w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        return None
    fd.write(f"{os.getpid()}\n")
    fd.flush()
    return fd


def main(foreground: bool = False) -> int:
    lock = _acquire_singleton_lock()
    if lock is None:
        from mycelium.daemon.config import daemon_lock_path

        print(  # noqa: T201 - runs before logging is configured
            f"error: another mycelium-daemon is already running (lock held at "
            f"{daemon_lock_path()}). Refusing to start a second — two daemons owning the "
            f"same agent handle collide on the fabric. Stop the other first "
            f"(`pkill -f mycelium.daemon`) or use it.",
            file=sys.stderr,
        )
        return 1
    try:
        return asyncio.run(_amain(foreground))
    except KeyboardInterrupt:
        return 130
