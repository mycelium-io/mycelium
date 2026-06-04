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

    ``workspace_id`` and ``mas_id`` are only populated on the hub
    redeploy (the source of truth for those IDs); the orchestrator
    propagates them to spoke calls.
    """

    device_name: str
    role: str
    success: bool
    error: str | None = None
    logs: list[tuple[str, bool, str]] = field(default_factory=list)
    workspace_id: str | None = None
    mas_id: str | None = None


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
    # We also reclaim ownership of the parent directory because the
    # systemd-managed daemon (or pre-redeploy compose containers) may
    # have written files as root; those would otherwise survive into
    # the next deploy and trip ``mycelium doctor``'s ownership check.
    "if [ -d $HOME/.mycelium ]; then sudo chown -R $USER:$USER $HOME/.mycelium 2>/dev/null || "
    "chown -R $USER:$USER $HOME/.mycelium 2>/dev/null || true; fi; "
    "[ -d $HOME/.mycelium/rooms ] && rm -rf $HOME/.mycelium/rooms; "
    "[ -d $HOME/.mycelium/data ] && rm -rf $HOME/.mycelium/data; "
    "[ -d $HOME/.mycelium/logs ] && rm -rf $HOME/.mycelium/logs; "
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


# ── workspace + MAS provisioning ──────────────────────────────────────


# A tiny Python program that calls the backend's workspace + MAS APIs
# the same way ``mycelium install`` does (see
# ``mycelium-cli/src/mycelium/commands/install.py:_provision_backend``).
# It's idempotent — creates the default workspace/MAS if they don't
# exist, or fetches the existing first entry if creation returns
# 400/409. Output is two lines: ``WORKSPACE_ID=<uuid>`` and
# ``MAS_ID=<uuid>`` so the caller can grep both back out cleanly.
#
# We embed it as a heredoc rather than scp-ing a file because the lab
# spokes don't necessarily have a writable temp dir we control.
_PROVISION_PY = r"""
import json, sys, urllib.request, urllib.error

api_url = sys.argv[1]

def _get(path):
    req = urllib.request.Request(api_url + path,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(api_url + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# workspace ---------------------------------------------------------
try:
    ws = _post("/api/workspaces", {"name": "default"})
except urllib.error.HTTPError as e:
    if e.code in (400, 409):
        wss = _get("/api/workspaces")
        ws = next((w for w in wss if w.get("name") == "default"),
                  wss[0] if wss else None)
        if ws is None:
            print("ERR: no workspaces returned by backend", file=sys.stderr)
            sys.exit(1)
    else:
        raise
ws_id = ws["id"]

# MAS ---------------------------------------------------------------
try:
    mas = _post(f"/api/workspaces/{ws_id}/mas", {"name": "default"})
except urllib.error.HTTPError as e:
    if e.code in (400, 409):
        mas_list = _get(f"/api/workspaces/{ws_id}/mas")
        if not mas_list:
            print("ERR: no MAS returned by backend", file=sys.stderr)
            sys.exit(1)
        mas = mas_list[0]
    else:
        raise
mas_id = mas["id"]

print(f"WORKSPACE_ID={ws_id}")
print(f"MAS_ID={mas_id}")
"""


def _parse_provisioned_ids(stdout: str) -> tuple[str, str] | None:
    """Extract WORKSPACE_ID + MAS_ID from the provisioning script's stdout.

    Returns ``None`` if either line is missing or malformed — callers
    treat that as a provisioning failure.
    """
    ws_id = mas_id = ""
    for line in stdout.splitlines():
        if line.startswith("WORKSPACE_ID="):
            ws_id = line.split("=", 1)[1].strip()
        elif line.startswith("MAS_ID="):
            mas_id = line.split("=", 1)[1].strip()
    if not ws_id or not mas_id:
        return None
    return ws_id, mas_id


def provision_workspace_and_mas(device: Any, hub_url: str, result: DeviceResult) -> tuple[str, str] | None:
    """Create (or fetch) the default workspace + MAS on the hub.

    Returns ``(workspace_id, mas_id)`` on success, ``None`` on failure
    (already recorded in ``result``).
    """
    # Heredoc the script via stdin so we don't have to worry about
    # quoting / writing it to disk. ``python3 -`` reads from stdin.
    # The script reads its API URL from argv[1].
    cmd = f"python3 - {hub_url} <<'PYEOF'{_PROVISION_PY}PYEOF"
    ok, out = _sh(device, cmd, timeout=60)
    if not ok:
        _record(result, "provision workspace + MAS", False, out)
        return None

    parsed = _parse_provisioned_ids(out)
    if parsed is None:
        _record(result, "provision workspace + MAS", False, f"malformed output: {out[:200]}")
        return None

    ws_id, mas_id = parsed
    _record(
        result,
        "provision workspace + MAS",
        True,
        f"workspace={ws_id[:8]}… mas={mas_id[:8]}…",
    )
    return ws_id, mas_id


# Container-internal CFN URLs — same constants ``mycelium install``
# writes when the IOC stack is enabled (install.py:_patch_env_vars).
# The backend container reaches CFN services by docker-network hostname,
# so these don't change between deployments.
_CFN_MGMT_URL_INTERNAL = "http://ioc-cfn-mgmt-plane-svc:9000"
_COGNITION_FABRIC_NODE_URL_INTERNAL = "http://ioc-cognition-fabric-node-svc:9002"

_PERSIST_HUB_IDS = (
    # Persist the provisioned IDs + CFN URLs via the CLI. ``config
    # set`` writes ``~/.mycelium/config.toml``; ``config apply`` then
    # renders the matching ``~/.mycelium/.env`` (which the backend
    # container picks up via the compose-dev env_file mount).
    "mycelium config set server.workspace_id {ws} && "
    "mycelium config set server.mas_id {mas} && "
    "mycelium config set runtime.cfn_mgmt_url {cfn_mgmt} && "
    "mycelium config set runtime.cognition_fabric_node_url {cognition} && "
    "mycelium config apply"
)

_PERSIST_SPOKE_IDS = (
    # Spokes don't run CFN containers locally — they don't need the
    # CFN_*_URL vars set. We only push workspace + MAS so the spoke
    # CLI can address the hub's MAS in API calls.
    "mycelium config set server.workspace_id {ws} && mycelium config set server.mas_id {mas} && mycelium config apply"
)


def persist_workspace_and_mas(
    device: Any,
    workspace_id: str,
    mas_id: str,
    result: DeviceResult,
    *,
    is_hub: bool = False,
) -> bool:
    """Write the IDs into the device's config via the mycelium CLI.

    On the hub, also writes ``CFN_MGMT_URL`` and
    ``COGNITION_FABRIC_NODE_URL`` so the backend container can reach
    the cognition fabric services (without these, ``mycelium doctor
    --mode hub`` reports a CFN config warning and negotiations fail).
    """
    # Basic UUID-ish validation. We don't need strict UUID format
    # (some backends use shorter / longer IDs), but we DO want to
    # reject anything containing shell metacharacters.
    for label, val in (("workspace_id", workspace_id), ("mas_id", mas_id)):
        if not val or any(c in val for c in " \t\n;|&`$<>"):
            _record(result, f"persist {label}", False, f"refused unsafe value: {val!r}")
            return False

    template = _PERSIST_HUB_IDS if is_hub else _PERSIST_SPOKE_IDS
    cmd = template.format(
        ws=workspace_id,
        mas=mas_id,
        cfn_mgmt=_CFN_MGMT_URL_INTERNAL,
        cognition=_COGNITION_FABRIC_NODE_URL_INTERNAL,
    )
    ok, out = _sh(device, cmd, timeout=30)
    label = "persist workspace + MAS + CFN URLs" if is_hub else "persist workspace + MAS"
    _record(result, f"{label} to config", ok, out)
    return ok


# ── top-level orchestration ────────────────────────────────────────────


def redeploy_device(
    device: Any,
    cfg: LabRedeployConfig,
    hub_url: str | None = None,
    *,
    provisioned_ids: tuple[str, str] | None = None,
) -> DeviceResult:
    """Redeploy ``device`` per ``cfg``.

    ``hub_url`` is only consulted on spokes — defaulted from
    ``device.custom.mycelium_backend_url`` when not supplied. Hubs
    derive their own URL from the device record.

    ``provisioned_ids`` is ``(workspace_id, mas_id)`` from the hub's
    provisioning step. When supplied (typically by
    :func:`redeploy_testbed` for spokes) the spoke writes the same
    IDs into its CLI config so it can talk to the same backend.

    Returns a :class:`DeviceResult` (never raises for routine failures
    — the structured result is the contract).
    """
    name = getattr(device, "name", None) or "<device>"
    role = _role(device)
    result = DeviceResult(device_name=name, role=role, success=False)

    log.info(
        "=== redeploy %s (role=%s, ref=%s, mode=%s) ===",
        name,
        role,
        cfg.ref,
        cfg.cleanup_mode.value,
    )

    # 1. Cleanup
    if not cleanup_device(device, cfg, result):
        result.error = "cleanup failed"
        return result

    # 2. CLI install (both hub and spokes need the same ref of the CLI)
    if not install_cli(device, cfg, result):
        result.error = "CLI install failed"
        return result

    # 3. Hub-only: source clone + image build + bring stack up + provision IDs
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

        # Provision workspace + MAS against the freshly booted backend
        # (the DB was wiped, so any old IDs in config.toml are stale).
        # Persist the new IDs locally before signalling success so the
        # hub's mycelium CLI is also in sync.
        ids = provision_workspace_and_mas(device, hub_url_local, result)
        if ids is None:
            result.error = "workspace/MAS provisioning failed"
            return result
        ws_id, mas_id = ids
        result.workspace_id = ws_id
        result.mas_id = mas_id
        if not persist_workspace_and_mas(device, ws_id, mas_id, result, is_hub=True):
            result.error = "could not persist workspace/MAS to hub config"
            return result

        # Restart the backend so it picks up the freshly written
        # WORKSPACE_ID / MAS_ID / CFN_MGMT_URL / COGNITION_FABRIC_NODE_URL
        # from the rendered .env. Without this restart the backend
        # keeps its boot-time env (empty values) and ``mycelium
        # doctor`` reports CFN config warnings.
        ok, out = _sh(
            device,
            f"cd {cfg.source_dir}/mycelium-cli/src/mycelium/docker && "
            "docker compose -f compose.yml -f compose-dev.yml "
            "--profile cfn --profile metrics restart mycelium-backend",
            timeout=120,
        )
        if not _record(result, "restart backend (pick up new env)", ok, out):
            result.error = "could not restart backend after provisioning"
            return result

    # 4. Spoke: point CLI at hub, then persist the same workspace/MAS
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
        if provisioned_ids is not None:
            ws_id, mas_id = provisioned_ids
            if not persist_workspace_and_mas(device, ws_id, mas_id, result):
                result.error = "could not persist workspace/MAS to spoke config"
                return result

    result.success = True
    log.info("=== redeploy %s OK ===", name)
    return result


def redeploy_testbed(testbed: Any, cfg: LabRedeployConfig) -> list[DeviceResult]:
    """Redeploy every device in ``testbed`` (hub first, then spokes).

    ``testbed`` is anything exposing a ``devices`` mapping — a pyATS
    Testbed or a plain dict works. Hubs are redeployed first because
    spokes need both the hub's backend URL **and** the workspace/MAS
    IDs that get provisioned during the hub redeploy.
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
    provisioned_ids: tuple[str, str] | None = None
    if hub_result.workspace_id and hub_result.mas_id:
        provisioned_ids = (hub_result.workspace_id, hub_result.mas_id)

    for spoke in spokes:
        results.append(redeploy_device(spoke, cfg, hub_url=hub_url, provisioned_ids=provisioned_ids))

    return results
