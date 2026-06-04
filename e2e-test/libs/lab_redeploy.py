"""Mycelium lab redeploy — wipe + rebuild the stack on real-hardware devices.

The Docker Compose CI environment is born fresh every run, but lab
hardware (oclw3/4/5) accumulates state across runs and needs an explicit
reset before testing a specific mycelium ref. This module is the moving
part of that reset.

Responsibilities
----------------

* **Moderate cleanup** — stop running containers, drop project volumes,
  but preserve ``~/.mycelium/{config.toml,.env}`` so LLM credentials
  survive (auth is the slow part for an interactive operator). The
  ``LabCleanupMode`` enum gives nuclear as an opt-in.
* **CLI reinstall** — uninstall the existing ``mycelium-cli`` tool and
  reinstall from any git ref (``main``, a tag, a SHA, or a custom
  branch) via ``uv tool install``. No PyPI release required.
* **Hub-only image build** — clone the mycelium source onto the hub,
  run the compose-dev override to build ``mycelium-backend:dev`` /
  ``mycelium-collector:dev`` from source, then ``mycelium install -n
  --force --no-ui`` bringing the stack up.
* **Spoke configuration** — point each spoke at the hub's backend URL
  via ``mycelium config set server.api_url`` and verify connectivity.

The module knows nothing about pyATS — it consumes anything
:mod:`libs.host_exec` can dispatch against. That keeps it usable from a
standalone CLI (``scripts/redeploy_lab.py``) as well as from a pyATS
``CommonSetup`` hook.

Safety
------

Cleanup operations target only Docker resources under the
``mycelium*`` / ``ioc-*`` naming convention. ``~/.mycelium`` is touched
in either *moderate* (data dirs wiped, config kept) or *nuclear*
(everything wiped) mode — never anywhere outside ``$HOME/.mycelium``.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from libs import host_exec

log = logging.getLogger(__name__)


# ── public types ───────────────────────────────────────────────────────


class LabCleanupMode(str, enum.Enum):
    """How aggressively to wipe the existing mycelium install."""

    #: Stop containers + drop project volumes, but keep ``~/.mycelium``
    #: config & credentials. Best for interactive iteration when you
    #: don't want to re-enter LLM keys every run.
    MODERATE = "moderate"

    #: Stop containers + drop volumes + ``rm -rf ~/.mycelium`` +
    #: ``uv tool uninstall mycelium-cli``. Slow but guarantees a clean
    #: slate; suitable for CI where secrets are injected from env.
    NUCLEAR = "nuclear"


@dataclass(frozen=True)
class LabRedeployConfig:
    """Configuration for a single ``redeploy_device`` invocation.

    ``ref`` is anything ``uv tool install git+…@<ref>`` understands —
    a branch, tag, or SHA. ``repo_url`` defaults to the public origin
    so the lab boxes don't need any local checkout.
    """

    ref: str = "main"
    repo_url: str = "https://github.com/mycelium-io/mycelium.git"
    cleanup_mode: LabCleanupMode = LabCleanupMode.MODERATE
    #: Where to clone the source on the hub before building images.
    source_dir: str = "/tmp/mycelium-redeploy"  # noqa: S108 - intentional; sibling-writable on shared hosts
    #: Skip ``mycelium install -n --force`` after bringing up the stack
    #: when the hub already has a config (moderate mode preserves it).
    skip_mycelium_install: bool = False
    #: Build the UI image too (slow). Off by default — scenarios don't
    #: need the UI and skipping it shaves ~3 min off the redeploy.
    include_ui: bool = False
    #: Extra env vars to set in ``~/.mycelium/.env`` on the hub after
    #: redeploy (e.g. LLM credentials). Sensitive values should be
    #: passed via env vars rather than command-line args; this dict is
    #: rendered to the env file but never logged.
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class DeviceResult:
    """Outcome of redeploying a single device.

    The ``logs`` field is a structured list of (phase, ok, detail)
    tuples so callers can pretty-print a progress report without
    re-parsing stdout.
    """

    device_name: str
    role: str
    success: bool
    error: str | None = None
    logs: list[tuple[str, bool, str]] = field(default_factory=list)


# ── role detection ─────────────────────────────────────────────────────


def _role(device: Any) -> str:
    """Resolve ``custom.role`` lowercased; default to ``spoke``."""
    custom = host_exec._custom_mapping(device)  # noqa: SLF001 - intentional reuse
    role = host_exec._resolve_env(custom.get("role"))  # noqa: SLF001
    return (role or "spoke").lower()


def _backend_url(device: Any) -> str | None:
    """Pull ``custom.mycelium_backend_url`` resolved through %ENV{}."""
    custom = host_exec._custom_mapping(device)  # noqa: SLF001
    return host_exec._resolve_env(custom.get("mycelium_backend_url"))  # noqa: SLF001


# ── shell helpers ──────────────────────────────────────────────────────


def _sh(
    device: Any,
    cmd: str,
    *,
    timeout: float = 60.0,
    check: bool = False,
) -> tuple[bool, str]:
    """Run a shell command on ``device``; return (ok, combined output)."""
    try:
        r = host_exec.execute(device, cmd, shell=True, timeout=timeout, check=check)
    except Exception as exc:  # noqa: BLE001 - host_exec is allowed to raise anything
        return False, f"dispatch failed: {exc}"
    ok = r.returncode == 0
    out = (r.stdout or "") + (r.stderr or "")
    return ok, out.strip()


def _record(result: DeviceResult, phase: str, ok: bool, detail: str = "") -> bool:
    """Append a phase outcome to ``result.logs`` and return ``ok``."""
    snippet = detail.splitlines()[-1][:200] if detail else ""
    result.logs.append((phase, ok, snippet))
    if ok:
        log.info("[%s/%s] ✓ %s%s", result.device_name, result.role, phase, f" — {snippet}" if snippet else "")
    else:
        log.warning("[%s/%s] ✗ %s — %s", result.device_name, result.role, phase, snippet)
    return ok


# ── cleanup ────────────────────────────────────────────────────────────


_COMPOSE_DOWN = (
    # Find the active compose project (where ``mycelium install`` rendered
    # the override) and bring it down with volumes. Fall back to the bare
    # vendored compose if no override file is present yet.
    "if [ -d $HOME/.mycelium/docker ]; then "
    "  cd $HOME/.mycelium/docker && "
    "  docker compose -f compose.yml -f compose-dev.yml --profile cfn down -v 2>/dev/null || "
    "  docker compose -f compose.yml --profile cfn down -v 2>/dev/null || true; "
    "fi; "
    # Belt-and-suspenders: kill any remaining mycelium-* containers in
    # case the project name diverged.
    "docker ps -aq --filter 'name=mycelium-' | xargs -r docker rm -f >/dev/null 2>&1 || true; "
    "docker ps -aq --filter 'name=ioc-' | xargs -r docker rm -f >/dev/null 2>&1 || true"
)

_DATA_DIRS_WIPE = (
    # Only touch known mycelium-managed paths under $HOME/.mycelium.
    "[ -d $HOME/.mycelium/rooms ] && rm -rf $HOME/.mycelium/rooms; "
    "[ -d $HOME/.mycelium/data ] && rm -rf $HOME/.mycelium/data; "
    "true"
)


def cleanup_device(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Run the cleanup pass appropriate for ``cfg.cleanup_mode``.

    Returns ``True`` on success; pushes phase entries into ``result``.
    """
    # Compose down works on both hub (the real stack) and spokes (no-op).
    ok, out = _sh(device, _COMPOSE_DOWN, timeout=120)
    _record(result, "compose down", ok, out)
    if not ok:
        return False

    if cfg.cleanup_mode is LabCleanupMode.MODERATE:
        ok, out = _sh(device, _DATA_DIRS_WIPE, timeout=20)
        _record(result, "wipe data dirs (keep config)", ok, out)
        return ok

    # NUCLEAR: wipe everything and uninstall the CLI tool too.
    ok, out = _sh(
        device,
        "rm -rf $HOME/.mycelium 2>/dev/null; uv tool uninstall mycelium-cli >/dev/null 2>&1 || true; true",
        timeout=30,
    )
    _record(result, "nuclear wipe (~/.mycelium + cli)", ok, out)
    return ok


# ── CLI install from git ───────────────────────────────────────────────


def _uv_install_cmd(cfg: LabRedeployConfig) -> str:
    """Build the ``uv tool install`` command for the configured ref.

    Pulls the CLI and its client subdirectory from the same ref so they
    can't drift. ``--force`` overwrites any existing tool install.
    """
    # ``uv tool install --with <pkg>`` lets us pull the generated openapi
    # client from the same ref; otherwise the released version on PyPI
    # would be used, which lags behind ``main``.
    repo = cfg.repo_url.removesuffix(".git")
    client_spec = f"mycelium-backend-client @ git+{repo}.git@{cfg.ref}#subdirectory=mycelium-client"
    cli_spec = f"git+{repo}.git@{cfg.ref}#subdirectory=mycelium-cli"
    return (
        # uv lives in ~/.local/bin or ~/.cargo/bin on the spokes; the
        # _shell_wrap prelude in host_exec already prepends both. We
        # still source PATH defensively for clarity.
        'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; '
        # Install with `--with`, quoting around the requirement spec so
        # the embedded ``#subdirectory`` segment isn't treated as a
        # shell comment.
        f"uv tool install --force --with '{client_spec}' '{cli_spec}'"
    )


def install_cli(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Install the mycelium CLI from ``cfg.ref`` on the device."""
    ok, out = _sh(device, _uv_install_cmd(cfg), timeout=300)
    _record(result, f"uv tool install mycelium-cli@{cfg.ref}", ok, out)
    if not ok:
        return False

    # Verify the install resolved to the expected ref by running
    # ``mycelium --version``. The version string includes the git hash
    # for source installs but not for PyPI releases; either is fine —
    # we just want to confirm the binary is on PATH.
    ok, out = _sh(device, "mycelium --version 2>&1", timeout=15)
    _record(result, "mycelium --version", ok, out)
    return ok


# ── hub: source clone + image build ────────────────────────────────────


def _clone_cmd(cfg: LabRedeployConfig) -> str:
    """Idempotent shallow clone (or fetch) into ``cfg.source_dir``."""
    return (
        f"if [ -d {cfg.source_dir}/.git ]; then "
        f"  cd {cfg.source_dir} && "
        f"  git fetch --depth 1 origin {cfg.ref} && "
        f"  git checkout FETCH_HEAD; "
        f"else "
        f"  rm -rf {cfg.source_dir} && "
        f"  git clone --depth 1 --branch {cfg.ref} {cfg.repo_url} {cfg.source_dir} || "
        # Fall back to a non-shallow clone when ``ref`` is a SHA (which
        # ``git clone --branch`` rejects).
        f"  (rm -rf {cfg.source_dir} && git clone {cfg.repo_url} {cfg.source_dir} && "
        f"   cd {cfg.source_dir} && git checkout {cfg.ref}); "
        f"fi"
    )


def fetch_source(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Clone (or fast-forward) the mycelium repo on the hub."""
    ok, out = _sh(device, _clone_cmd(cfg), timeout=300)
    _record(result, f"clone {cfg.ref} → {cfg.source_dir}", ok, out)
    return ok


_BUILD_HUB_IMAGES = (
    # Build mycelium-backend:dev and mycelium-collector:dev from the
    # source tree using compose-dev.yml's build contexts. The compose
    # override also wires pull_policy=never so a subsequent ``up`` won't
    # clobber our local builds with stale registry images. We need both
    # the ``cfn`` and ``metrics`` profiles active for the collector
    # service to even be in scope.
    "cd {src}/mycelium-cli/src/mycelium/docker && "
    "docker compose -f compose.yml -f compose-dev.yml "
    "--profile cfn --profile metrics build "
    "mycelium-backend mycelium-collector"
)


def build_hub_images(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Build mycelium-backend + mycelium-collector images on the hub."""
    cmd = _BUILD_HUB_IMAGES.format(src=cfg.source_dir)
    ok, out = _sh(device, cmd, timeout=900)  # image builds can take a while
    _record(result, "docker build backend + collector", ok, out)
    if not ok:
        return False

    if cfg.include_ui:
        ui_cmd = f"cd {cfg.source_dir}/mycelium-frontend && docker build -t mycelium-frontend:dev ."
        ok, out = _sh(device, ui_cmd, timeout=900)
        _record(result, "docker build frontend (--include-ui)", ok, out)
        return ok

    return True


# ── hub: bring stack up ───────────────────────────────────────────────


def _write_env_overrides_cmd(cfg: LabRedeployConfig) -> str | None:
    """Append ``cfg.env_overrides`` to ``~/.mycelium/.env`` idempotently.

    Returns ``None`` when there are no overrides (caller skips the step).
    """
    if not cfg.env_overrides:
        return None
    # Build a series of `set_env KEY VALUE` invocations that rewrite the
    # matching line in place (or append). Single-quote the value so
    # shell expansion can't corrupt it; the value itself can't contain
    # a single quote without escaping (we reject that below).
    lines = ["mkdir -p $HOME/.mycelium && touch $HOME/.mycelium/.env"]
    for key, value in cfg.env_overrides.items():
        if "'" in value:
            raise ValueError(f"env_overrides[{key!r}] contains a single quote which is unsupported")
        if not key.replace("_", "").isalnum() or not key[0].isalpha():
            raise ValueError(f"env_overrides key {key!r} must be a valid shell identifier")
        # Replace existing line, else append. Use a sentinel so grep can't
        # match a substring (e.g. ``LLM_API_KEY`` vs ``LLM_API_KEY_BACKUP``).
        lines.append(
            f"grep -v '^{key}=' $HOME/.mycelium/.env > $HOME/.mycelium/.env.tmp && "
            f"mv $HOME/.mycelium/.env.tmp $HOME/.mycelium/.env && "
            f"echo \"{key}='{value}'\" >> $HOME/.mycelium/.env"
        )
    return "; ".join(lines)


def apply_env_overrides(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Render ``cfg.env_overrides`` into ``~/.mycelium/.env``."""
    cmd = _write_env_overrides_cmd(cfg)
    if cmd is None:
        return True
    # Use 30s timeout; this is purely file I/O.
    ok, out = _sh(device, cmd, timeout=30)
    # Mask the actual values from logs.
    keys = ",".join(cfg.env_overrides.keys())
    _record(result, f"write ~/.mycelium/.env ({keys})", ok, "" if ok else out)
    return ok


_COMPOSE_UP_HUB = (
    # We deliberately bypass ``mycelium install`` here because that
    # command is hardwired to pull ``:latest`` from ghcr. Compose-dev's
    # ``pull_policy: never`` ensures our locally-built images stick.
    # Profiles: ``cfn`` (cognition fabric services for negotiations) +
    # ``metrics`` (collector for token / cost telemetry). The ``ui``
    # profile is intentionally omitted — scenarios don't need it and
    # skipping the frontend pull keeps the redeploy hermetic.
    "cd {src}/mycelium-cli/src/mycelium/docker && "
    "docker compose -f compose.yml -f compose-dev.yml "
    "--profile cfn --profile metrics up -d"
)


def start_hub_stack(device: Any, cfg: LabRedeployConfig, result: DeviceResult) -> bool:
    """Bring the hub's docker stack up with the freshly built images."""
    cmd = _COMPOSE_UP_HUB.format(src=cfg.source_dir)
    ok, out = _sh(device, cmd, timeout=300)
    _record(result, "compose up -d (backend + collector + cfn)", ok, out)
    return ok


# ── spoke: point at hub ───────────────────────────────────────────────


def configure_spoke(device: Any, hub_url: str, result: DeviceResult) -> bool:
    """Point the spoke's CLI at ``hub_url``.

    The CLI's ``config set`` writes to ``~/.mycelium/config.toml`` and is
    idempotent. We follow with ``config apply`` so the rendered ``.env``
    matches.
    """
    cmd = f"mycelium config set server.api_url {hub_url} && mycelium config apply"
    ok, out = _sh(device, cmd, timeout=30)
    _record(result, f"point CLI at {hub_url}", ok, out)
    return ok


# ── health check ───────────────────────────────────────────────────────


def verify_hub_health(device: Any, hub_url: str, result: DeviceResult, *, timeout: float = 120.0) -> bool:
    """Poll the backend ``/health`` endpoint until it returns 200."""
    cmd = (
        # Loop in shell rather than blasting many ssh round-trips. 60
        # attempts × 2s = 120s budget.
        "ok=0; "
        f"for i in $(seq 1 60); do "
        f'  code=$(curl -sf -o /dev/null -w "%{{http_code}}" {hub_url}/health 2>/dev/null || echo "000"); '
        '  if [ "$code" = "200" ]; then ok=1; break; fi; '
        "  sleep 2; "
        "done; "
        '[ $ok = 1 ] && echo "backend healthy" || (echo "backend NOT healthy" && exit 1)'
    )
    ok, out = _sh(device, cmd, timeout=timeout + 20)
    _record(result, f"GET {hub_url}/health", ok, out)
    return ok


def verify_spoke_reachable(device: Any, hub_url: str, result: DeviceResult) -> bool:
    """Confirm the spoke can reach the hub's backend."""
    # curl returns nonzero for any HTTP error so a healthy backend yields
    # code 200 → curl exit 0. Use --max-time so we don't hang on a bad
    # network.
    cmd = f"curl -sf --max-time 10 {hub_url}/health > /dev/null && echo reachable"
    ok, out = _sh(device, cmd, timeout=20)
    _record(result, f"spoke can reach {hub_url}", ok, out)
    return ok


# ── top-level orchestration ────────────────────────────────────────────


def redeploy_device(device: Any, cfg: LabRedeployConfig, hub_url: str | None = None) -> DeviceResult:
    """Redeploy ``device`` per ``cfg``.

    ``hub_url`` is only consulted on spokes — defaulted from
    ``device.custom.mycelium_backend_url`` when not supplied. Hubs
    derive their own URL from the device record.

    Returns a :class:`DeviceResult` (never raises for routine failures
    — the structured result is the contract).
    """
    name = getattr(device, "name", None) or "<device>"
    role = _role(device)
    result = DeviceResult(device_name=name, role=role, success=False)

    log.info("=== redeploy %s (role=%s, ref=%s, mode=%s) ===", name, role, cfg.ref, cfg.cleanup_mode.value)

    # 1. Cleanup
    if not cleanup_device(device, cfg, result):
        result.error = "cleanup failed"
        return result

    # 2. CLI install (both hub and spokes need the same ref of the CLI)
    if not install_cli(device, cfg, result):
        result.error = "CLI install failed"
        return result

    # 3. Hub-only: source clone + image build + bring stack up + env overrides
    if role == "hub":
        if not fetch_source(device, cfg, result):
            result.error = "source clone failed"
            return result
        if not build_hub_images(device, cfg, result):
            result.error = "image build failed"
            return result
        if not apply_env_overrides(device, cfg, result):
            result.error = "env overrides write failed"
            return result
        if not start_hub_stack(device, cfg, result):
            result.error = "compose up failed"
            return result

        hub_url_local = hub_url or _backend_url(device) or "http://localhost:8000"
        if not verify_hub_health(device, hub_url_local, result):
            result.error = "backend health check failed"
            return result

    # 4. Spoke: just point the CLI at the hub
    else:
        target = hub_url or _backend_url(device)
        if not target:
            result.error = "no hub_url supplied and custom.mycelium_backend_url unset"
            _record(result, "configure spoke", False, result.error)
            return result
        if not configure_spoke(device, target, result):
            result.error = "spoke configuration failed"
            return result
        if not verify_spoke_reachable(device, target, result):
            result.error = "spoke cannot reach hub"
            return result

    result.success = True
    log.info("=== redeploy %s OK ===", name)
    return result


def redeploy_testbed(testbed: Any, cfg: LabRedeployConfig) -> list[DeviceResult]:
    """Redeploy every device in ``testbed`` (hub first, then spokes).

    ``testbed`` is anything exposing a ``devices`` mapping — a pyATS
    Testbed or a plain dict works. Hubs are redeployed first because
    spokes need the hub's backend URL.
    """
    devices_map = getattr(testbed, "devices", None) or testbed.get("devices", {})  # type: ignore[union-attr]
    devices = list(devices_map.values())

    hubs = [d for d in devices if _role(d) == "hub"]
    spokes = [d for d in devices if _role(d) != "hub"]

    if not hubs:
        raise ValueError("testbed has no device with custom.role=hub")
    if len(hubs) > 1:
        raise ValueError(f"testbed has {len(hubs)} hubs; expected exactly one")

    results: list[DeviceResult] = []
    hub = hubs[0]
    hub_result = redeploy_device(hub, cfg)
    results.append(hub_result)

    # If the hub failed there's no point redeploying spokes — they'd
    # all fail the reachability check. Fail fast and let the caller
    # report.
    if not hub_result.success:
        log.error("Hub redeploy failed (%s) — skipping spokes", hub_result.error)
        return results

    hub_url = _backend_url(hub)
    for spoke in spokes:
        results.append(redeploy_device(spoke, cfg, hub_url=hub_url))

    return results
