# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Install command for Mycelium CLI.

Phases:
  1. Hex animation + real system checks + public image pulls
  2. Interactive prompt (LLM config)
  3. Real docker compose up (streaming output)
  4. Health polling
  5. Provision default workspace + MAS in the backend
  6. Config write to ~/.mycelium/config.toml
"""

import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import typer

from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

LOG_WINDOW = 4

# Public images that are always pulled regardless of profile.
# Pulling these during the animation means compose-up is faster.
_PUBLIC_IMAGES = [
    ("postgres:17-alpine", "postgres"),
    ("skaiworldwide/agensgraph:v2.16.0-alpine3.22", "graph DB (AgensGraph)"),
    ("skaiworldwide/agviewer:latest", "graph DB viewer"),
]


def _check_docker() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, "docker daemon not running"
    except FileNotFoundError:
        return False, "docker not found — install Docker Desktop"
    except Exception as e:
        return False, str(e)


def _check_compose() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["docker", "compose", "version", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, "docker compose v2 not available"
    except Exception as e:
        return False, str(e)


def _check_ports(ports: list[int]) -> list[int]:
    """Return list of ports that are already in use."""
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("localhost", port)) == 0:
                busy.append(port)
    return busy


def _check_disk(min_mb: int = 500) -> tuple[bool, str]:
    usage = shutil.disk_usage(Path.home())
    free_mb = usage.free // (1024 * 1024)
    return free_mb >= min_mb, f"{free_mb:,} MB free"


# ── Interactive prompts ──────────────────────────────────────────────────────


def _ask(prompt: str, default: str = "") -> str:
    """Read a line; raise KeyboardInterrupt on Ctrl+C/Ctrl+D/q/Q/Escape."""
    try:
        raw = input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt
    stripped = raw.strip()
    if stripped.lower() in ("q", "quit", "exit") or stripped.startswith("\x1b"):
        raise KeyboardInterrupt
    return stripped or default


def _prompt_llm() -> dict[str, str]:
    from beaupy import select

    # Offer to reuse existing LLM config if present
    env_path = Path.home() / ".mycelium" / ".env"
    if env_path.exists():
        from dotenv import dotenv_values

        existing = dotenv_values(env_path)
        model = existing.get("LLM_MODEL", "")
        key = existing.get("LLM_API_KEY", "")
        if model:
            print()
            keep = _ask(
                f"  LLM is currently \x1b[1m{model}\x1b[0m — keep existing config? [Y/n] ",
                default="y",
            )
            if keep.lower() in ("y", "yes", ""):
                result: dict[str, str] = {"LLM_MODEL": model}
                if key:
                    result["LLM_API_KEY"] = key
                base = existing.get("LLM_BASE_URL", "")
                if base:
                    result["LLM_BASE_URL"] = base
                print(f"  \x1b[32m✓\x1b[0m Keeping {model}")
                return result

    print()
    print("  \x1b[1;36m? LLM for CognitiveEngine\x1b[0m")
    print()

    providers = [
        "Anthropic  — claude-sonnet-4-6, claude-opus-4-6",
        "OpenAI     — gpt-4o, gpt-4.1",
        "OpenRouter  — multi-provider gateway",
        "Ollama     — local models (llama3.3, mistral, etc.)",
        "Custom     — any OpenAI-compatible endpoint",
        "Skip       — no LLM (stub mode)",
    ]

    choice = select(providers, cursor="  ▸ ", cursor_style="cyan")
    if choice is None:
        raise KeyboardInterrupt

    if choice.startswith("Anthropic"):
        models = [
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-haiku-4-5",
        ]
        model = select(models, cursor="  ▸ ", cursor_style="cyan")
        key = _ask("  \x1b[2mAPI key (sk-ant-...):\x1b[0m ")
        print(f"  \x1b[32m✓\x1b[0m {model}")
        return {"LLM_MODEL": model, "LLM_API_KEY": key}

    if choice.startswith("OpenAI"):
        models = [
            "openai/gpt-4o",
            "openai/gpt-4.1",
            "openai/gpt-4o-mini",
            "openai/o3",
        ]
        model = select(models, cursor="  ▸ ", cursor_style="cyan")
        key = _ask("  \x1b[2mAPI key (sk-...):\x1b[0m ")
        print(f"  \x1b[32m✓\x1b[0m {model}")
        return {"LLM_MODEL": model, "LLM_API_KEY": key}

    if choice.startswith("OpenRouter"):
        model = _ask(
            "  \x1b[2mModel (e.g. anthropic/claude-sonnet-4-6):\x1b[0m ",
            default="anthropic/claude-sonnet-4-6",
        )
        model = f"openrouter/{model}"
        key = _ask("  \x1b[2mOpenRouter API key:\x1b[0m ")
        print(f"  \x1b[32m✓\x1b[0m {model}")
        return {"LLM_MODEL": model, "LLM_API_KEY": key}

    if choice.startswith("Ollama"):
        models = [
            "ollama/llama3.3",
            "ollama/mistral",
            "ollama/qwen2.5",
            "ollama/deepseek-r1",
        ]
        model = select(models, cursor="  ▸ ", cursor_style="cyan")
        print(f"  \x1b[32m✓\x1b[0m {model} at localhost:11434")
        return {"LLM_MODEL": model, "LLM_BASE_URL": "http://host.docker.internal:11434"}

    if choice.startswith("Custom"):
        model = _ask("  \x1b[2mModel (litellm format, e.g. openai/my-model):\x1b[0m ")
        base_url = _ask("  \x1b[2mBase URL:\x1b[0m ")
        key = _ask("  \x1b[2mAPI key (or empty):\x1b[0m ")
        print(f"  \x1b[32m✓\x1b[0m {model} at {base_url}")
        result = {"LLM_MODEL": model}
        if base_url:
            result["LLM_BASE_URL"] = base_url
        if key:
            result["LLM_API_KEY"] = key
        return result

    # Skip
    print("  \x1b[33m~\x1b[0m Skipped — synthesis will use stub responses")
    return {}


# ── Env file ─────────────────────────────────────────────────────────────────


def _write_env_file(env_path: Path, llm_config: dict[str, str]) -> None:
    import importlib.resources

    # On re-install, preserve existing .env and only update/append changed keys.
    # Remove LLM_BASE_URL when the new config doesn't include it — avoids
    # leaving a stale empty value that breaks litellm (see #97).
    if env_path.exists():
        _patch_env_vars(env_path, llm_config)
        if "LLM_BASE_URL" not in llm_config:
            _remove_env_var(env_path, "LLM_BASE_URL")
        return

    defaults_ref = importlib.resources.files("mycelium.docker") / "env.defaults"
    defaults_text = defaults_ref.read_text(encoding="utf-8")

    lines = []
    for line in defaults_text.splitlines():
        key = line.split("=")[0].strip() if "=" in line else None
        if key and key in llm_config:
            lines.append(f"{key}={llm_config[key]}")
        else:
            lines.append(line)

    # Append any new keys from llm_config not already in defaults
    existing_keys = {ln.split("=")[0].strip() for ln in lines if "=" in ln}
    for key, value in llm_config.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _restart_backend(
    compose_path: Path,
    env_path: Path,
    profiles: list[str] | None = None,
    api_url: str = "http://localhost:8000",
) -> None:
    """Restart only the backend container and wait for it to become healthy."""
    args = [
        "docker",
        "compose",
        "-p",
        "mycelium",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_path),
    ]
    for p in profiles or []:
        args += ["--profile", p]
    args += ["up", "--no-build", "--force-recreate", "-d", "mycelium-backend"]
    subprocess.run(args, capture_output=True)
    _wait_for_health([f"{api_url}/health"], timeout=60)


def _patch_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    """Update or append specific key=value entries in an existing .env file."""
    if not env_path.exists():
        return
    text = env_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    remaining = dict(updates)
    new_lines = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=")[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    # Append any keys not yet present
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _remove_env_var(env_path: Path, key: str) -> None:
    """Remove a key from an existing .env file (no-op if absent)."""
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = [
        ln
        for ln in lines
        if not (
            "=" in ln
            and not ln.lstrip().startswith("#")
            and ln.split("=")[0].strip() == key
        )
    ]
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Docker compose ────────────────────────────────────────────────────────────


def _get_compose_path() -> Path:
    """
    Resolve the canonical compose file path.

    For editable installs (dev), walk up from the package source to find the
    repo's services/docker-compose.yml — this keeps build context relative
    paths (../cfn/..., ../fastapi-backend) correct.

    For non-editable installs, extract the bundled compose to ~/.mycelium/docker/.
    Build contexts won't work in that case, but pull-only services will.
    """
    import importlib.resources
    import os

    if env_path := os.getenv("MYCELIUM_COMPOSE_FILE"):
        return Path(env_path)

    # Check cwd — covers running `mycelium install` from the repo root
    cwd_candidate = Path.cwd() / "services" / "docker-compose.yml"
    if cwd_candidate.exists():
        return cwd_candidate

    # Walk up from package location to find services/docker-compose.yml
    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "services" / "docker-compose.yml"
            if candidate.exists():
                return candidate
    except Exception:
        pass

    # Fallback: extract bundled compose (relative build paths will be wrong)
    compose_ref = importlib.resources.files("mycelium.docker") / "compose.yml"
    dest = Path.home() / ".mycelium" / "docker" / "compose.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(compose_ref.read_bytes())

    # Copy bundled initdb/ scripts so Postgres entrypoint creates CFN databases
    # on first volume init (compose mounts ./initdb as /docker-entrypoint-initdb.d).
    try:
        initdb_dest = dest.parent / "initdb"
        initdb_dest.mkdir(exist_ok=True)
        initdb_pkg = importlib.resources.files("mycelium.docker") / "initdb"
        for item in initdb_pkg.iterdir():
            if item.name.startswith("_"):
                continue
            script_path = initdb_dest / item.name
            script_path.write_bytes(item.read_bytes())
            script_path.chmod(0o755)
    except Exception:
        pass  # non-fatal: _ensure_cfn_databases() handles it at runtime

    return dest


def _image_exists(image: str) -> bool:
    """Return True if a Docker image is already present locally."""
    r = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    return r.returncode == 0


_KNOWN_CONTAINERS = [
    "mycelium-db",
    "mycelium-backend",
    "ioc-cfn-db",
    "ioc-cfn-mgmt-plane-svc",
]


def _remove_orphan_containers() -> None:
    """Remove containers with known Mycelium names that aren't tracked
    by the current compose project (leftovers from earlier installs).

    Handles running, stopped, and dead containers alike so that
    ``compose up --force-recreate`` never hits a name conflict.
    """
    for name in _KNOWN_CONTAINERS:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _compose_up(
    compose_path: Path, env_path: Path, profiles: list[str] | None = None
) -> tuple[bool, bool]:
    """Bring the stack up.  Returns (success, needs_build)."""
    # Build context exists when running from a repo checkout. Packaged installs
    # extract compose to ~/.mycelium/docker/ where ../fastapi-backend is absent —
    # those installs pull pre-built GHCR images instead.
    build_context = compose_path.parent.parent / "fastapi-backend"
    can_build = build_context.exists()
    needs_build = can_build and not _image_exists("ghcr.io/mycelium-io/mycelium-backend:latest")

    _remove_orphan_containers()

    args = [
        "docker",
        "compose",
        "-p",
        "mycelium",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_path),
    ]
    for profile in profiles or []:
        args += ["--profile", profile]
    up_flags = ["up", "--pull", "always", "--force-recreate", "-d"]
    if can_build:
        up_flags.append("--build")
    else:
        up_flags.append("--no-build")
    args += up_flags

    print()
    typer.secho("  Running: " + " ".join(args[2:]), dim=True)
    if needs_build:
        typer.secho("  (first run — building backend image, this may take a few minutes)", dim=True)
    print()

    result = subprocess.run(args, text=True)
    return result.returncode == 0, needs_build


def _run_migrations() -> None:
    """Run alembic migrations via the migrate command."""
    from mycelium.commands.instance import _get_backend_dir, _get_env_path

    backend_dir = _get_backend_dir()
    if not (backend_dir / "alembic.ini").exists():
        typer.echo("  ⚠  alembic.ini not found — skipping migrations")
        return

    import os

    env = {**os.environ}
    env_path = _get_env_path()
    if env_path and env_path.exists():
        from dotenv import dotenv_values

        env.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})

    backend_env = backend_dir / ".env"
    if backend_env.exists():
        from dotenv import dotenv_values

        env.update({k: v for k, v in dotenv_values(backend_env).items() if v is not None})

    if "DATABASE_URL" not in env:
        typer.echo("  ⚠  DATABASE_URL not set — skipping migrations")
        return

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        typer.secho("  ✓ Database migrations applied", fg=typer.colors.GREEN)
    else:
        typer.secho("  ⚠  Migration failed (non-fatal)", fg=typer.colors.YELLOW)


def _ensure_cfn_databases(db_container: str = "mycelium-db") -> None:
    """Create cfn_mgmt and cfn_cp databases if they don't exist.

    initdb scripts only run on first postgres init, so on upgrades with an
    existing volume the CFN databases won't be present. This is idempotent.
    """
    for db in ("cfn_mgmt", "cfn_cp"):
        # Check if DB exists, create if not. Can't use \gexec with psql -c.
        check = subprocess.run(
            [
                "docker",
                "exec",
                db_container,
                "psql",
                "-U",
                "postgres",
                "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname = '{db}'",
            ],
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            typer.secho(
                f"  ✗ Could not check for database '{db}': {check.stderr.strip()}",
                fg=typer.colors.RED,
            )
            continue
        if check.stdout.strip() == "1":
            typer.echo(f"  ~ Database '{db}' already exists")
            continue
        create = subprocess.run(
            [
                "docker",
                "exec",
                db_container,
                "psql",
                "-U",
                "postgres",
                "-c",
                f"CREATE DATABASE {db}",
            ],
            capture_output=True,
            text=True,
        )
        if create.returncode != 0:
            typer.secho(
                f"  ✗ Failed to create database '{db}': {create.stderr.strip()}",
                fg=typer.colors.RED,
            )
        else:
            typer.echo(f"  ✓ Created database '{db}'")


def _wait_for_db_container(
    compose_path: Path,
    env_path: Path,
    db_service: str = "mycelium-db",
    timeout: int = 60,
) -> bool:
    """Wait until the DB container reports healthy via docker compose ps."""
    import time

    deadline = time.time() + timeout
    args = [
        "docker",
        "compose",
        "-p",
        "mycelium",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_path),
        "ps",
        "--format",
        "json",
        db_service,
    ]
    while time.time() < deadline:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0 and "healthy" in result.stdout:
            return True
        time.sleep(2)
    return False


def _compose_up_services(
    compose_path: Path,
    env_path: Path,
    profiles: list[str] | None = None,
    services: list[str] | None = None,
) -> bool:
    """Bring specific services (or all) up in detached mode. Returns success bool."""
    args = [
        "docker",
        "compose",
        "-p",
        "mycelium",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_path),
    ]
    for profile in profiles or []:
        args += ["--profile", profile]
    args += ["up", "-d"]
    if services:
        args += services
    result = subprocess.run(args, text=True)
    return result.returncode == 0


def _wait_for_health(urls: list[str], timeout: int = 120) -> bool:
    try:
        import httpx
    except ImportError:
        return True  # skip if httpx not available

    deadline = time.time() + timeout
    pending = list(urls)

    sys.stdout.write("  Waiting for services to become healthy")
    sys.stdout.flush()

    while pending and time.time() < deadline:
        time.sleep(3)
        sys.stdout.write(".")
        sys.stdout.flush()
        still_pending = []
        for url in pending:
            try:
                r = httpx.get(url, timeout=3)
                if r.status_code < 500:
                    continue
            except Exception:
                pass
            still_pending.append(url)
        pending = still_pending

    print()
    if pending:
        typer.secho(f"  ⚠  Timed out waiting for: {', '.join(pending)}", fg=typer.colors.YELLOW)
        return False
    return True


# ── Backend provisioning ──────────────────────────────────────────────────────


def _get_cfn_workspace_id(cfn_mgmt_url: str) -> str | None:
    """Fetch the first workspace ID from the CFN mgmt plane."""
    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{cfn_mgmt_url}/api/workspaces", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        workspaces = data.get("workspaces", [])
        return workspaces[0]["id"] if workspaces else None
    except Exception:
        return None


def _provision_backend(api_url: str, workspace_name: str = "default") -> tuple[str, str]:
    """
    Create a default workspace and MAS in the backend.
    Returns (workspace_id, mas_id).
    Idempotent — fetches existing workspace/MAS on 409/400 conflict.
    Raises RuntimeError if the backend is unreachable or returns an error.
    """
    import json
    import urllib.error
    import urllib.request

    def _get(path: str) -> list:
        req = urllib.request.Request(
            f"{api_url}{path}", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def _post(path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{api_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    try:
        ws = _post("/api/workspaces", {"name": workspace_name})
    except urllib.error.HTTPError as e:
        if e.code in (400, 409):
            workspaces = _get("/api/workspaces")
            ws = next((w for w in workspaces if w.get("name") == workspace_name), workspaces[0])
        else:
            raise
    workspace_id: str = ws["id"]

    try:
        mas = _post(f"/api/workspaces/{workspace_id}/mas", {"name": "default"})
    except urllib.error.HTTPError as e:
        if e.code in (400, 409):
            mas_list = _get(f"/api/workspaces/{workspace_id}/mas")
            mas = mas_list[0]
        else:
            raise
    mas_id: str = mas["id"]

    return workspace_id, mas_id


# ── Config write ─────────────────────────────────────────────────────────────


def _write_mycelium_config(
    api_url: str,
    workspace_id: str,
    mas_id: str,
    llm_config: dict[str, str] | None = None,
    custom_ports: dict[str, int] | None = None,
    ioc_enabled: bool = False,
) -> None:
    from mycelium.config import LLMConfig, MyceliumConfig, RuntimeConfig, ServerConfig
    from mycelium.docker_utils import write_env_file

    config_path = MyceliumConfig.get_global_config_path()
    try:
        config = MyceliumConfig.load(config_path) if config_path.exists() else MyceliumConfig()
    except Exception:
        config = MyceliumConfig()

    config.server = ServerConfig(
        api_url=api_url,
        workspace_id=workspace_id,
        mas_id=mas_id,
    )

    # Persist LLM settings into [llm] section
    if llm_config:
        config.llm = LLMConfig(
            model=llm_config.get("LLM_MODEL") or config.llm.model,
            api_key=llm_config.get("LLM_API_KEY") or config.llm.api_key,
            base_url=llm_config.get("LLM_BASE_URL") or config.llm.base_url,
        )

    # Persist runtime settings into [runtime] section
    runtime_kwargs: dict[str, object] = {
        "data_dir": str(Path.home() / ".mycelium"),
    }
    if custom_ports:
        runtime_kwargs["db_port"] = custom_ports.get("db", 5432)
        runtime_kwargs["backend_port"] = custom_ports.get("backend", 8000)
    if ioc_enabled:
        runtime_kwargs["cfn_mgmt_url"] = "http://ioc-cfn-mgmt-plane-svc:9000"
        runtime_kwargs["cognition_fabric_node_url"] = "http://ioc-cognition-fabric-node-svc:9002"
    if workspace_id:
        runtime_kwargs["workspace_id"] = workspace_id
    config.runtime = RuntimeConfig(**runtime_kwargs)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config.save(config_path)

    # Derive .env from the canonical config.toml
    env_path = write_env_file(config)
    typer.echo(f"  ✓ Regenerated {env_path} from config.toml")


# ── Animation helper ──────────────────────────────────────────────────────────


# ── Main ─────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium install [--yes] [--non-interactive] [--force]",
    desc="Interactive installer — Docker check, LLM config, <code>docker compose up</code>, provision workspace.",
    group="setup",
)
def install(
    ctx: typer.Context,
    ascii_: bool = typer.Option(False, "--ascii", help="Use ASCII rendering"),
    blocks: bool = typer.Option(False, "--blocks", help="Use unicode block rendering"),
    theme: str = typer.Option(
        "cyan", "--color", help="Color theme (cyan|amber|magenta|green|white)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmations"),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", "-n", help="Skip prompts and animation (use --llm-model etc.)"
    ),
    llm_model: str = typer.Option(
        "", "--llm-model", help="LLM model in litellm format (non-interactive)"
    ),
    llm_base_url: str = typer.Option("", "--llm-base-url", help="LLM base URL (non-interactive)"),
    llm_api_key: str = typer.Option("", "--llm-api-key", help="LLM API key (non-interactive)"),
    db_port: int = typer.Option(
        0, "--db-port", help="Host port for Postgres (0 = auto-detect, default 5432)"
    ),
    backend_port: int = typer.Option(
        0, "--backend-port", help="Host port for backend API (0 = auto-detect, default 8000)"
    ),
    ioc: bool = typer.Option(True, "--ioc/--no-ioc", help="Enable IoC CFN stack (default: on)"),
    force: bool = typer.Option(
        False, "--force", help="Force full reinstall even if already installed"
    ),
) -> None:
    """
    Install a Mycelium instance.

    By default this runs interactively — it plays an intro animation, prompts
    for LLM configuration, and walks you through bringing up all services via
    Docker Compose.

    If Mycelium is already installed, this command will suggest using
    ``mycelium upgrade``, ``mycelium pull``, or ``mycelium doctor`` instead.
    Pass --force to reinstall from scratch.

    \b
    NON-INTERACTIVE MODE
    If you are running in a script, CI pipeline, or any non-TTY environment,
    pass -n / --non-interactive and supply config via flags:

      mycelium install -n \\
        --llm-model anthropic/claude-sonnet-4-6 \\
        --llm-api-key sk-ant-... \\
        [--no-ioc]

    \b
    FLAGS (non-interactive)
      --llm-model     LLM in litellm format, e.g. anthropic/claude-sonnet-4-6
                      or openai/gpt-4o or ollama/llama3
      --llm-base-url  Custom base URL (required for ollama / local models)
      --llm-api-key   API key for the chosen LLM provider
      --db-port       Host port for Postgres (default: 5432, auto-increments on conflict)
      --backend-port  Host port for backend API (default: 8000, auto-increments on conflict)
      --no-ioc        Skip the IoC CFN management-plane stack (default: included)
      --force         Force full reinstall (ignore existing configuration)
    """
    import sys

    try:
        # ── Detect existing install and redirect ──────────────────────────
        _existing_env = Path.home() / ".mycelium" / ".env"
        _existing_cfg = Path.home() / ".mycelium" / "config.toml"
        if not force and _existing_env.exists() and _existing_cfg.exists():
            typer.secho("\n  Mycelium is already installed.", fg=typer.colors.CYAN, bold=True)
            typer.echo("")
            typer.echo("  To update:")
            typer.echo("    mycelium upgrade    — fetch latest CLI")
            typer.echo("    mycelium pull       — pull latest containers and restart")
            typer.echo("    mycelium doctor     — diagnose and fix issues")
            typer.echo("")
            typer.echo("  Pass --force to reinstall from scratch.")
            raise typer.Exit(0)

        if non_interactive:
            # ── Non-interactive path ───────────────────────────────────────
            docker_ok, docker_ver = _check_docker()
            compose_ok, compose_ver = _check_compose()
            if not docker_ok:
                typer.secho(f"\n  ✗ Docker: {docker_ver}", fg=typer.colors.RED)
                raise typer.Exit(1) from None
            if not compose_ok:
                typer.secho(f"\n  ✗ Docker Compose: {compose_ver}", fg=typer.colors.RED)
                raise typer.Exit(1) from None

            llm_config: dict[str, str] = {}
            if llm_model:
                llm_config["LLM_MODEL"] = llm_model
            if llm_base_url:
                llm_config["LLM_BASE_URL"] = llm_base_url
            if llm_api_key:
                llm_config["LLM_API_KEY"] = llm_api_key

            compose_profiles: list[str] = []
            if ioc:
                llm_config["CFN_MGMT_URL"] = "http://ioc-cfn-mgmt-plane-svc:9000"
                llm_config["COGNITION_FABRIC_NODE_URL"] = (
                    "http://ioc-cognition-fabric-node-svc:9002"
                )
                compose_profiles.append("cfn")

            # Resolve ports — use explicit flags, or auto-detect conflicts
            default_ports = {"db": db_port or 5432, "backend": backend_port or 8000}
            if not db_port or not backend_port:
                busy = _check_ports(list(default_ports.values()))
                for label, port in default_ports.items():
                    if port in busy:
                        new_port = port + 1
                        while new_port in busy or new_port in default_ports.values():
                            new_port += 1
                        typer.secho(
                            f"  ⚠  Port {port} ({label}) in use — using {new_port}",
                            fg=typer.colors.YELLOW,
                        )
                        default_ports[label] = new_port
            custom_ports = default_ports
            llm_config["MYCELIUM_DB_PORT"] = str(custom_ports["db"])
            llm_config["MYCELIUM_BACKEND_PORT"] = str(custom_ports["backend"])
            llm_config["MYCELIUM_DATA_DIR"] = str(Path.home() / ".mycelium")

            typer.secho(
                "  ⚠  Experimental software — please report issues at github.com/mycelium-io/mycelium/issues",
                fg=typer.colors.YELLOW,
            )
            typer.secho("  ── Starting services ──────────────────────────────────", bold=True)
            env_dir = Path.home() / ".mycelium"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_path = env_dir / ".env"
            _write_env_file(env_path, llm_config)
            typer.echo(f"  ✓ Wrote {env_path}")

            compose_path = _get_compose_path()
            typer.echo(f"  ✓ Compose file → {compose_path}")

            if ioc:
                # Phase 1: bring up DB alone so we can provision CFN databases
                # before the CFN services start and try to connect.
                if not _compose_up_services(compose_path, env_path, services=["mycelium-db"]):
                    typer.secho("\n  ✗ docker compose up failed (db)", fg=typer.colors.RED)
                    raise typer.Exit(1) from None
                if not _wait_for_db_container(compose_path, env_path):
                    typer.secho("\n  ✗ mycelium-db failed to become healthy", fg=typer.colors.RED)
                    raise typer.Exit(1) from None
                _ensure_cfn_databases()

            # Phase 2 (or only phase for non-ioc): bring up everything
            ok, needs_build = _compose_up(compose_path, env_path, profiles=compose_profiles)
            if not ok:
                typer.secho("\n  ✗ docker compose up failed", fg=typer.colors.RED)
                raise typer.Exit(1) from None

            api_url = f"http://localhost:{custom_ports['backend']}"
            health_timeout = 300 if needs_build else 120
            _wait_for_health([f"{api_url}/health"], timeout=health_timeout)

            if ioc:
                # Source WORKSPACE_ID from the CFN mgmt plane (the source of truth)
                workspace_id = _get_cfn_workspace_id("http://localhost:9000") or ""
                mas_id = ""
                if workspace_id:
                    typer.echo(f"  ✓ Workspace  {workspace_id}")
                else:
                    typer.secho(
                        "  ⚠  Could not fetch workspace from CFN mgmt plane", fg=typer.colors.YELLOW
                    )
            else:
                try:
                    workspace_id, mas_id = _provision_backend(api_url)
                    typer.echo(f"  ✓ Workspace  {workspace_id}")
                    typer.echo(f"  ✓ MAS        {mas_id}")
                except Exception as exc:
                    typer.secho(f"  ⚠  Could not provision backend: {exc}", fg=typer.colors.YELLOW)
                    workspace_id, mas_id = "", ""

            # Persist WORKSPACE_ID into .env and restart backend so it picks it up
            if workspace_id:
                ws_patch: dict[str, str] = {"WORKSPACE_ID": workspace_id}
                if ioc:
                    ws_patch["CFN_MGMT_URL"] = "http://ioc-cfn-mgmt-plane-svc:9000"
                    ws_patch["COGNITION_FABRIC_NODE_URL"] = (
                        "http://ioc-cognition-fabric-node-svc:9002"
                    )
                _patch_env_vars(env_path, ws_patch)
                _restart_backend(compose_path, env_path, compose_profiles, api_url)

            _run_migrations()
            _write_mycelium_config(
                api_url,
                workspace_id,
                mas_id,
                llm_config=llm_config,
                custom_ports=custom_ports,
                ioc_enabled=ioc,
            )
            typer.secho("  ✓ Done.", fg=typer.colors.GREEN, bold=True)
            return

        if not sys.stdin.isatty():
            typer.secho(
                "\n  ✗ Non-interactive terminal detected — interactive install requires a TTY.\n",
                fg=typer.colors.RED,
            )
            import click

            click_ctx = click.get_current_context()
            typer.echo(click_ctx.get_help())
            raise typer.Exit(1) from None

        from mycelium.animations import run_animation_live

        mode = "ascii" if ascii_ else "blocks" if blocks else "braille"

        # ── Phase 1: System checks + public image pulls (animation runs live) ─
        docker_ok, docker_ver = _check_docker()
        compose_ok, compose_ver = _check_compose()
        disk_ok, disk_info = _check_disk()

        # Fail fast — no point running the animation if Docker isn't available
        if not docker_ok:
            typer.secho(f"\n  ✗ Docker: {docker_ver}", fg=typer.colors.RED)
            typer.echo("  Install Docker Desktop: https://docs.docker.com/get-docker/")
            raise typer.Exit(1) from None
        if not compose_ok:
            typer.secho(f"\n  ✗ Docker Compose: {compose_ver}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

        ok = "\x1b[32m✓\x1b[0m"
        err = "\x1b[31m✗\x1b[0m"
        spin = "\x1b[2m⟳\x1b[0m"

        header_lines = [
            "",
            "  \x1b[1mInstalling Mycelium...\x1b[0m",
            "",
            "  \x1b[33m⚠  Experimental software — please report issues at github.com/mycelium-io/mycelium/issues\x1b[0m",
            "",
            f"    {ok if docker_ok else err} docker {docker_ver}",
            f"    {ok if compose_ok else err} docker compose {compose_ver}",
            f"    {ok if disk_ok else err} disk {disk_info}",
            "",
            "  \x1b[1mPulling base images\x1b[0m",
            "",
        ]
        # One slot per image — updated in-place by the pull thread.
        image_lines: list[str] = [f"    {spin} {label}" for _, label in _PUBLIC_IMAGES]
        # Sliding window of recent pull output lines.
        log_window: list[str] = []

        done = threading.Event()

        # Honor DOCKER_DEFAULT_PLATFORM from the env defaults so pre-pulled
        # images match the platform compose will use.
        import importlib.resources as _ir
        import os as _os

        _pull_platform = _os.getenv("DOCKER_DEFAULT_PLATFORM", "")
        if not _pull_platform:
            try:
                _defaults = (_ir.files("mycelium.docker") / "env.defaults").read_text()
                for _ln in _defaults.splitlines():
                    if _ln.startswith("DOCKER_DEFAULT_PLATFORM="):
                        _pull_platform = _ln.split("=", 1)[1].strip()
                        break
            except Exception:
                pass
        # Services that need amd64 (AgensGraph, CFN node) pin platform in compose.
        # For pre-pulling public images that are amd64-only, force the platform.
        if not _pull_platform:
            try:
                import platform as _pf

                if _pf.machine() == "arm64":
                    _pull_platform = "linux/amd64"
            except Exception:
                pass

        def _do_pulls() -> None:
            nonlocal log_window
            try:
                for i, (image, label) in enumerate(_PUBLIC_IMAGES):
                    image_lines[i] = f"    {spin} {label}  \x1b[2mpulling…\x1b[0m"
                    log_window = []
                    cmd = ["docker", "pull"]
                    if _pull_platform:
                        cmd += ["--platform", _pull_platform]
                    cmd.append(image)
                    try:
                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        assert proc.stdout
                        for raw in proc.stdout:
                            text = raw.strip()
                            if text:
                                log_window = (log_window + [f"      \x1b[2m> {text}\x1b[0m"])[
                                    -LOG_WINDOW:
                                ]
                        proc.wait()
                        if proc.returncode == 0:
                            image_lines[i] = f"    {ok} {label}"
                        else:
                            image_lines[i] = (
                                f"    {err} {label}  \x1b[2m(will retry during compose up)\x1b[0m"
                            )
                    except Exception:
                        image_lines[i] = (
                            f"    {err} {label}  \x1b[2m(skipped — docker not available)\x1b[0m"
                        )
                    log_window = []
            finally:
                done.set()

        pull_thread = threading.Thread(target=_do_pulls, daemon=True)
        pull_thread.start()

        def _get_lines() -> list[str]:
            return header_lines + image_lines + ([""] + log_window if log_window else [])

        run_animation_live(
            get_lines=_get_lines,
            done=done,
            height=18,
            theme=theme,
            fill=0.15,
            mode=mode,
            rain=True,
            wipe=True,
            linger=0.4,
        )
        pull_thread.join()

        if not docker_ok:
            typer.secho(f"\n  ✗ Docker: {docker_ver}", fg=typer.colors.RED)
            typer.echo("  Install Docker Desktop: https://docs.docker.com/get-docker/")
            raise typer.Exit(1) from None

        if not compose_ok:
            typer.secho(f"\n  ✗ Docker Compose: {compose_ver}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

        # ── Phase 2: Interactive prompts ──────────────────────────────────
        llm_config = _prompt_llm()

        ioc_enabled = True  # IoC is always enabled; use --no-ioc in non-interactive mode to skip
        compose_profiles: list[str] = []
        if ioc_enabled:
            llm_config["CFN_MGMT_URL"] = "http://ioc-cfn-mgmt-plane-svc:9000"
            llm_config["COGNITION_FABRIC_NODE_URL"] = "http://ioc-cognition-fabric-node-svc:9002"
            compose_profiles.append("cfn")

        # Port check — allow user to pick alternatives
        default_ports = {"db": 5432, "backend": 8000}
        ports_to_check = list(default_ports.values())
        busy_ports = _check_ports(ports_to_check)
        custom_ports = dict(default_ports)

        if busy_ports:
            typer.secho(f"\n  ⚠  Ports already in use: {busy_ports}", fg=typer.colors.YELLOW)
            print()
            for label, default in default_ports.items():
                if default in busy_ports:
                    new_port = _ask(f"  \x1b[2m{label} port (default {default} is busy):\x1b[0m ")
                    if new_port.isdigit():
                        custom_ports[label] = int(new_port)
                    else:
                        typer.echo(f"    Using default {default} anyway")

            # Update llm_config with custom ports for env file
            llm_config["MYCELIUM_DB_PORT"] = str(custom_ports["db"])
            llm_config["MYCELIUM_BACKEND_PORT"] = str(custom_ports["backend"])

        # Set MYCELIUM_DATA_DIR so compose mounts the host's .mycelium/ into the container
        llm_config["MYCELIUM_DATA_DIR"] = str(Path.home() / ".mycelium")

        # ── Phase 3: Write env, bring up services ─────────────────────────
        print()
        typer.secho("  ── Starting services ──────────────────────────────────", bold=True)

        env_dir = Path.home() / ".mycelium"
        env_dir.mkdir(parents=True, exist_ok=True)
        env_path = env_dir / ".env"

        # Merge LLM + CFN keys into .env (create or patch — never skip merge when .env exists).
        if not env_path.exists():
            typer.echo(f"  ✓ Creating {env_path}")
        else:
            typer.echo(f"  ~ Updating existing {env_path}")
        _write_env_file(env_path, llm_config)
        typer.echo(f"  ✓ Wrote {env_path}")

        compose_path = _get_compose_path()
        typer.echo(f"  ✓ Compose file → {compose_path}")

        if ioc_enabled:
            # Phase 1: bring up DB alone so we can provision CFN databases
            # before the CFN services start and try to connect.
            if not _compose_up_services(compose_path, env_path, services=["mycelium-db"]):
                typer.secho("\n  ✗ docker compose up failed (db)", fg=typer.colors.RED)
                raise typer.Exit(1) from None
            if not _wait_for_db_container(compose_path, env_path):
                typer.secho("\n  ✗ mycelium-db failed to become healthy", fg=typer.colors.RED)
                raise typer.Exit(1) from None
            _ensure_cfn_databases()

        # Phase 2 (or only phase for non-ioc): bring up everything
        ok, needs_build = _compose_up(compose_path, env_path, profiles=compose_profiles)
        if not ok:
            typer.secho("\n  ✗ docker compose up failed", fg=typer.colors.RED)
            raise typer.Exit(1) from None

        # ── Phase 4: Health checks ─────────────────────────────────────────
        # Allow extra time on first run when the backend image is being built.
        api_url = f"http://localhost:{custom_ports['backend']}"
        health_timeout = 300 if needs_build else 120
        print()
        _wait_for_health([f"{api_url}/health"], timeout=health_timeout)

        # ── Phase 5: Provision workspace + MAS ────────────────────────────
        print()
        typer.echo("  ── Provisioning backend ────────────────────────────────")
        if ioc_enabled:
            # Source WORKSPACE_ID from the CFN mgmt plane (the source of truth)
            workspace_id = _get_cfn_workspace_id("http://localhost:9000") or ""
            mas_id = ""
            if workspace_id:
                typer.echo(f"  ✓ Workspace  {workspace_id}")
            else:
                typer.secho(
                    "  ⚠  Could not fetch workspace from CFN mgmt plane", fg=typer.colors.YELLOW
                )
        else:
            try:
                workspace_id, mas_id = _provision_backend(api_url)
                typer.echo(f"  ✓ Workspace created  {workspace_id}")
                typer.echo(f"  ✓ MAS created        {mas_id}")
            except Exception as exc:
                typer.secho(f"  ⚠  Could not provision backend: {exc}", fg=typer.colors.YELLOW)
                typer.echo("     Run manually: mycelium install --provision")
                workspace_id, mas_id = "", ""

        # ── Phase 6: Migrate DB + write config ────────────────────────────
        # Persist WORKSPACE_ID into .env and restart backend so it picks it up
        if workspace_id:
            ws_patch: dict[str, str] = {"WORKSPACE_ID": workspace_id}
            if ioc_enabled:
                ws_patch["CFN_MGMT_URL"] = "http://ioc-cfn-mgmt-plane-svc:9000"
                ws_patch["COGNITION_FABRIC_NODE_URL"] = "http://ioc-cognition-fabric-node-svc:9002"
            _patch_env_vars(env_path, ws_patch)
            _restart_backend(compose_path, env_path, compose_profiles, api_url)

        _run_migrations()
        _write_mycelium_config(
            api_url,
            workspace_id,
            mas_id,
            llm_config=llm_config,
            custom_ports=custom_ports,
            ioc_enabled=ioc_enabled,
        )
        typer.secho("  ✓ Config written to ~/.mycelium/config.toml", fg=typer.colors.GREEN)

        # ── Done ───────────────────────────────────────────────────────────
        print()
        typer.secho("  Mycelium is ready.", fg=typer.colors.GREEN, bold=True)
        print()
        typer.echo("  Services:")
        typer.echo(f"    mycelium-backend  → {api_url}")
        typer.echo(f"    mycelium-db       → localhost:{custom_ports['db']}")
        typer.echo("    graph-db-viewer   → http://localhost:5457  (dev profile only)")
        print()
        typer.echo("  Next steps:")
        typer.echo("    mycelium adapter add openclaw   # wire openclaw agents")
        typer.echo("    mycelium room create <name>     # create your first room")
        print()

    except KeyboardInterrupt:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()
        typer.secho("  Cancelled.", fg=typer.colors.YELLOW)
        raise typer.Exit(0) from None
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── Upgrade command ──────────────────────────────────────────────────────────

_GITHUB_REPO = "mycelium-io/mycelium"


def _get_latest_release_tag() -> str | None:
    """Follow GitHub /releases/latest redirect to get the version tag."""
    import urllib.request

    url = f"https://github.com/{_GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            # Redirected URL ends with /tag/v0.2.0
            final_url = resp.url
        tag = final_url.rsplit("/", 1)[-1]
        return tag if tag.startswith("v") else None
    except Exception:
        return None


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse a version tag like 'v0.2.0' or '0.2.0' into a comparable tuple."""
    clean = tag.lstrip("v")
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


@doc_ref(
    usage="mycelium upgrade [--check]",
    desc="Upgrade the Mycelium CLI to the latest release.",
    group="setup",
)
def upgrade(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Just check for updates, don't install"),
) -> None:
    """
    Upgrade the Mycelium CLI to the latest release.

    Fetches the latest version from GitHub releases and installs it via
    ``uv tool install``. After upgrading the CLI, reminds you to run
    ``mycelium pull`` if containers also need updating.

    \b
    Examples:
        mycelium upgrade          # upgrade CLI to latest
        mycelium upgrade --check  # just check, don't install
    """
    try:
        from mycelium import __version__

        typer.echo(f"  Current CLI version: v{__version__}")
        typer.echo("")

        typer.echo("  Checking for updates...")
        latest_tag = _get_latest_release_tag()

        if not latest_tag:
            typer.secho("  ⚠  Could not fetch latest release from GitHub", fg=typer.colors.YELLOW)
            typer.echo(f"    Check manually: https://github.com/{_GITHUB_REPO}/releases")
            raise typer.Exit(1)

        latest_version = latest_tag.lstrip("v")
        current_tuple = _parse_version(__version__)
        latest_tuple = _parse_version(latest_version)

        if current_tuple >= latest_tuple:
            typer.secho(f"  ✓ CLI is up to date (v{__version__})", fg=typer.colors.GREEN)
            raise typer.Exit(0)

        typer.echo(f"  New version available: v{__version__} → {latest_tag}")
        typer.echo("")

        if check:
            typer.echo(f"  Run 'mycelium upgrade' to install {latest_tag}")
            raise typer.Exit(1)  # exit 1 = outdated (useful for scripts)

        # Try wheel from GitHub first, fall back to PyPI
        typer.echo("  Upgrading CLI...")

        wheel_name = f"mycelium_cli-{latest_version}-py3-none-any.whl"
        wheel_url = f"https://github.com/{_GITHUB_REPO}/releases/download/{latest_tag}/{wheel_name}"
        wheel_tmp = Path(f"/tmp/{wheel_name}")  # noqa: S108

        installed = False

        # Try GitHub wheel
        try:
            import urllib.request

            urllib.request.urlretrieve(wheel_url, str(wheel_tmp))  # noqa: S310
            result = subprocess.run(
                ["uv", "tool", "install", str(wheel_tmp), "--force"],
                capture_output=True,
                text=True,
            )
            wheel_tmp.unlink(missing_ok=True)
            if result.returncode == 0:
                installed = True
        except Exception:
            wheel_tmp.unlink(missing_ok=True)

        # Fall back to PyPI
        if not installed:
            typer.echo("    (GitHub wheel unavailable, trying PyPI...)")
            result = subprocess.run(
                ["uv", "tool", "install", f"mycelium-cli=={latest_version}", "--force"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                installed = True

        if not installed:
            typer.secho("  ✗ Upgrade failed", fg=typer.colors.RED)
            if result.stderr:
                typer.echo(f"    {result.stderr.strip()}")
            raise typer.Exit(1)

        typer.secho(f"  ✓ CLI updated to {latest_tag}", fg=typer.colors.GREEN)

        # Remind about containers
        typer.echo("")
        typer.echo("  Containers may also need updating.")
        typer.echo("  Run: mycelium pull")

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
