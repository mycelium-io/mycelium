# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Doctor command — diagnose and fix common Mycelium configuration issues.

Checks:
  1. Config files exist (~/.mycelium/.env, config.toml)
  2. Config file drift — every shared key aligned between .env and config.toml
  3. Runtime config drift — backend container env matches .env on disk
  4. Docker containers running and healthy
  5. Backend API reachable
  6. LLM connectivity (real completion probe via backend)
  7. Workspace ID in sync (CFN mgmt plane vs .env vs config.toml)
  8. Room MAS IDs present (CFN-enabled installs)
  9. OpenClaw adapter health (plugin, channel config, agent sandbox)

Single-device installs (the default) run the backend locally and exercise
all checks. In the optional hub-and-spoke deployment mode, spoke nodes
connect to a remote backend and don't run local Docker containers. When
``server.api_url`` points at a non-local host the doctor auto-detects
**spoke mode** and skips checks that only apply when the backend is
local (Docker containers, runtime config drift, .env port vs Docker
port, localhost CFN mgmt plane).  An explicit ``--mode hub|spoke`` flag
overrides the auto-detection.
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
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    missing = []
    if not env_path.exists():
        missing.append(".env")
    if not config_path.exists():
        missing.append("config.toml")

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


def _check_llm_connectivity() -> CheckResult:
    """Probe the backend's LLM with a real ``litellm.completion(max_tokens=1)`` call.

    Exercises the same code path as inference and surfaces problems that only
    show up at first use — missing provider SDK extras (e.g. boto3 for Bedrock),
    bad model strings, and auth failures at the actual endpoint (not just the
    free model-list endpoint).

    Runs via ``GET /health?check_llm=true&llm_probe=completion`` so the probe
    executes inside the backend container, which is where LLM calls will
    actually run in production.
    """
    # Skip entirely if the LLM isn't configured at all — _check_llm_config
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
            message=f"{model} — completion probe succeeded",
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
            message=f"{model} — missing provider SDK in backend",
            details=details,
        )
    if status == "bad_model":
        return CheckResult(
            name="LLM connectivity",
            status="error",
            message=f"{model} — invalid model string",
            details=details,
        )
    if status == "auth_error":
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message=f"{model} — authentication failed",
            details=details,
        )
    if status == "unreachable":
        return CheckResult(
            name="LLM connectivity",
            status="warning",
            message=f"{model} — provider unreachable",
            details=details,
        )
    if status == "unchecked":
        return CheckResult(
            name="LLM connectivity",
            status="ok",
            message=f"{model} — probe unsupported for this provider",
            details=details,
        )
    # error | unknown
    return CheckResult(
        name="LLM connectivity",
        status="error",
        message=f"{model} — {status}",
        details=details,
    )


def _check_docker_containers() -> CheckResult:
    """Check that expected containers are running and healthy."""
    expected = ["mycelium-db", "mycelium-backend"]

    # Check if CFN is enabled
    env_path = Path.home() / ".mycelium" / ".env"
    if env_path.exists():
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        if vals.get("CFN_MGMT_URL", ""):
            expected += ["ioc-cfn-mgmt-plane-svc", "ioc-cognition-fabric-node-svc"]

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


def _check_workspace_id(*, local_backend: bool = True) -> CheckResult:
    """Check workspace_id consistency between .env, config.toml, and CFN mgmt plane.

    When *local_backend* is False (spoke mode) the localhost CFN management
    plane check is skipped — the mgmt plane runs on the hub, not here.
    """
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    # Read from .env
    env_ws = ""
    cfn_enabled = False
    if env_path.exists():
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        env_ws = vals.get("WORKSPACE_ID", "")
        cfn_enabled = bool(vals.get("CFN_MGMT_URL", ""))

    # Read from config.toml
    config_ws = ""
    if config_path.exists():
        from mycelium.config import MyceliumConfig

        try:
            cfg = MyceliumConfig.load(config_path)
            config_ws = cfg.server.workspace_id or ""
        except Exception:
            pass

    if not env_ws and not config_ws:
        if not local_backend:
            return CheckResult(
                name="Workspace ID",
                status="ok",
                message="Not set (optional for spoke nodes)",
            )
        return CheckResult(
            name="Workspace ID",
            status="warning",
            message="Not configured",
            details=["Run: mycelium install --force"],
        )

    # If CFN is enabled *and* we're on the hub, check against the local
    # mgmt plane.  Spoke nodes don't run the mgmt plane locally.
    cfn_ws = None
    if cfn_enabled and local_backend:
        from mycelium.commands.install import _get_cfn_workspace_id

        cfn_ws = _get_cfn_workspace_id("http://localhost:9000")

    details: list[str] = []
    mismatches: list[str] = []

    if env_ws:
        details.append(f".env: {env_ws}")
    if config_ws and config_ws != env_ws:
        details.append(f"config.toml: {config_ws}")
        mismatches.append("config.toml")

    if cfn_ws is not None:
        details.append(f"CFN mgmt plane: {cfn_ws}")
        if cfn_ws != env_ws:
            mismatches.append("CFN mgmt plane")
    elif cfn_enabled and local_backend:
        details.append("CFN mgmt plane: unreachable")

    if mismatches:
        # Build a fix function that re-syncs from CFN (or from .env if no CFN)
        source_ws = cfn_ws if cfn_ws else env_ws
        fix_fn = (
            _make_workspace_fix(source_ws, env_path, config_path, cfn_enabled)
            if source_ws
            else None
        )

        return CheckResult(
            name="Workspace ID",
            status="error",
            message=f"Mismatch — {', '.join(mismatches)} differ from .env",
            details=details,
            fix_label=f"Sync all to {source_ws}",
            fix_fn=fix_fn,
        )

    # All agree (or only one source exists)
    display_ws = env_ws or config_ws
    return CheckResult(
        name="Workspace ID",
        status="ok",
        message=display_ws,
        details=details if len(details) > 1 else [],
    )


def _make_workspace_fix(
    target_ws: str,
    env_path: Path,
    config_path: Path,
    cfn_enabled: bool,
) -> Callable[[], None]:
    """Return a closure that patches workspace_id in .env and config.toml."""

    def _fix() -> None:
        from mycelium.commands.install import (
            _get_compose_path,
            _patch_env_vars,
            _restart_backend,
            _write_mycelium_config,
        )

        # Patch .env
        typer.echo(f"    Patching ~/.mycelium/.env WORKSPACE_ID={target_ws}")
        _patch_env_vars(env_path, {"WORKSPACE_ID": target_ws})

        # Patch config.toml
        from mycelium.config import MyceliumConfig

        try:
            cfg = MyceliumConfig.load(config_path) if config_path.exists() else MyceliumConfig()
        except Exception:
            cfg = MyceliumConfig()

        api_url = cfg.server.api_url or "http://localhost:8000"
        mas_id = cfg.server.mas_id or ""

        typer.echo(f"    Patching ~/.mycelium/config.toml server.workspace_id={target_ws}")
        _write_mycelium_config(api_url, target_ws, mas_id)

        # Restart backend so it picks up the new WORKSPACE_ID
        typer.echo("    Restarting backend...")
        try:
            compose_path = _get_compose_path()
            profiles = ["cfn"] if cfn_enabled else []
            _restart_backend(compose_path, env_path, profiles, api_url)
            typer.secho("  ✓ Workspace ID synced", fg=typer.colors.GREEN)
        except Exception as exc:
            typer.secho(f"  ⚠  Backend restart failed: {exc}", fg=typer.colors.YELLOW)
            typer.echo("    Run: mycelium up")

    return _fix


# Keys that should match between ~/.mycelium/.env and config.toml. Each entry
# is (env_key, config_accessor) — config_accessor pulls the equivalent value
# out of a loaded MyceliumConfig. `mycelium config apply` regenerates .env
# from config.toml, so config.toml is the source of truth on drift.
_SHARED_CONFIG_KEYS: list[tuple[str, Callable[..., str]]] = [
    ("LLM_MODEL", lambda cfg: (cfg.llm.model or "") if getattr(cfg, "llm", None) else ""),
    ("WORKSPACE_ID", lambda cfg: cfg.server.workspace_id or ""),
    ("MAS_ID", lambda cfg: cfg.server.mas_id or ""),
]


def _check_config_file_drift(*, local_backend: bool = True) -> CheckResult:
    """Compare every shared key between ``~/.mycelium/.env`` and ``config.toml``.

    Catches the common "I edited one file and forgot the other" failure mode.
    The sibling runtime-drift check covers "I edited both files but forgot
    to restart the container" — this one only looks at disk, not runtime.

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

    # Text keys — only flag when both sides have a value. A missing value on
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

    # Port special case — compare .env port to the port parsed from config
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

    Catches "I edited the files but didn't restart the backend" — in that
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


def _check_room_mas_ids() -> CheckResult:
    """Check that all rooms have a MAS ID (CFN-enabled installs only)."""
    env_path = Path.home() / ".mycelium" / ".env"
    if not env_path.exists():
        return CheckResult(name="Room MAS IDs", status="ok", message="Skipped (no .env)")

    from dotenv import dotenv_values

    vals = dotenv_values(env_path)
    if not vals.get("CFN_MGMT_URL"):
        return CheckResult(name="Room MAS IDs", status="ok", message="Skipped (CFN not enabled)")

    from mycelium.config import MyceliumConfig

    try:
        cfg = MyceliumConfig.load()
        api_url = cfg.server.api_url or "http://localhost:8000"
    except Exception:
        api_url = "http://localhost:8000"

    try:
        import httpx

        with httpx.Client(base_url=api_url, timeout=5) as client:
            resp = client.get("/rooms")
            resp.raise_for_status()
            rooms = resp.json()
    except Exception:
        return CheckResult(
            name="Room MAS IDs", status="ok", message="Skipped (backend unreachable)"
        )

    # Session sub-rooms (name contains ":session:") don't need MAS IDs
    top_level = [r for r in rooms if ":session:" not in r["name"]]
    missing = [r["name"] for r in top_level if not r.get("mas_id")]
    if not missing:
        return CheckResult(
            name="Room MAS IDs",
            status="ok",
            message=f"All {len(top_level)} room(s) have MAS IDs",
        )

    return CheckResult(
        name="Room MAS IDs",
        status="warning",
        message=f"{len(missing)} room(s) missing MAS ID",
        details=[f"  {name}" for name in missing]
        + ["Fix: run 'mycelium doctor --fix' after workspace ID is synced"],
    )


# ── OpenClaw adapter checks ───────────────────────────────────────────────────
#
# All three openclaw checks are gated on whether the user has opted into the
# mycelium OpenClaw adapter (by running `mycelium adapter add openclaw`).  We
# read that from config.adapters in ~/.mycelium/config.toml.  A fresh mycelium
# install that has never touched OpenClaw, and a user who happens to have
# OpenClaw installed for unrelated reasons, should both see all three checks
# cleanly skipped — doctor should only nag about adapter health once the user
# has explicitly asked for the adapter.


def _openclaw_adapter_registered() -> bool:
    """True if the user has run `mycelium adapter add openclaw` at least once."""
    from mycelium.config import MyceliumConfig

    try:
        cfg = MyceliumConfig.load()
    except Exception:
        return False
    return "openclaw" in (cfg.adapters or {})


def _check_openclaw_mycelium_plugin() -> CheckResult:
    """Verify the `mycelium` plugin is installed, registers the mycelium-room channel,
    and has the post-refactor source layout.  Catches three real failure modes
    previously only surfaced at gateway startup or at first message routing:

    1. Manifest missing ``kind: channel`` / ``channels: [mycelium-room]`` — gateway
       refuses to start with "unknown channel id: mycelium-room" on any config
       referencing the channel.
    2. Pre-refactor layout (no ``src/channel/route.ts``) — a user who installed
       before the channel logic was extracted still has the monolithic file and
       will miss the unit-tested routing path entirely.
    3. Stale ``instructions.ts`` from before the ``message`` → ``negotiate`` rename —
       agents read the stale text on every turn and try to run commands that no
       longer exist.
    """
    import json

    if not _openclaw_adapter_registered():
        return CheckResult(
            name="openclaw plugin",
            status="ok",
            message="openclaw adapter not registered — skipped",
        )

    plugin_dir = Path.home() / ".openclaw" / "extensions" / "mycelium"
    manifest = plugin_dir / "openclaw.plugin.json"
    index = plugin_dir / "index.ts"
    route_file = plugin_dir / "src" / "channel" / "route.ts"
    instructions_file = plugin_dir / "src" / "instructions.ts"

    if not manifest.exists():
        return CheckResult(
            name="openclaw plugin",
            status="warning",
            message="adapter registered but plugin not found",
            details=[
                f"expected: {plugin_dir}",
                "fix: run `mycelium adapter add openclaw --reinstall`",
            ],
        )

    if not index.exists():
        return CheckResult(
            name="openclaw plugin",
            status="error",
            message="manifest present but index.ts missing — corrupt install",
            details=["fix: run `mycelium adapter add openclaw --reinstall`"],
        )

    # 1. Channel registration in manifest
    try:
        manifest_data = json.loads(manifest.read_text())
    except Exception as exc:
        return CheckResult(
            name="openclaw plugin",
            status="error",
            message=f"manifest is not valid JSON: {exc}",
            details=["fix: run `mycelium adapter add openclaw --reinstall`"],
        )

    channels = manifest_data.get("channels") or []
    if manifest_data.get("kind") != "channel" or "mycelium-room" not in channels:
        return CheckResult(
            name="openclaw plugin",
            status="error",
            message="manifest does not register the mycelium-room channel",
            details=[
                f"found kind={manifest_data.get('kind')!r} channels={channels}",
                'expected kind="channel" channels=["mycelium-room"]',
                "symptom: gateway refuses to start with 'unknown channel id: mycelium-room'",
                "fix: run `mycelium adapter add openclaw --reinstall`",
            ],
        )

    # 2. Post-refactor layout
    if not route_file.exists():
        return CheckResult(
            name="openclaw plugin",
            status="warning",
            message="pre-refactor plugin layout — missing src/channel/route.ts",
            details=[
                "the channel routing logic was extracted into a dedicated module",
                "fix: run `mycelium adapter add openclaw --reinstall`",
            ],
        )

    # 3. Staleness from the message → negotiate rename
    if instructions_file.exists():
        try:
            instructions_text = instructions_file.read_text()
        except Exception:
            instructions_text = ""
        if "mycelium message " in instructions_text:
            return CheckResult(
                name="openclaw plugin",
                status="warning",
                message="installed instructions.ts references `mycelium message` (stale)",
                details=[
                    "the `message` command group was renamed to `negotiate`",
                    "agents reading this on wake will try commands that no longer exist",
                    "fix: run `mycelium adapter add openclaw --reinstall`",
                ],
            )

    return CheckResult(
        name="openclaw plugin",
        status="ok",
        message=f"installed at {plugin_dir} (channel registered, layout current)",
    )


def _check_openclaw_channel_config() -> CheckResult:
    """Verify channels.mycelium-room is configured correctly in openclaw.json."""
    import json

    if not _openclaw_adapter_registered():
        return CheckResult(
            name="channel config",
            status="ok",
            message="openclaw adapter not registered — skipped",
        )

    openclaw_json = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_json.exists():
        return CheckResult(
            name="channel config",
            status="ok",
            message="openclaw.json not found — skipped",
        )

    try:
        with openclaw_json.open() as f:
            oc = json.load(f)
    except Exception as exc:
        return CheckResult(
            name="channel config",
            status="error",
            message=f"could not parse openclaw.json: {exc}",
        )

    channel = (oc.get("channels") or {}).get("mycelium-room")
    if not channel:
        return CheckResult(
            name="channel config",
            status="warning",
            message="channels.mycelium-room not configured",
            details=[
                "the plugin will run in session-only mode (no addressed messaging)",
                "fix: add channels.mycelium-room with backendUrl, room, agents, requireMention",
            ],
        )

    if channel.get("enabled") is False:
        return CheckResult(
            name="channel config",
            status="warning",
            message="channels.mycelium-room present but disabled",
        )

    missing = [k for k in ("backendUrl", "room", "agents") if not channel.get(k)]
    if missing:
        return CheckResult(
            name="channel config",
            status="error",
            message=f"missing required fields: {', '.join(missing)}",
            details=["fix: set backendUrl, room, and agents in channels.mycelium-room"],
        )

    # Check backendUrl matches mycelium config.toml's server.api_url
    try:
        import tomllib

        mycelium_toml = Path.home() / ".mycelium" / "config.toml"
        if mycelium_toml.exists():
            with mycelium_toml.open("rb") as f:
                mcfg = tomllib.load(f)
            expected = (mcfg.get("server") or {}).get("api_url", "").rstrip("/")
            actual = str(channel.get("backendUrl", "")).rstrip("/")
            if expected and actual and expected != actual:
                return CheckResult(
                    name="channel config",
                    status="error",
                    message="backendUrl doesn't match mycelium config.toml",
                    details=[
                        f"openclaw.json:     {actual}",
                        f"mycelium/config:   {expected}",
                        "fix: update channels.mycelium-room.backendUrl to match",
                    ],
                )
    except Exception:
        pass  # non-fatal

    agents = channel.get("agents") or []
    require_mention = channel.get("requireMention", True)
    return CheckResult(
        name="channel config",
        status="ok",
        message=f"room={channel.get('room')} agents={len(agents)} requireMention={require_mention}",
    )


def _check_openclaw_agent_sandbox() -> CheckResult:
    """Warn about agents whose sandbox mode blocks the mycelium CLI."""
    import json

    if not _openclaw_adapter_registered():
        return CheckResult(
            name="agent sandbox",
            status="ok",
            message="openclaw adapter not registered — skipped",
        )

    openclaw_json = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_json.exists():
        return CheckResult(
            name="agent sandbox",
            status="ok",
            message="openclaw.json not found — skipped",
        )

    try:
        with openclaw_json.open() as f:
            oc = json.load(f)
    except Exception as exc:
        return CheckResult(
            name="agent sandbox",
            status="error",
            message=f"could not parse openclaw.json: {exc}",
        )

    channel = (oc.get("channels") or {}).get("mycelium-room") or {}
    channel_agents = set(channel.get("agents") or [])
    if not channel_agents:
        return CheckResult(
            name="agent sandbox",
            status="ok",
            message="no channel agents configured — skipped",
        )

    default_sandbox = (((oc.get("agents") or {}).get("defaults") or {}).get("sandbox") or {}).get(
        "mode", "all"
    )

    sandboxed: list[str] = []
    for agent in (oc.get("agents") or {}).get("list", []):
        agent_id = agent.get("id", "")
        if agent_id not in channel_agents:
            continue
        mode = (agent.get("sandbox") or {}).get("mode") or default_sandbox
        if mode != "off":
            sandboxed.append(f"{agent_id} (mode={mode})")

    if sandboxed:
        return CheckResult(
            name="agent sandbox",
            status="warning",
            message=f"{len(sandboxed)} channel agent(s) are sandboxed — mycelium CLI invisible",
            details=[
                *sandboxed,
                "sandboxed agents cannot execute `mycelium session join`, `message propose`,",
                "or `message respond` because the mycelium binary isn't in their sandbox PATH.",
                "fix: set sandbox.mode = 'off' in openclaw.json for each agent, restart gateway",
            ],
        )

    return CheckResult(
        name="agent sandbox",
        status="ok",
        message=f"all {len(channel_agents)} channel agent(s) have sandbox=off",
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
    mode from server.api_url — if it points to a non-local host the
    Docker, runtime-drift, and port-drift checks are skipped automatically.

    \b
    Examples:
        mycelium doctor              # interactive — auto-detects hub vs spoke
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
            _check_config_file_drift(local_backend=local),
        ]
        if local:
            config_checks.append(_check_runtime_config_drift())

        service_checks: list[CheckResult] = []
        if local:
            service_checks.append(_check_docker_containers())
        service_checks.append(_check_backend_reachable(local_backend=local))
        service_checks.append(_check_llm_connectivity())

        sections: list[tuple[str, list[CheckResult]]] = [
            ("Configuration", config_checks),
            ("Services", service_checks),
            (
                "CFN",
                [
                    _check_workspace_id(local_backend=local),
                    _check_room_mas_ids(),
                ],
            ),
            (
                "Adapters",
                [
                    _check_openclaw_mycelium_plugin(),
                    _check_openclaw_channel_config(),
                    _check_openclaw_agent_sandbox(),
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
        subtitle = f"{detected_mode} — backend at {backend_label}" if not local else None
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
        # flip the exit code — they're nudges, not failures.
        if errors:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
