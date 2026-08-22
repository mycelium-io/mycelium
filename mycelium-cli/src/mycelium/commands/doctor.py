# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Doctor command: diagnose and fix common Mycelium configuration issues.

Checks:
  1. Config files exist (~/.mycelium/.env, config.toml)
  2. Config file drift: every shared key aligned between .env and config.toml
  3. Runtime config drift: backend container env matches .env on disk
  4. Docker containers running and healthy
  5. Backend API reachable
  6. LLM connectivity (real completion probe via backend)
  7. Cursor adapter health (binary, login, workspace assets)

Single-device installs (the default) run the backend locally and exercise
all checks. In the optional hub-and-spoke deployment mode, spoke nodes
connect to a remote backend and don't run local Docker containers. When
``server.api_url`` points at a non-local host the doctor auto-detects
**spoke mode** and skips checks that only apply when the backend is
local (Docker containers, runtime config drift, .env port vs Docker
port).  An explicit ``--mode hub|spoke`` flag overrides the auto-detection.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import typer

from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.ui_status import (
    CheckResult,
    print_check,
    print_section,
    print_title,
    print_verdict,
)

# ── Topology detection ────────────────────────────────────────────────────────


def _is_local_backend(api_url: str) -> bool:
    """Return True when *api_url* targets this machine (hub / all-in-one)."""
    host = (urlparse(api_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# ── Individual checks ────────────────────────────────────────────────────────


def _check_config_files() -> CheckResult:
    """Check that ~/.mycelium/.env and config.toml exist."""
    import os

    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    missing = []
    if not env_path.exists():
        missing.append(".env")
    if not config_path.exists():
        missing.append("config.toml")

    # A client configured from the environment — an ephemeral container, a CI
    # job — has no config files by design, and `mycelium install` is the wrong
    # advice for a machine with no stack to install.
    if missing and os.environ.get("MYCELIUM_API_URL"):
        return CheckResult(
            name="Config files",
            status="ok",
            message="configured from the environment (MYCELIUM_API_URL)",
        )

    if missing:
        return CheckResult(
            name="Config files",
            status="error",
            message=f"Missing: {', '.join(missing)}",
            details=["Run: mycelium install"],
        )
    return CheckResult(
        name="Config files",
        status="ok",
        message="~/.mycelium/.env and config.toml present",
    )


def _check_mycelium_dir_ownership() -> CheckResult:
    """Surface files under ``~/.mycelium/`` not owned by the current user.

    Root-owned files in here are a common cloud-install symptom (sudo
    install + non-sudo agent add, or a service running as root). They lead to opaque
    ``PermissionError`` failures in later commands. Detect early and point
    at the single ``chown`` that fixes it.
    """
    import os

    if os.name == "nt":  # Windows has no uid
        return CheckResult(
            name="~/.mycelium ownership",
            status="ok",
            message="not applicable on this platform",
        )

    mycelium_dir = Path.home() / ".mycelium"
    if not mycelium_dir.exists():
        return CheckResult(
            name="~/.mycelium ownership",
            status="ok",
            message="directory does not exist yet",
        )

    uid = os.getuid()
    foreign: list[str] = []
    # Cap the walk; a pathological room shouldn't make doctor hang.
    seen = 0
    for path in mycelium_dir.rglob("*"):
        seen += 1
        if seen > 5000:
            break
        try:
            if path.stat().st_uid != uid:
                # Show paths relative to ~ for readable output.
                foreign.append(str(path.relative_to(Path.home())))
        except OSError:
            continue
        if len(foreign) >= 5:
            break

    if not foreign:
        return CheckResult(
            name="~/.mycelium ownership",
            status="ok",
            message="all files owned by current user",
        )

    details = [f"~/{p}" for p in foreign]
    details.append("Fix with: sudo chown -R $USER ~/.mycelium")
    return CheckResult(
        name="~/.mycelium ownership",
        status="error",
        message=f"{len(foreign)}+ file(s) owned by another user; agent/memory writes will fail",
        details=details,
    )


def _check_llm_connectivity() -> CheckResult:
    """Probe the backend's LLM with a real one-shot ``pi`` turn.

    Exercises the same runtime as inference and surfaces problems that only
    show up at first use: a missing/broken ``pi`` binary, bad model strings,
    and auth failures at the actual endpoint (not just the free model-list
    endpoint).

    Runs via ``GET /health?check_llm=true&llm_probe=completion`` so the probe
    executes inside the backend container, which is where LLM calls will
    actually run in production.
    """
    # Skip entirely if the LLM isn't configured at all; _check_llm_config
    # already reported that and running the probe would be redundant noise.
    env_path = Path.home() / ".mycelium" / ".env"
    if env_path.exists():
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        if not vals.get("LLM_MODEL"):
            return CheckResult(
                name="LLM connectivity",
                status="ok",
                message="Skipped (LLM_MODEL not set)",
            )

    from mycelium.config import MyceliumConfig

    try:
        config = MyceliumConfig.load()
        api_url = config.server.api_url
    except Exception:
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message="Skipped (cannot load config)",
        )

    try:
        import httpx

        resp = httpx.get(
            f"{api_url}/health",
            params={"check_llm": "true", "llm_probe": "completion"},
            timeout=30,
        )
    except Exception as exc:
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message="Skipped (backend unreachable)",
            details=[str(exc), "Start the backend: mycelium up"],
        )

    if resp.status_code >= 500:
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message=f"Backend /health returned HTTP {resp.status_code}",
        )

    try:
        llm = resp.json().get("llm", {}) or {}
    except Exception:
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message="Backend returned non-JSON response",
        )

    status = llm.get("status", "unknown")
    model = llm.get("model", "") or "<unset>"
    message = llm.get("message", "") or ""
    remediation = llm.get("remediation") or ""

    details: list[str] = []
    if message:
        details.append(message)
    if remediation:
        details.append(f"fix: {remediation}")

    # Map backend status → doctor status.  Missing provider SDKs and bad model
    # strings are hard failures; auth + network are warnings (transient or
    # user-fixable without a reinstall).
    if status == "ok":
        return CheckResult(
            name="LLM connectivity",
            status="ok",
            message=f"{model}: completion probe succeeded",
        )
    if status == "not_configured":
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message="Not configured",
            details=["Run: mycelium install --force"],
        )
    if status == "missing_extras":
        return CheckResult(
            name="LLM connectivity",
            status="error",
            message=f"{model}: missing provider SDK in backend",
            details=details,
        )
    if status == "bad_model":
        return CheckResult(
            name="LLM connectivity",
            status="error",
            message=f"{model}: invalid model string",
            details=details,
        )
    if status == "auth_error":
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message=f"{model}: authentication failed",
            details=details,
        )
    if status == "unreachable":
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message=f"{model}: provider unreachable",
            details=details,
        )
    if status == "unchecked":
        return CheckResult(
            name="LLM connectivity",
            status="ok",
            message=f"{model}: probe unsupported for this provider",
            details=details,
        )
    # error | unknown
    return CheckResult(
        name="LLM connectivity",
        status="error",
        message=f"{model}: {status}",
        details=details,
    )


def _check_docker_containers() -> CheckResult:
    """Check that expected containers are running and healthy."""
    expected = ["mycelium-backend"]

    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return CheckResult(
                name="Docker containers",
                status="error",
                message="Docker not available",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return CheckResult(
            name="Docker containers",
            status="error",
            message="Docker not available",
        )

    running = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            running[parts[0]] = parts[1]

    missing = [c for c in expected if c not in running]
    unhealthy = [c for c in expected if c in running and "unhealthy" in running.get(c, "").lower()]

    if missing:
        return CheckResult(
            name="Docker containers",
            status="error",
            message=f"Not running: {', '.join(missing)}",
            details=["Run: mycelium up"],
        )
    if unhealthy:
        return CheckResult(
            name="Docker containers",
            status="warning",
            message=f"Unhealthy: {', '.join(unhealthy)}",
            details=["Check: mycelium logs"],
        )

    healthy_list = ", ".join(f"{c} (up)" for c in expected if c in running)
    return CheckResult(
        name="Docker containers",
        status="ok",
        message=healthy_list,
    )


def _backend_container_running() -> bool:
    """True if the ``mycelium-backend`` container is up (backend is dockerized)."""
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if r.returncode != 0:
        return False
    return "mycelium-backend" in r.stdout.split()


def _check_mediator_pi_binary() -> CheckResult:
    """The aligner's SAO mediator runs on Pi; warn if it's unreachable on a
    host-run backend.

    Pi is the mediator's *brain*; without it on PATH, an ``@aligner`` summon fails
    (``PiBrainError: pi not found``). The released **backend image already installs
    Pi**, so the normal ``mycelium up`` path is fine and needs no host binary. The
    only gap is running the backend *outside Docker* (a contributor doing
    ``uvicorn app.main:app`` on the host): there Pi must be on the host PATH. So:
    if the backend container is up, this is satisfied by the image; otherwise check
    the host.
    """
    import os
    import shutil

    if _backend_container_running():
        return CheckResult(
            name="mediator Pi brain",
            status="ok",
            message="backend is dockerized (Pi ships in the image)",
        )

    binary = os.environ.get("ALIGNER_PI_BINARY") or "pi"
    resolved = shutil.which(binary)
    if resolved is not None:
        return CheckResult(
            name="mediator Pi brain",
            status="ok",
            message=f"pi on PATH ({resolved})",
        )
    return CheckResult(
        name="mediator Pi brain",
        status="warning",
        message=f"`{binary}` not on PATH; @aligner negotiations will fail on a host-run backend",
        details=[
            "the released backend image already ships Pi, so `mycelium up` needs nothing here;",
            "this only bites when you run the backend outside Docker (host uvicorn).",
            "fix: npm install -g @mariozechner/pi-coding-agent",
            "or point ALIGNER_PI_BINARY at an existing pi install.",
        ],
    )


def _check_backend_reachable(*, local_backend: bool = True) -> CheckResult:
    """Check that the backend API responds to /health."""
    from mycelium.config import MyceliumConfig

    try:
        config = MyceliumConfig.load()
    except Exception:
        return CheckResult(
            name="Backend reachable",
            status="error",
            message="Cannot load config",
        )

    api_url = config.server.api_url

    try:
        import httpx

        resp = httpx.get(f"{api_url}/health", timeout=5)
        if resp.status_code < 500:
            data = resp.json()
            status = data.get("status", "unknown")
            version = data.get("version", "")
            label = f"{api_url} ({status})"
            if version:
                label += f" v{version}"
            return CheckResult(
                name="Backend reachable",
                status="ok" if status in ("ok", "degraded") else "warning",
                message=label,
            )
        return CheckResult(
            name="Backend reachable",
            status="error",
            message=f"{api_url} returned HTTP {resp.status_code}",
        )
    except Exception as exc:
        hint = "Run: mycelium up" if local_backend else f"Check the remote backend at {api_url}"
        return CheckResult(
            name="Backend reachable",
            status="error",
            message=f"Cannot connect to {api_url}",
            details=[str(exc), hint],
        )


def _read_env_master_secret() -> str | None:
    """Return ``MYCELIUM_SLIM_MASTER_SECRET`` from ``~/.mycelium/.env`` if set."""
    env_path = Path.home() / ".mycelium" / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        if key.strip() == "MYCELIUM_SLIM_MASTER_SECRET":
            cleaned = val.strip().strip('"').strip("'")
            return cleaned or None
    return None


def _check_http_auth_gate(*, api_url: str) -> CheckResult:
    """Warn when the hub HTTP API is reachable but auth is off on a remote URL."""
    host = (urlparse(api_url).hostname or "").lower()
    remote_target = host not in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    try:
        import httpx

        resp = httpx.get(f"{api_url.rstrip('/')}/health", timeout=5)
        if resp.status_code >= 500:
            return CheckResult(
                name="HTTP API auth",
                status="warning",
                message="Could not read auth status from /health",
            )
        auth = resp.json().get("auth") or {}
        if auth.get("enabled"):
            details = [str(w) for w in auth.get("warnings") or []]
            status = "warning" if details else "ok"
            return CheckResult(
                name="HTTP API auth",
                status=status,
                message="JWT gate enabled on hub",
                details=details,
            )
        if remote_target:
            return CheckResult(
                name="HTTP API auth",
                status="warning",
                message=(
                    "HTTP JWT gate is off — peers can read/write memory and post as any @handle"
                ),
                details=[
                    "Spokes use the HTTP API (:8000), not SLIM PSK.",
                    "Enable auth.enabled on the hub before sharing over a network.",
                    "See: mycelium config set auth.enabled true",
                ],
            )
        return CheckResult(
            name="HTTP API auth",
            status="ok",
            message="Off (local backend — expected for try-it)",
        )
    except Exception as exc:
        return CheckResult(
            name="HTTP API auth",
            status="warning",
            message=f"Could not check auth status: {type(exc).__name__}",
            details=[str(exc)],
        )


def _hub_slim_master_secret() -> str | None:
    """Return the hub SLIM master secret from config.toml, falling back to .env."""
    try:
        from mycelium.config import MyceliumConfig

        secret = MyceliumConfig.load().slim.master_secret
        if secret:
            return secret
    except Exception:
        pass
    return _read_env_master_secret()


def _check_hub_slim_psk(*, local_backend: bool) -> CheckResult | None:
    """Hub-only: warn when SLIM keys derive from the public dev master secret."""
    if not local_backend:
        return None
    from mycelium.slim import naming

    secret = _hub_slim_master_secret()
    if secret and secret != naming._DEV_MASTER_SECRET:
        return CheckResult(
            name="SLIM PSK (hub)",
            status="ok",
            message="Private slim.master_secret configured",
        )
    if not secret:
        return CheckResult(
            name="SLIM PSK (hub)",
            status="warning",
            message="No hub SLIM master secret in config.toml",
            details=[
                "Run: mycelium config apply  (generates [slim].master_secret)",
                "PSK gates native SLIM group join on the hub — spokes do not use it.",
            ],
        )
    return CheckResult(
        name="SLIM PSK (hub)",
        status="warning",
        message="Hub uses the public dev SLIM master secret",
        details=[
            "PSK gates native SLIM group join on the hub — spokes do not use it.",
            "Run: mycelium config apply  (generates a private [slim].master_secret)",
            "For spokes on a network, enable auth.enabled (HTTP JWT gate).",
        ],
    )


# Keys that should match between ~/.mycelium/.env and config.toml. Each entry
# is (env_key, config_accessor); config_accessor pulls the equivalent value
# out of a loaded MyceliumConfig. `mycelium config apply` regenerates .env
# from config.toml, so config.toml is the source of truth on drift.
_SHARED_CONFIG_KEYS: list[tuple[str, Callable[..., str]]] = [
    ("LLM_MODEL", lambda cfg: (cfg.llm.model or "") if getattr(cfg, "llm", None) else ""),
]


def _check_config_file_drift(*, local_backend: bool = True) -> CheckResult:
    """Compare every shared key between ``~/.mycelium/.env`` and ``config.toml``.

    Catches the common "I edited one file and forgot the other" failure mode.
    The sibling runtime-drift check covers "I edited both files but forgot
    to restart the container"; this one only looks at disk, not runtime.

    When *local_backend* is False (spoke mode) the Docker-port comparison is
    skipped because there is no local container to map the port for.
    """
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    if not env_path.exists() or not config_path.exists():
        return CheckResult(
            name="Config file drift",
            status="ok",
            message="Skipped (missing files)",
        )

    from dotenv import dotenv_values

    from mycelium.config import MyceliumConfig

    vals = dotenv_values(env_path)

    try:
        cfg = MyceliumConfig.load(config_path)
    except Exception:
        return CheckResult(
            name="Config file drift",
            status="warning",
            message="Cannot parse config.toml",
        )

    mismatches: list[str] = []

    # Text keys: only flag when both sides have a value. A missing value on
    # one side isn't drift, it's an opt-out.
    for env_key, get_toml in _SHARED_CONFIG_KEYS:
        try:
            toml_val = get_toml(cfg)
        except Exception:
            toml_val = ""
        env_val = vals.get(env_key, "") or ""
        if env_val and toml_val and env_val != toml_val:
            mismatches.append(f"{env_key}")
            mismatches.append(f"  .env:         {env_val}")
            mismatches.append(f"  config.toml:  {toml_val}")

    # Port special case: compare .env port to the port parsed from config
    # URL.  Only meaningful on hub nodes where Docker maps the port locally.
    if local_backend:
        env_port = vals.get("MYCELIUM_BACKEND_PORT", "")
        try:
            parsed = urlparse(cfg.server.api_url or "")
            config_port = str(parsed.port) if parsed.port else ""
        except Exception:
            config_port = ""

        if env_port and config_port and env_port != config_port:
            mismatches.append("Backend port")
            mismatches.append(f"  .env:         MYCELIUM_BACKEND_PORT={env_port}")
            mismatches.append(f"  config.toml:  api_url port={config_port}")

    if mismatches:
        return CheckResult(
            name="Config file drift",
            status="warning",
            message="Values differ between .env and config.toml",
            details=mismatches + ["fix: mycelium config apply  (overwrites .env from config.toml)"],
        )

    return CheckResult(
        name="Config file drift",
        status="ok",
        message=".env and config.toml aligned",
    )


def _check_runtime_config_drift() -> CheckResult:
    """Compare backend runtime values against the on-disk ``.env``.

    Catches "I edited the files but didn't restart the backend"; in that
    state ``mycelium doctor`` may happily green-light LLM connectivity
    because the container is still running the old-but-working config, so
    the user never notices their config changes took no effect.

    Runtime values come from ``/health?check_llm=true``. Key hints are
    compared by last 4 characters (the format the backend returns).
    """
    env_path = Path.home() / ".mycelium" / ".env"
    if not env_path.exists():
        return CheckResult(
            name="Runtime config drift",
            status="ok",
            message="Skipped (no .env)",
        )

    from dotenv import dotenv_values

    vals = dotenv_values(env_path)
    env_model = (vals.get("LLM_MODEL", "") or "").strip()
    env_key = (vals.get("LLM_API_KEY", "") or "").strip()
    env_key_tail = env_key[-4:] if len(env_key) >= 4 else ""

    from mycelium.config import MyceliumConfig

    try:
        cfg = MyceliumConfig.load()
        api_url = cfg.server.api_url or "http://localhost:8000"
    except Exception:
        return CheckResult(
            name="Runtime config drift",
            status="ok",
            message="Skipped (cannot load config)",
        )

    try:
        import httpx

        resp = httpx.get(
            f"{api_url}/health",
            params={"check_llm": "true"},
            timeout=5,
        )
    except Exception:
        return CheckResult(
            name="Runtime config drift",
            status="ok",
            message="Skipped (backend unreachable)",
        )

    if resp.status_code >= 500:
        return CheckResult(
            name="Runtime config drift",
            status="ok",
            message=f"Skipped (backend HTTP {resp.status_code})",
        )

    try:
        llm = resp.json().get("llm") or {}
    except Exception:
        return CheckResult(
            name="Runtime config drift",
            status="ok",
            message="Skipped (backend returned non-JSON)",
        )

    runtime_model = (llm.get("model", "") or "").strip()
    runtime_key_hint = (llm.get("key_hint", "") or "").strip()
    runtime_key_tail = runtime_key_hint[-4:] if len(runtime_key_hint) >= 4 else ""

    mismatches: list[str] = []
    if env_model and runtime_model and env_model != runtime_model:
        mismatches.append("LLM_MODEL")
        mismatches.append(f"  .env:      {env_model}")
        mismatches.append(f"  backend:   {runtime_model}")

    if env_key_tail and runtime_key_tail and env_key_tail != runtime_key_tail:
        mismatches.append("LLM_API_KEY")
        mismatches.append(f"  .env ends …{env_key_tail}")
        mismatches.append(f"  backend ends …{runtime_key_tail}")

    if mismatches:
        return CheckResult(
            name="Runtime config drift",
            status="warning",
            message="Backend running with stale env",
            details=mismatches
            + ["fix: mycelium up  (recreate the backend container with current .env)"],
        )

    return CheckResult(
        name="Runtime config drift",
        status="ok",
        message="Backend env matches .env",
    )


# ── Cursor adapter checks ─────────────────────────────────────────────────────
#
# Gate every check on whether the user has opted into the cursor adapter (via
# ``mycelium adapter add cursor``).  A fresh mycelium install that has never
# touched Cursor (and a user who happens to have ``cursor-agent`` on PATH for
# unrelated reasons) should both see all cursor checks cleanly skipped.  We
# surface health only after the user has explicitly asked for the adapter.


def _cursor_adapter_registered() -> bool:
    """True if the user has run ``mycelium adapter add cursor`` at least once."""
    from mycelium.config import MyceliumConfig

    try:
        cfg = MyceliumConfig.load()
    except Exception:
        return False
    return "cursor" in (cfg.adapters or {})


def _check_cursor_agent_binary() -> CheckResult:
    """Verify ``cursor-agent`` is reachable on PATH for a resident Cursor session.

    A cursor agent participates as the user's own Cursor session (kept woken with
    ``mycelium await --loop``); ``cursor-agent`` must be installed for that session
    to run. Surfacing this early avoids the "I set up a cursor agent and nothing
    happened" debugging spiral.
    """
    if not _cursor_adapter_registered():
        return CheckResult(
            name="cursor-agent binary",
            status="ok",
            message="cursor adapter not registered (skipped)",
        )

    import shutil

    binary = shutil.which("cursor-agent")
    if binary is None:
        return CheckResult(
            name="cursor-agent binary",
            status="error",
            message="cursor-agent not on PATH; mentions will fail",
            details=[
                "install Cursor + the cursor CLI from https://cursor.com,",
                "then run `cursor-agent login` to authenticate this host.",
            ],
        )
    return CheckResult(
        name="cursor-agent binary",
        status="ok",
        message=f"installed at {binary}",
    )


def _check_cursor_login() -> CheckResult:
    """Verify ``cursor-agent`` is authenticated so a resident Cursor session can run.

    ``cursor-agent`` persists its session at ``~/.config/cursor/auth.json``
    (top-level ``accessToken`` / ``refreshToken``): that's the file
    ``cursor-agent`` itself reads on startup. Verified empirically on
    2026.05 builds: moving that file aside reproduces the
    ``Authentication required.`` error path; nothing else does. The
    older ``~/.cursor/cli-config.json`` ``preferences.tokenInfo`` schema
    is gone in current builds, and ``cli-config.json`` ``authInfo``
    (email/displayName) is a *biographical* breadcrumb that survives
    logout, so we deliberately do NOT consider it a "logged in"
    signal. Doctor must report what ``cursor-agent`` will actually do at
    spawn time, not what the user ever did.

    The spawn helper still surfaces a friendly error at first-mention
    time, but doctor catches it during setup. Returns ``ok`` only when
    auth.json carries a non-empty ``accessToken``.
    """
    if not _cursor_adapter_registered():
        return CheckResult(
            name="cursor-agent login",
            status="ok",
            message="cursor adapter not registered (skipped)",
        )

    import json

    auth_path = Path.home() / ".config" / "cursor" / "auth.json"

    if not auth_path.exists():
        return CheckResult(
            name="cursor-agent login",
            status="warning",
            message="cursor-agent has not been run on this host",
            details=[
                f"expected: {auth_path}",
                "fix: run `cursor-agent login` and complete the browser flow",
            ],
        )

    try:
        auth_data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 (malformed JSON shouldn't crash doctor)
        return CheckResult(
            name="cursor-agent login",
            status="warning",
            message=f"auth.json could not be parsed: {exc}",
            details=[
                f"checked: {auth_path}",
                "fix: run `cursor-agent login` to refresh credentials",
            ],
        )

    if not isinstance(auth_data, dict) or not auth_data.get("accessToken"):
        return CheckResult(
            name="cursor-agent login",
            status="warning",
            message="cursor-agent is not authenticated",
            details=[
                f"checked: {auth_path}",
                "fix: run `cursor-agent login` and complete the browser flow",
            ],
        )

    return CheckResult(
        name="cursor-agent login",
        status="ok",
        message="authenticated",
    )


def _check_cursor_workspace_assets() -> CheckResult:
    """Verify each registered cursor agent's workspace has the mycelium assets.

    ``mycelium agent create --adapter cursor`` drops
    ``.cursor/rules/mycelium.mdc`` + the mycelium-marked block of
    ``AGENTS.md`` into the agent's cwd. A user manually wiping ``.cursor``
    (or moving the workspace directory) leaves the manifest registered but
    the spawned ``cursor-agent`` blind to mycelium context. Doctor catches
    that drift.
    """
    if not _cursor_adapter_registered():
        return CheckResult(
            name="cursor workspace",
            status="ok",
            message="cursor adapter not registered (skipped)",
        )

    # Walk every room's agent manifests; collect (handle, cwd) tuples for
    # cursor-family agents. We deliberately read the manifest files directly
    # rather than hitting the backend so doctor stays functional on spokes
    # whose backend is down.
    from mycelium.commands.agent import _load_manifest

    rooms_dir = Path.home() / ".mycelium" / "rooms"
    if not rooms_dir.exists():
        return CheckResult(
            name="cursor workspace",
            status="ok",
            message="no rooms on disk (skipped)",
        )

    cursor_agents: list[tuple[str, str, Path]] = []
    for room_dir in rooms_dir.iterdir():
        if not room_dir.is_dir():
            continue
        agents_dir = room_dir / "agents"
        if not agents_dir.exists():
            continue
        for manifest_file in agents_dir.glob("*.md"):
            try:
                manifest = _load_manifest(room_dir.name, manifest_file.stem)
            except Exception:
                continue
            if manifest is None or manifest.adapter != "cursor" or not manifest.cwd:
                continue
            cursor_agents.append((manifest.handle, room_dir.name, Path(manifest.cwd).expanduser()))

    if not cursor_agents:
        return CheckResult(
            name="cursor workspace",
            status="ok",
            message="no cursor agents registered (skipped)",
        )

    missing: list[str] = []
    for handle, room, cwd in cursor_agents:
        rule = cwd / ".cursor" / "rules" / "mycelium.mdc"
        agents_md = cwd / "AGENTS.md"
        if not cwd.is_dir():
            missing.append(f"  @{handle} ({room}): cwd {cwd} does not exist")
            continue
        if not rule.exists():
            missing.append(f"  @{handle} ({room}): missing {rule}")
        if not agents_md.exists():
            missing.append(f"  @{handle} ({room}): missing {agents_md}")

    if missing:
        return CheckResult(
            name="cursor workspace",
            status="warning",
            message=f"{len(missing)} drift item(s) across {len(cursor_agents)} agent(s)",
            details=[*missing, "fix: `mycelium agent rm <handle> && mycelium agent create ...`"],
        )

    return CheckResult(
        name="cursor workspace",
        status="ok",
        message=f"all {len(cursor_agents)} cursor agent(s) have current workspace assets",
    )


@doc_ref(
    usage="mycelium doctor [--fix] [--json] [--mode auto|hub|spoke]",
    desc="Diagnose and fix common configuration issues (workspace sync, LLM, containers).",
    group="setup",
)
def doctor(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Auto-fix all fixable issues without prompting"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="Check scope: auto (detect from api_url), hub (all checks), or spoke (skip local-only checks)",
    ),
) -> None:
    """
    Diagnose and fix common Mycelium configuration issues.

    Checks config files, LLM setup, Docker containers, backend connectivity,
    workspace ID sync, and config consistency. Offers to fix issues it finds.

    Single-device installs (the default) run the backend locally and
    exercise all checks. In the optional hub-and-spoke deployment mode
    spoke nodes talk to a remote backend and don't run Docker containers
    locally. When --mode is 'auto' (the default), doctor detects spoke
    mode from server.api_url: if it points to a non-local host the
    Docker, runtime-drift, and port-drift checks are skipped automatically.

    \b
    Examples:
        mycelium doctor              # interactive; auto-detects hub vs spoke
        mycelium doctor --fix        # auto-fix all fixable issues
        mycelium doctor --mode spoke # force spoke mode (skip local-only checks)
        mycelium doctor --mode hub   # force hub mode (run all checks)
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        # ── Topology detection ────────────────────────────────────────
        from mycelium.config import MyceliumConfig

        try:
            config = MyceliumConfig.load()
            api_url = config.server.api_url
        except Exception:
            api_url = "http://localhost:8000"

        if mode == "auto":
            local = _is_local_backend(api_url)
        elif mode == "hub":
            local = True
        elif mode == "spoke":
            local = False
        else:
            typer.secho(f"Unknown --mode '{mode}'. Use auto, hub, or spoke.", fg=typer.colors.RED)
            raise typer.Exit(1)

        detected_mode = "hub" if local else "spoke"

        # ── Build check list ──────────────────────────────────────────
        # Checks are grouped into sections for display but we collect
        # them once so the JSON output and verdict have a single source
        # of truth.  Spoke nodes skip checks that only apply when the
        # backend runs locally (Docker containers, runtime config drift,
        # .env port vs Docker port).
        config_checks: list[CheckResult] = [
            _check_config_files(),
            _check_mycelium_dir_ownership(),
            _check_config_file_drift(local_backend=local),
        ]
        if local:
            config_checks.append(_check_runtime_config_drift())

        service_checks: list[CheckResult] = []
        if local:
            service_checks.append(_check_docker_containers())
        service_checks.append(_check_backend_reachable(local_backend=local))
        service_checks.append(_check_http_auth_gate(api_url=api_url))
        if local:
            psk_check = _check_hub_slim_psk(local_backend=local)
            if psk_check is not None:
                service_checks.append(psk_check)
        service_checks.append(_check_llm_connectivity())
        if local:
            service_checks.append(_check_mediator_pi_binary())

        sections: list[tuple[str, list[CheckResult]]] = [
            ("Configuration", config_checks),
            ("Services", service_checks),
            (
                "Adapters",
                [
                    _check_cursor_agent_binary(),
                    _check_cursor_login(),
                    _check_cursor_workspace_assets(),
                ],
            ),
        ]
        results = [r for _, checks in sections for r in checks]

        if json_output:
            import json

            output = {
                "mode": detected_mode,
                "api_url": api_url,
                "checks": [
                    {
                        "name": r.name,
                        "status": r.status,
                        "message": r.message,
                        "details": r.details,
                        "fixable": r.fix_fn is not None,
                    }
                    for r in results
                ],
            }
            typer.echo(json.dumps(output, indent=2))
            return

        parsed_host = urlparse(api_url).hostname or api_url
        parsed_port = urlparse(api_url).port
        backend_label = f"{parsed_host}:{parsed_port}" if parsed_port else parsed_host
        subtitle = f"{detected_mode}, backend at {backend_label}" if not local else None
        print_title("Mycelium Doctor", subtitle=subtitle)
        for title, checks in sections:
            print_section(title)
            for result in checks:
                print_check(result)

        # Summary
        issues = [r for r in results if r.status not in ("ok", "info")]
        fixable = [r for r in issues if r.fix_fn is not None]
        errors = [
            r
            for r in results
            if r.status == "error" or r.status in ("missing_extras", "bad_model", "unreachable")
        ]

        # Warnings verdict as yellow ~, errors as red ✗. A lone warning
        # shouldn't render as a hard failure.
        if not issues:
            print_verdict("ok", "All checks passed.")
        else:
            summary = f"{len(issues)} issue(s) found" + (
                f", {len(fixable)} auto-fixable." if fixable else "."
            )
            print_verdict("error" if errors else "warning", summary)

        # Offer to fix
        if fixable:
            typer.echo("")
            for result in fixable:
                if fix:
                    typer.echo(f"  Fixing: {result.fix_label}")
                    assert result.fix_fn is not None
                    result.fix_fn()
                else:
                    try:
                        answer = input(f"  {result.fix_label}? [Y/n] ").strip()
                    except (EOFError, KeyboardInterrupt):
                        typer.echo("\n  Skipped.")
                        continue
                    if answer.lower() in ("y", "yes", ""):
                        assert result.fix_fn is not None
                        result.fix_fn()
                    else:
                        typer.echo("  Skipped.")

        # Exit code: hard errors (and backend-classified hard failures) are
        # fatal so CI/scripts can rely on a non-zero exit. Warnings don't
        # flip the exit code; they're nudges, not failures.
        if errors:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
