# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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

# Public images pulled during animation to speed compose-up.
_PUBLIC_IMAGES: list[tuple[str, str]] = []


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
        return False, "docker not found. Install Docker Desktop"
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

    env_path = Path.home() / ".mycelium" / ".env"
    if env_path.exists():
        from dotenv import dotenv_values

        existing = dotenv_values(env_path)
        model = existing.get("LLM_MODEL", "")
        key = existing.get("LLM_API_KEY", "")
        if model:
            print()
            keep = _ask(
                f"  LLM is currently \x1b[1m{model}\x1b[0m. Keep existing config? [Y/n] ",
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
    print("  \x1b[1;36m? LLM for the aligner\x1b[0m")
    print()

    providers = [
        "Anthropic  : claude-sonnet-4-6, claude-opus-4-6",
        "OpenAI     : gpt-4o, gpt-4.1",
        "OpenRouter : multi-provider gateway",
        "Ollama     : local models (llama3.3, mistral, etc.)",
        "Custom     : any OpenAI-compatible endpoint",
        "Skip       : no LLM (stub mode)",
    ]

    choice = select(providers, cursor="  ▸ ", cursor_style="cyan")
    if choice is None:
        raise KeyboardInterrupt
    assert isinstance(choice, str)  # noqa: S101

    if choice.startswith("Anthropic"):
        models = [
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-haiku-4-5",
        ]
        model = select(models, cursor="  ▸ ", cursor_style="cyan")
        assert isinstance(model, str)  # noqa: S101
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
        assert isinstance(model, str)  # noqa: S101
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
        assert isinstance(model, str)  # noqa: S101
        print(f"  \x1b[32m✓\x1b[0m {model} at localhost:11434")
        return {"LLM_MODEL": model, "LLM_BASE_URL": "http://host.docker.internal:11434"}

    if choice.startswith("Custom"):
        model = _ask("  \x1b[2mModel (provider/model format, e.g. openai/my-model):\x1b[0m ")
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
    print("  \x1b[33m~\x1b[0m Skipped. Synthesis will use stub responses")
    return {}


# ── Env file ─────────────────────────────────────────────────────────────────


def _write_env_file(env_path: Path, llm_config: dict[str, str]) -> None:
    import importlib.resources

    # On re-install, preserve existing .env and only update/append changed keys.
    # Remove LLM_BASE_URL when the new config doesn't include it: avoids
    # leaving a stale empty value that breaks the LLM client.
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
        if not ("=" in ln and not ln.lstrip().startswith("#") and ln.split("=")[0].strip() == key)
    ]
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Docker compose ────────────────────────────────────────────────────────────


def _refresh_compose_templates(*, backup: bool = True) -> list[Path]:
    """Overwrite ``~/.mycelium/docker/`` with the templates bundled in the
    currently-installed wheel.

    Refreshes ``compose.yml``. When *backup* is True (the default), the
    previous ``compose.yml`` is renamed to ``compose.yml.prev`` before
    overwrite: a single rolling backup that covers anyone who has hand-edited
    the file.

    The currently-running Python process loads ``importlib.resources`` from
    its own ``site-packages``, so this should only be called from a process
    running the NEW wheel after an upgrade. ``mycelium upgrade`` does that by
    invoking ``mycelium _refresh-templates`` as a subprocess of the freshly-
    installed binary.

    Returns the list of paths that were (re)written.
    """
    import importlib.resources

    refreshed: list[Path] = []
    dest_dir = Path.home() / ".mycelium" / "docker"
    dest_dir.mkdir(parents=True, exist_ok=True)

    compose_dest = dest_dir / "compose.yml"
    if backup and compose_dest.exists():
        prev = dest_dir / "compose.yml.prev"
        prev.write_bytes(compose_dest.read_bytes())
    compose_ref = importlib.resources.files("mycelium.docker") / "compose.yml"
    compose_dest.write_bytes(compose_ref.read_bytes())
    refreshed.append(compose_dest)

    # Copy companion override files. These are always bundled (docker/* in
    # package-data) and are not user-edited, so no backup is needed for them.
    for companion in ("compose-dev.yml", "compose-keycloak.yml", "compose-auth-dev.yml"):
        try:
            ref = importlib.resources.files("mycelium.docker") / companion
            data = ref.read_bytes()
            dest = dest_dir / companion
            dest.write_bytes(data)
            refreshed.append(dest)
        except Exception:
            pass  # file absent in this wheel version — skip silently

    return refreshed


def _get_compose_path() -> Path:
    """
    Resolve the canonical compose file path.

    For editable installs (dev), walk up from the package source to find the
    repo's services/docker-compose.yml; this keeps build context relative
    paths (../fastapi-backend) correct.

    For non-editable installs, extract the bundled compose to ~/.mycelium/docker/.
    Build contexts won't work in that case, but pull-only services will.
    """
    import importlib.resources
    import os

    if env_path := os.getenv("MYCELIUM_COMPOSE_FILE"):
        return Path(env_path)

    # Check cwd: covers running `mycelium install` from the repo root
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

    # Fallback: extract bundled compose. No backup here (first-time install,
    # nothing to preserve.
    refreshed = _refresh_compose_templates(backup=False)
    return refreshed[0]  # compose.yml is always first


def _image_exists(image: str) -> bool:
    """Return True if a Docker image is already present locally."""
    r = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    return r.returncode == 0


# Containers `mycelium up` creates with no profile flag. A stale copy of any of
# them fails `compose up --force-recreate` on a name conflict, so install clears
# them first.
_KNOWN_CONTAINERS = [
    "mycelium-slim",
    "mycelium-backend",
    "mycelium-frontend",
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


def _compose_up(compose_path: Path, env_path: Path) -> tuple[bool, bool]:
    """Bring the stack up.  Returns (success, needs_build)."""
    # Build context exists when running from a repo checkout. Packaged installs
    # extract compose to ~/.mycelium/docker/ where ../fastapi-backend is absent;
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
    up_flags = ["up", "--pull", "always", "--force-recreate", "-d"]
    if can_build:
        up_flags.append("--build")
    else:
        up_flags.append("--no-build")
    args += up_flags

    print()
    typer.secho("  Running: " + " ".join(args[2:]), dim=True)
    if needs_build:
        typer.secho("  (first run: building backend image, this may take a few minutes)", dim=True)
    print()

    result = subprocess.run(args, text=True)
    if result.returncode == 0:
        from mycelium.docker_utils import patch_build_mode

        patch_build_mode(env_path, "")
    return result.returncode == 0, needs_build


def _wait_for_health(urls: list[str], timeout: int = 120) -> bool:
    try:
        import httpx
    except ImportError:
        typer.echo("  ⚠ httpx not installed, skipping health check")
        return False

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


def _probe_llm_via_backend(api_url: str) -> tuple[str, str, str, str]:
    """Probe the configured LLM via the backend's /health endpoint.

    Uses ``check_llm=true&llm_probe=completion`` so the backend runs a real
    one-shot ``pi`` turn.  This catches a missing/broken ``pi`` binary, bad model
    strings, and auth errors, all of which would otherwise only surface at first
    inference.

    Returns ``(status, model, message, remediation)``.  Status is one of the
    LLMHealthResult states (ok | auth_error | missing_extras | bad_model |
    unreachable | not_configured | unchecked | error) or the special value
    ``"backend_down"`` when the backend itself isn't reachable.
    """
    try:
        import httpx
    except ImportError:
        return ("backend_down", "", "httpx not installed", "")

    try:
        resp = httpx.get(
            f"{api_url}/health",
            params={"check_llm": "true", "llm_probe": "completion"},
            timeout=30,
        )
    except Exception as exc:
        return ("backend_down", "", f"cannot reach backend: {exc}", "")

    if resp.status_code >= 500:
        return ("backend_down", "", f"backend returned HTTP {resp.status_code}", "")

    try:
        llm = resp.json().get("llm", {}) or {}
    except Exception:
        return ("backend_down", "", "backend returned non-JSON response", "")

    return (
        llm.get("status", "unknown") or "unknown",
        llm.get("model", "") or "",
        llm.get("message", "") or "",
        llm.get("remediation") or "",
    )


def _report_llm_probe_result(
    status: str,
    model: str,
    message: str,
    remediation: str,
    *,
    interactive: bool,
) -> bool:
    """Pretty-print an install-time LLM probe result.

    Returns True if the user should be allowed to continue, False if the caller
    should abort.  We never hard-fail the install on a probe failure; the user
    may legitimately want to fix things after install, or be running in an
    environment where the probe is wrong (e.g. proxy, network blocked during
    install).
    """
    if status == "ok":
        typer.secho(f"  ✓ LLM probe succeeded  {model}", fg=typer.colors.GREEN)
        return True

    if status == "unchecked":
        # We couldn't verify, so don't nag the user about it.
        typer.secho(
            f"  ~ LLM configured  {model}  (probe unsupported for this provider)",
            fg=typer.colors.YELLOW,
        )
        return True

    if status == "not_configured":
        typer.secho(
            "  ~ LLM not configured. Synthesis will use stub responses",
            fg=typer.colors.YELLOW,
        )
        return True

    # All other statuses are failures: print a coloured header + the backend's
    # own message and remediation hint, then let the caller decide what to do.
    headers = {
        "missing_extras": ("✗", "LLM provider SDK missing in backend", typer.colors.RED),
        "bad_model": ("✗", "LLM model string is invalid", typer.colors.RED),
        "auth_error": ("⚠", "LLM authentication failed", typer.colors.YELLOW),
        "unreachable": ("⚠", "LLM provider unreachable from backend", typer.colors.YELLOW),
        "error": ("✗", "LLM probe failed", typer.colors.RED),
        "backend_down": ("~", "LLM probe skipped: backend not reachable", typer.colors.YELLOW),
    }
    icon, header, color = headers.get(status, ("✗", f"LLM probe: {status}", typer.colors.RED))

    typer.secho(f"  {icon} {header}", fg=color)
    if model:
        typer.echo(f"      model: {model}")
    if message:
        typer.echo(f"      {message}")
    if remediation:
        typer.secho(f"      fix: {remediation}", fg=typer.colors.CYAN)
    typer.echo("      Run `mycelium doctor` any time to re-check.")

    # backend_down is not a hard LLM failure; the probe just couldn't run.
    # The user probably already knows the backend is having trouble.
    if status == "backend_down":
        return True

    if not interactive:
        # In non-interactive mode we surface the warning and keep going.
        return True

    try:
        answer = input("  Continue install anyway? [Y/n] ").strip()
    except (EOFError, KeyboardInterrupt):
        return True
    return answer.lower() in ("y", "yes", "")


# ── Config write ─────────────────────────────────────────────────────────────


def _recreate_backend(compose_path: Path, env_path: Path) -> bool:
    """Recreate the backend container so it picks up a regenerated .env."""
    args = [
        "docker",
        "compose",
        "-p",
        "mycelium",
        "-f",
        str(compose_path),
        "--env-file",
        str(env_path),
        "up",
        "-d",
        "--force-recreate",
        "--no-build",
        "mycelium-backend",
    ]
    result = subprocess.run(args, text=True)
    return result.returncode == 0


def _run_telemetry_disclosure(api_url: str, *, compose_path: Path) -> None:  # noqa: ARG001
    """Interactive opt-in disclosure for product analytics.

    Shows what would be collected (event categories, destination, retention) and
    asks for consent before enabling. Defaults to *No*.

    Non-interactive installs never reach this path; they stay off unconditionally
    as required by #938.
    """
    import uuid

    from mycelium.config import MyceliumConfig, TelemetryConfig

    print()
    typer.secho("  ── Optional: product analytics ─────────────────────────", bold=True)
    print()
    typer.echo("  Help improve Mycelium by sending anonymous adoption metrics.")
    typer.echo("")
    typer.echo("  What would be sent:")
    typer.echo("    • Install event (OS kind, release version)")
    typer.echo("    • Session outcome (coordinated vs not, aggregate result)")
    typer.echo("")
    typer.echo("  What is never sent:")
    typer.echo("    • Room names, task content, prompts, replies, handles")
    typer.echo("    • IP addresses, hostnames, or any identifying information")
    typer.echo("")
    typer.echo("  Each install is identified by a random UUID stored in config.toml.")
    typer.echo("  Destination: not yet configured (pending #937 go/no-go decision).")
    typer.echo("")
    typer.echo("  Disable at any time:")
    typer.echo("    mycelium config set telemetry.send_product_analytics false")
    print()

    try:
        consent = typer.confirm(
            "  Enable anonymous product analytics?",
            default=False,
        )
    except (EOFError, KeyboardInterrupt):
        consent = False

    config_path = MyceliumConfig.get_global_config_path()
    try:
        config = MyceliumConfig.load(config_path) if config_path.exists() else MyceliumConfig()
    except Exception:
        config = MyceliumConfig()

    if config.telemetry is None:
        config.telemetry = TelemetryConfig()

    # Generate install_id regardless of consent so it's ready when the user
    # opts in later via `mycelium config set telemetry.send_product_analytics true`.
    if not config.telemetry.install_id:
        config.telemetry.install_id = str(uuid.uuid4())

    config.telemetry.send_product_analytics = consent
    config.save()

    # Phase 5 already wrote .env with send_product_analytics=false; regenerate
    # so the running backend picks up the user's opt-in.
    from mycelium.docker_utils import write_env_file

    env_path, _ = write_env_file(config)
    typer.echo(f"  ✓ Regenerated {env_path} from config.toml")

    if consent:
        if _recreate_backend(compose_path, env_path):
            typer.echo("  ✓ Backend recreated with updated telemetry settings")
        else:
            typer.secho(
                "  ⚠ Could not recreate backend — run "
                "`mycelium config apply && mycelium up` to pick up telemetry settings",
                fg=typer.colors.YELLOW,
            )
        typer.secho("  ✓ Analytics enabled — thank you!", fg=typer.colors.GREEN)
        # Fire the install event. The destination is not yet set (#937) so this
        # is a no-op until the destination URL is configured, but the opt-in is
        # persisted for when it is.
        try:
            import platform

            from mycelium.config import MyceliumConfig as _MC

            def _release() -> str:
                try:
                    from importlib.metadata import version

                    return version("mycelium")
                except Exception:
                    return "unknown"

            # Inline analytics emit (avoids importing the backend analytics module
            # from the CLI).  Mirrors analytics.install_event logic.
            _config = _MC.load() if _MC.get_global_config_path().exists() else _MC()
            _dest = (
                _config.telemetry.analytics_destination
                if _config.telemetry.analytics_destination
                else ""
            )
            if _dest and _dest.startswith("https://"):
                import json
                import urllib.request

                payload = json.dumps(
                    {
                        "event": "mycelium.install",
                        "install_id": config.telemetry.install_id,
                        "release": _release(),
                        "ts": __import__("datetime")
                        .datetime.now(__import__("datetime").timezone.utc)
                        .isoformat(),
                        "platform": platform.system() or "unknown",
                    }
                ).encode()
                req = urllib.request.Request(
                    _dest,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as _r:  # noqa: S310
                        pass
                except Exception:
                    pass
        except Exception:
            pass
    else:
        typer.echo("  Analytics disabled (default).")


def _write_mycelium_config(
    api_url: str,
    llm_config: dict[str, str] | None = None,
    custom_ports: dict[str, int] | None = None,
) -> None:
    from mycelium.config import LLMConfig, MyceliumConfig, RuntimeConfig, ServerConfig
    from mycelium.docker_utils import write_env_file

    config_path = MyceliumConfig.get_global_config_path()
    try:
        config = MyceliumConfig.load(config_path) if config_path.exists() else MyceliumConfig()
    except Exception:
        config = MyceliumConfig()

    config.server = ServerConfig(api_url=api_url)

    # Persist LLM settings into [llm] section
    if llm_config:
        config.llm = LLMConfig(
            model=llm_config.get("LLM_MODEL") or config.llm.model,
            api_key=llm_config.get("LLM_API_KEY") or config.llm.api_key,
            base_url=llm_config.get("LLM_BASE_URL") or config.llm.base_url,
        )

    # Persist runtime settings into [runtime] section
    runtime = RuntimeConfig(data_dir=str(Path.home() / ".mycelium"))
    if custom_ports:
        runtime.backend_port = custom_ports.get("backend", 8000)
        runtime.collector_port = custom_ports.get("collector", 4318)
    config.runtime = runtime

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config.save(config_path)

    # Derive .env from the canonical config.toml
    env_path, secret_assigned = write_env_file(config)
    typer.echo(f"  ✓ Regenerated {env_path} from config.toml")
    if secret_assigned:
        typer.echo("  ✓ Generated [slim].master_secret (hub SLIM PSK)")


# ── Main ─────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium install [--yes] [--non-interactive] [--force]",
    desc="Interactive installer: Docker check, LLM config, <code>docker compose up</code>, provision workspace.",
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
        "", "--llm-model", help="LLM model in provider/model format (non-interactive)"
    ),
    llm_base_url: str = typer.Option("", "--llm-base-url", help="LLM base URL (non-interactive)"),
    llm_api_key: str = typer.Option("", "--llm-api-key", help="LLM API key (non-interactive)"),
    backend_port: int = typer.Option(
        0, "--backend-port", help="Host port for backend API (0 = auto-detect, default 8000)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Force full reinstall even if already installed"
    ),
    tag: str = typer.Option(
        "",
        "--tag",
        help="Pin MYCELIUM_IMAGE_TAG (mycelium-io image version, e.g. 2.0.0) instead of "
        "the :latest default.",
    ),
) -> None:
    """
    Install a Mycelium instance.

    By default this runs interactively: it plays an intro animation, prompts
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
        --llm-api-key sk-ant-...

    \b
    FLAGS (non-interactive)
      --llm-model     LLM in provider/model format, e.g. anthropic/claude-sonnet-4-6
                      or openai/gpt-4o or ollama/llama3
      --llm-base-url  Custom base URL (required for ollama / local models)
      --llm-api-key   API key for the chosen LLM provider
      --backend-port  Host port for backend API (default: 8000, auto-increments on conflict)
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
            typer.echo("    mycelium upgrade    : fetch latest CLI")
            typer.echo("    mycelium pull       : pull latest containers and restart")
            typer.echo("    mycelium doctor     : diagnose and fix issues")
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

            # Resolve ports: use explicit flags, or auto-detect conflicts
            default_ports: dict[str, int] = {
                "backend": backend_port or 8000,
                "ui": 3000,
            }
            busy = _check_ports(list(default_ports.values()))
            for label, port in list(default_ports.items()):
                if port in busy:
                    new_port = port + 1
                    while new_port in busy or new_port in default_ports.values():
                        new_port += 1
                    typer.secho(
                        f"  ⚠  Port {port} ({label}) in use, using {new_port}",
                        fg=typer.colors.YELLOW,
                    )
                    default_ports[label] = new_port
            custom_ports = default_ports
            llm_config["MYCELIUM_BACKEND_PORT"] = str(custom_ports["backend"])
            llm_config["MYCELIUM_UI_PORT"] = str(custom_ports["ui"])
            llm_config["MYCELIUM_DATA_DIR"] = str(Path.home() / ".mycelium")

            typer.secho(
                "  ⚠  Experimental software. Please report issues at github.com/mycelium-io/mycelium/issues",
                fg=typer.colors.YELLOW,
            )
            typer.secho("  ── Starting services ──────────────────────────────────", bold=True)
            env_dir = Path.home() / ".mycelium"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_path = env_dir / ".env"
            if tag:
                llm_config["MYCELIUM_IMAGE_TAG"] = tag
            _write_env_file(env_path, llm_config)
            typer.echo(f"  ✓ Wrote {env_path}")

            compose_path = _get_compose_path()
            typer.echo(f"  ✓ Compose file → {compose_path}")

            ok, needs_build = _compose_up(compose_path, env_path)
            if not ok:
                typer.secho("\n  ✗ docker compose up failed", fg=typer.colors.RED)
                raise typer.Exit(1) from None

            api_url = f"http://localhost:{custom_ports['backend']}"
            health_timeout = 300 if needs_build else 120
            _wait_for_health([f"{api_url}/health"], timeout=health_timeout)

            _write_mycelium_config(
                api_url,
                llm_config=llm_config,
                custom_ports=custom_ports,
            )

            # LLM probe: real completion call inside the backend container.
            # Non-interactive mode only warns; it never blocks the install.
            if llm_config.get("LLM_MODEL"):
                typer.echo("  Probing LLM...")
                status, model, msg, remediation = _probe_llm_via_backend(api_url)
                _report_llm_probe_result(status, model, msg, remediation, interactive=False)

            typer.secho("  ✓ Done.", fg=typer.colors.GREEN, bold=True)
            typer.echo(f"  mycelium-backend  → {api_url}")
            typer.echo(f"  mycelium-frontend → http://localhost:{custom_ports['ui']}")
            typer.echo("  Open it with: mycelium ui open")
            return

        if not sys.stdin.isatty():
            typer.secho(
                "\n  ✗ Non-interactive terminal detected. Interactive install requires a TTY.\n",
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

        # Fail fast: no point running the animation if Docker isn't available
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
            "  \x1b[33m⚠  Experimental software. Please report issues at github.com/mycelium-io/mycelium/issues\x1b[0m",
            "",
            f"    {ok if docker_ok else err} docker {docker_ver}",
            f"    {ok if compose_ok else err} docker compose {compose_ver}",
            f"    {ok if disk_ok else err} disk {disk_info}",
            "",
            "  \x1b[1mPulling base images\x1b[0m",
            "",
        ]
        # One slot per image, updated in-place by the pull thread.
        image_lines: list[str] = [f"    {spin} {label}" for _, label in _PUBLIC_IMAGES]
        # Sliding window of recent pull output lines.
        log_window: list[str] = []

        done = threading.Event()

        # Pre-pulled images must match the compose platform.
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
        # Force amd64 platform for pre-pulled images when on arm64.
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
                            f"    {err} {label}  \x1b[2m(skipped, docker not available)\x1b[0m"
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

        # Port check: allow user to pick alternatives
        default_ports: dict[str, int] = {"backend": 8000, "ui": 3000}
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
            llm_config["MYCELIUM_BACKEND_PORT"] = str(custom_ports["backend"])
            llm_config["MYCELIUM_UI_PORT"] = str(custom_ports["ui"])

        # Set MYCELIUM_DATA_DIR so compose mounts the host's .mycelium/ into the container
        llm_config["MYCELIUM_DATA_DIR"] = str(Path.home() / ".mycelium")

        # ── Phase 3: Write env, bring up services ─────────────────────────
        print()
        typer.secho("  ── Starting services ──────────────────────────────────", bold=True)

        env_dir = Path.home() / ".mycelium"
        env_dir.mkdir(parents=True, exist_ok=True)
        env_path = env_dir / ".env"

        if not env_path.exists():
            typer.echo(f"  ✓ Creating {env_path}")
        else:
            typer.echo(f"  ~ Updating existing {env_path}")
        if tag:
            llm_config["MYCELIUM_IMAGE_TAG"] = tag
        _write_env_file(env_path, llm_config)
        typer.echo(f"  ✓ Wrote {env_path}")

        compose_path = _get_compose_path()
        typer.echo(f"  ✓ Compose file → {compose_path}")

        ok, needs_build = _compose_up(compose_path, env_path)
        if not ok:
            typer.secho("\n  ✗ docker compose up failed", fg=typer.colors.RED)
            raise typer.Exit(1) from None

        # ── Phase 4: Health checks ─────────────────────────────────────────
        # Allow extra time on first run when the backend image is being built.
        api_url = f"http://localhost:{custom_ports['backend']}"
        health_timeout = 300 if needs_build else 120
        print()
        _wait_for_health([f"{api_url}/health"], timeout=health_timeout)

        # ── Phase 5: Write config ─────────────────────────────────────────
        print()
        typer.echo("  ── Provisioning backend ────────────────────────────────")
        _write_mycelium_config(
            api_url,
            llm_config=llm_config,
            custom_ports=custom_ports,
        )
        typer.secho("  ✓ Config written to ~/.mycelium/config.toml", fg=typer.colors.GREEN)

        # ── Phase 6: Telemetry disclosure ─────────────────────────────────
        # Non-interactive installs (handled in the early branch above) stay off
        # unconditionally. This phase runs only on the interactive path.
        _run_telemetry_disclosure(api_url, compose_path=compose_path)

        # ── Phase 7: LLM connectivity probe ─────────────────────────────────
        # Real one-shot pi turn inside the backend. Catches a missing/broken pi
        # binary, bad model strings, and auth errors that would otherwise only
        # surface at first inference.
        # On failure we ask the user whether to continue; never hard-fail,
        # since the user may be installing with a known-bad LLM config on purpose.
        if llm_config.get("LLM_MODEL"):
            print()
            typer.secho("  ── Probing LLM ─────────────────────────────────────────", bold=True)
            status, probed_model, msg, remediation = _probe_llm_via_backend(api_url)
            keep_going = _report_llm_probe_result(
                status, probed_model, msg, remediation, interactive=True
            )
            if not keep_going:
                typer.secho(
                    "  Install cancelled. Re-run after fixing the LLM config.",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(1) from None

        # ── Done ───────────────────────────────────────────────────────────
        print()
        typer.secho("  Mycelium is ready.", fg=typer.colors.GREEN, bold=True)
        print()
        typer.echo("  Services:")
        typer.echo(f"    mycelium-backend  → {api_url}")
        typer.echo(f"    mycelium-frontend → http://localhost:{custom_ports['ui']}")
        print()
        typer.echo("  Next steps:")
        typer.echo("    mycelium adapter add claude-code  # wire your Claude Code agent")
        typer.echo("    mycelium room create <name>      # create your first room")
        typer.echo("    mycelium ui open                # open the frontend in your browser")
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
    usage="mycelium upgrade [--check] [--version <version>]",
    desc="Upgrade (or pin) the Mycelium CLI. Pass --version to install a specific release.",
    group="setup",
)
def upgrade(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Just check for updates, don't install"),
    target_version: str | None = typer.Option(
        None,
        "--version",
        help="Install a specific version (e.g. 0.1.83 or v0.1.83) instead of latest. "
        "Useful for pinning, rollback, or reproducing a specific release.",
    ),
) -> None:
    """
    Upgrade the Mycelium CLI to the latest release, or install a specific version.

    Fetches the target version from GitHub releases and installs it via
    ``uv tool install``. After upgrading the CLI, reminds you to run
    ``mycelium pull`` if containers also need updating.

    With ``--version``, the resolved version is installed directly without
    any "is this newer?" gate, so the same flag works for upgrade,
    downgrade, or pinning to the current release.

    \b
    Examples:
        mycelium upgrade                    # upgrade CLI to latest
        mycelium upgrade --check            # just check, don't install
        mycelium upgrade --version 0.1.83   # install a specific version
        mycelium upgrade --version v0.1.83  # leading v is fine too
    """
    try:
        from mycelium import __version__

        typer.echo(f"  Current CLI version: v{__version__}")
        typer.echo("")

        # --version pins directly without is-this-newer check (for downgrade/pin).
        if target_version is not None:
            latest_version = target_version.lstrip("v")
            latest_tag = f"v{latest_version}"
            if check:
                typer.echo(f"  --check ignored with --version; would install {latest_tag}")
                raise typer.Exit(0)
            typer.echo(f"  Installing {latest_tag}...")
        else:
            typer.echo("  Checking for updates...")
            latest_tag = _get_latest_release_tag()

            if not latest_tag:
                typer.secho(
                    "  ⚠  Could not fetch latest release from GitHub", fg=typer.colors.YELLOW
                )
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

            typer.echo("  Upgrading CLI...")

        # Try wheel from GitHub first, fall back to PyPI
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

        # Refresh ~/.mycelium/docker/compose.yml + initdb/ to match the new
        # wheel. The currently-running process still has the OLD package
        # loaded, so we shell out to the freshly-installed binary; it'll
        # importlib.resources from the NEW site-packages. Previous
        # compose.yml is preserved as compose.yml.prev.
        typer.echo("")
        typer.echo("  Refreshing compose templates...")
        try:
            refresh = subprocess.run(
                ["mycelium", "_refresh-templates"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if refresh.returncode == 0:
                if refresh.stdout:
                    typer.echo(refresh.stdout.rstrip())
                typer.secho("  ✓ Compose templates refreshed", fg=typer.colors.GREEN)
            else:
                typer.secho(
                    "  ⚠  Template refresh failed. Run 'mycelium _refresh-templates' manually.",
                    fg=typer.colors.YELLOW,
                )
                if refresh.stderr:
                    typer.echo(f"    {refresh.stderr.strip()}")
        except Exception as exc:
            typer.secho(f"  ⚠  Template refresh failed: {exc}", fg=typer.colors.YELLOW)
            typer.echo("    Run 'mycelium _refresh-templates' manually.")

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


def refresh_templates(ctx: typer.Context) -> None:
    """Overwrite ~/.mycelium/docker/ templates with the bundled versions.

    Hidden subcommand, invoked by ``mycelium upgrade`` after the new wheel
    is installed, so the bundled compose.yml + initdb/ scripts on disk match
    the running CLI. The previous compose.yml is preserved as compose.yml.prev.

    Safe to call manually if the upgrade hook failed (e.g., subprocess
    timeout) or if you want to revert to the bundled compose.yml.
    """
    try:
        refreshed = _refresh_compose_templates()
        for path in refreshed:
            typer.echo(f"  ✓ {path}")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
