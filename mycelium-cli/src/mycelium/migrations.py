# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Run Alembic migrations for Mycelium.

Wheel installs do not ship ``fastapi-backend/`` on the host.  For those
environments we run ``python -m alembic`` inside the ``mycelium-backend``
container, which carries alembic.ini and the migration scripts.

Dev/monorepo installs can still run host-side ``uv run alembic`` when a local
``fastapi-backend/alembic.ini`` is discoverable.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

BACKEND_SERVICE = "mycelium-backend"
BACKEND_CONTAINER = "mycelium-backend"


@dataclass(frozen=True)
class AlembicRunResult:
    """Outcome of an alembic upgrade/current invocation."""

    returncode: int
    stdout: str
    stderr: str
    mode: str  # "host", "container", or "unavailable"


def find_local_backend_dir() -> Path | None:
    """Return fastapi-backend/ when running from a dev checkout, else None."""
    import importlib.resources

    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "fastapi-backend"
            if (candidate / "alembic.ini").exists():
                return candidate
    except Exception:
        pass

    if (Path.cwd() / "alembic.ini").exists():
        return Path.cwd()

    candidate = Path.cwd() / "fastapi-backend"
    if (candidate / "alembic.ini").exists():
        return candidate

    return None


def backend_container_running() -> bool:
    """True when the mycelium-backend container exists and is running."""
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                BACKEND_CONTAINER,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"
    except Exception:
        return False


def _host_alembic_env(backend_dir: Path) -> dict[str, str]:
    from dotenv import dotenv_values

    from mycelium.commands.instance import _get_env_path
    from mycelium.docker_utils import resolve_host_database_url

    env = {**os.environ}
    env_path = _get_env_path()
    if env_path and env_path.exists():
        env.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})

    backend_env = backend_dir / ".env"
    if backend_env.exists():
        env.update({k: v for k, v in dotenv_values(backend_env).items() if v is not None})

    host_url = resolve_host_database_url(env)
    if host_url:
        env["DATABASE_URL"] = host_url
    return env


def _run_host_alembic(backend_dir: Path, alembic_cmd: list[str]) -> AlembicRunResult:
    alembic_args = ["uv", "run", "alembic", *alembic_cmd]
    result = subprocess.run(
        alembic_args,
        cwd=str(backend_dir),
        env=_host_alembic_env(backend_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    return AlembicRunResult(result.returncode, result.stdout, result.stderr, "host")


def _run_container_alembic(alembic_cmd: list[str]) -> AlembicRunResult:
    from mycelium.commands.instance import _compose_base_cmd, _get_compose_path, _get_env_path

    compose_path = _get_compose_path()
    if not compose_path.exists():
        return AlembicRunResult(
            1,
            "",
            f"Compose file not found at {compose_path}",
            "unavailable",
        )

    env_path = _get_env_path()
    cmd = _compose_base_cmd(
        compose_path,
        env_path,
        include_cfn_profile=False,
        include_metrics_profile=False,
        include_ui_profile=False,
    ) + ["exec", "-T", BACKEND_SERVICE, "python", "-m", "alembic", *alembic_cmd]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return AlembicRunResult(result.returncode, result.stdout, result.stderr, "container")


def run_alembic_upgrade(revision: str = "head") -> AlembicRunResult:
    """Apply alembic migrations using the best available backend."""
    backend_dir = find_local_backend_dir()
    if backend_dir is not None:
        return _run_host_alembic(backend_dir, ["upgrade", revision])

    if backend_container_running():
        return _run_container_alembic(["upgrade", revision])

    return AlembicRunResult(
        1,
        "",
        "alembic.ini not found on the host and mycelium-backend is not running",
        "unavailable",
    )


def run_alembic_current() -> AlembicRunResult:
    """Return the current DB revision using the best available backend."""
    backend_dir = find_local_backend_dir()
    if backend_dir is not None:
        return _run_host_alembic(backend_dir, ["current"])

    if backend_container_running():
        return _run_container_alembic(["current"])

    return AlembicRunResult(
        1,
        "",
        "alembic.ini not found on the host and mycelium-backend is not running",
        "unavailable",
    )


def echo_alembic_output(result: AlembicRunResult) -> None:
    """Print alembic stdout/stderr with basic success/error highlighting."""
    import typer

    if result.stdout:
        typer.echo(result.stdout.rstrip())
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            if "Running upgrade" in line:
                typer.secho(f"  {line.split('] ')[-1]}", fg=typer.colors.GREEN)
            elif "ERROR" in line:
                typer.secho(f"  {line}", fg=typer.colors.RED)
