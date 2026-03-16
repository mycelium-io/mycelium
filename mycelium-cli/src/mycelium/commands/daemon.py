"""
Daemon commands for Mycelium CLI.

Simplified daemon: polls for pending runs and sends heartbeats.
No Docker container management — that's CFN's job.
"""

import json as json_module
import logging
import os
import signal
import time
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error

app = typer.Typer(help="Daemon management commands")
logger = logging.getLogger(__name__)

_DAEMON_PID_FILE = Path.home() / ".mycelium" / "daemon.pid"
_POLL_INTERVAL = 10  # seconds
_HEARTBEAT_INTERVAL = 30  # seconds


def is_daemon_running() -> bool:
    """Check if the daemon is currently running."""
    if not _DAEMON_PID_FILE.exists():
        return False
    try:
        pid = int(_DAEMON_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def _write_pid() -> None:
    _DAEMON_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DAEMON_PID_FILE.write_text(str(os.getpid()))


def _clear_pid() -> None:
    if _DAEMON_PID_FILE.exists():
        _DAEMON_PID_FILE.unlink()


def _daemon_loop(config: MyceliumConfig, handle: str) -> None:
    """Main daemon polling loop."""
    last_heartbeat = 0.0
    running = True

    def _handle_signal(sig: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(f"Daemon started. Handle: {handle}")

    while running:
        now = time.time()

        try:
            # Placeholder: future polling logic goes here
            last_heartbeat = now

        except Exception as e:
            logger.error(f"Daemon error: {e}")

        time.sleep(_POLL_INTERVAL)

    _clear_pid()
    logger.info("Daemon stopped.")


@app.callback()
def daemon_main(ctx: typer.Context) -> None:
    """Daemon management — polls for runs and sends heartbeats."""


def start(
    ctx: typer.Context,
    restart: bool = typer.Option(False, "--restart", help="Restart if already running"),
) -> None:
    """Start the Mycelium daemon in the background."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841

        if is_daemon_running() and not restart:
            typer.echo("Daemon already running.")
            return

        if is_daemon_running() and restart:
            stop(ctx)

        config = MyceliumConfig.load()
        handle = config.get_current_identity()

        # Fork to background
        pid = os.fork()
        if pid == 0:
            # Child process
            os.setsid()
            _write_pid()
            _daemon_loop(config, handle)
            os._exit(0)
        else:
            typer.secho(f"Daemon started (PID {pid})", fg=typer.colors.GREEN)

    except AttributeError:
        # Windows — no fork
        typer.echo("Background daemon not supported on Windows. Run 'mycelium daemon run' instead.")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command("start")
def start_cmd(
    ctx: typer.Context,
    restart: bool = typer.Option(False, "--restart"),
) -> None:
    """Start the Mycelium daemon."""
    start(ctx, restart=restart)


@app.command("stop")
def stop(ctx: typer.Context) -> None:
    """Stop the Mycelium daemon."""
    try:
        if not is_daemon_running():
            typer.echo("Daemon is not running.")
            return

        pid = int(_DAEMON_PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        typer.secho("Daemon stopped.", fg=typer.colors.GREEN)

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command("status")
def daemon_status(ctx: typer.Context) -> None:
    """Show daemon status."""
    json_output = ctx.obj.get("json", False) if ctx.obj else False

    running = is_daemon_running()
    pid = None
    if running and _DAEMON_PID_FILE.exists():
        try:
            pid = int(_DAEMON_PID_FILE.read_text().strip())
        except ValueError:
            pass

    if json_output:
        typer.echo(json_module.dumps({"running": running, "pid": pid}))
    else:
        if running:
            typer.secho(f"Daemon running (PID {pid})", fg=typer.colors.GREEN)
        else:
            typer.secho("Daemon not running", fg=typer.colors.YELLOW)
            typer.echo("  Start with: mycelium daemon start")


@app.command("run")
def run_foreground(ctx: typer.Context) -> None:
    """Run the daemon in the foreground (for debugging)."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        logging.basicConfig(level=logging.INFO)

        config = MyceliumConfig.load()
        handle = config.get_current_identity()

        typer.echo(f"Running daemon in foreground. Handle: {handle}")
        typer.echo("Press Ctrl+C to stop.")

        _write_pid()
        _daemon_loop(config, handle)

    except KeyboardInterrupt:
        typer.echo("\nDaemon stopped.")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
