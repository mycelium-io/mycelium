# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Package + drive a local NVIDIA OpenShell gateway that sandboxes Pi.

OpenShell (https://github.com/NVIDIA/OpenShell) is the policy-controlled sandbox
runtime we run our *internal* Pi cognition engines inside. The gateway is its
control plane: a Docker container that spawns per-run sandboxes via the host
Docker socket. Getting a working *local* gateway is a multi-step recipe the
upstream "quickstart" glosses over; this module encodes the version we validated
end to end (``pi`` running inside a ``--from pi`` sandbox) so ``mycelium openshell
install`` can reproduce it deterministically.

The recipe, in order:

1. **Ensure the ``openshell`` CLI** on PATH (``uv tool install openshell``).
2. **Extract the supervisor binary** from the supervisor image to a host path
   that is *mirrored* into the gateway (host path == container path); the
   gateway hands that same path to Docker when it starts a sandbox, so it must
   resolve on the host too.
3. **Generate an Ed25519 JWT signing keypair**, the Docker driver requires
   gateway-minted sandbox JWT auth (``[openshell.gateway.gateway_jwt]``).
4. **Render ``gateway.toml``** (jwt + ``allow_unauthenticated_users`` for local +
   the docker driver).
5. **Run the gateway container** as root (docker.sock access), TLS off for local,
   with ``HOME`` pointed at a mirrored state dir so the supervisor/JWT-token
   staging paths exist on the host, and the Prometheus ``/metrics`` port on.
6. **Register + select** the gateway with the CLI and **create the ``pi``
   sandbox**.
7. **Wire observability**: add a ``grpc_red`` scrape target so the gateway's
   gRPC RED metrics surface in ``mycelium metrics`` (traces are not exported by
   OpenShell today).

**Security posture (local dev):** the gateway mounts ``/var/run/docker.sock`` and
runs with TLS off + unauthenticated local access. That's the documented local
setup but a real host exposure; the command layer surfaces it as an explicit
opt-in; this module never enables it silently.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

GATEWAY_IMAGE = "ghcr.io/nvidia/openshell/gateway:latest"
SUPERVISOR_IMAGE = "ghcr.io/nvidia/openshell/supervisor:latest"
GATEWAY_CONTAINER = "mycelium-openshell-gateway"
GATEWAY_PORT = 8080
METRICS_PORT = 9464
GATEWAY_ENDPOINT = f"http://127.0.0.1:{GATEWAY_PORT}"
PI_SANDBOX_NAME = "mycelium-pi"

# The scrape target that surfaces the gateway's gRPC RED metrics in
# ``mycelium metrics`` (see prom_scrape.aggregate_grpc_red). The collector runs
# in a container, so it reaches the host-published metrics port via the Docker
# host alias, not localhost.
SCRAPE_TARGET_NAME = "openshell-gateway"
SCRAPE_TARGET_URL = f"http://host.docker.internal:{METRICS_PORT}/metrics"
SCRAPE_TARGET_KIND = "grpc_red"


class OpenShellError(RuntimeError):
    """A step of the OpenShell setup failed (missing tool, docker error, ...)."""


# ── Host paths (all under ~/.mycelium/openshell, mirrored into the gateway) ───


def openshell_dir() -> Path:
    """Root for OpenShell host artifacts (``~/.mycelium/openshell``)."""
    return Path.home() / ".mycelium" / "openshell"


def state_dir() -> Path:
    """The gateway's mirrored ``HOME``/state dir (DB + supervisor/JWT staging).

    Mounted host==container so paths the gateway hands to Docker for a spawned
    sandbox resolve on the host.
    """
    return openshell_dir() / "state"


def jwt_dir() -> Path:
    return openshell_dir() / "jwt"


def supervisor_bin() -> Path:
    return openshell_dir() / "supervisor" / "openshell-sandbox"


def gateway_toml() -> Path:
    return openshell_dir() / "gateway.toml"


# ── Pure builders (unit-tested) ──────────────────────────────────────────────


def render_gateway_toml() -> str:
    """The gateway config: JWT signing keys, unauthenticated local access, docker.

    The Docker driver *requires* gateway-minted sandbox JWT auth, so
    ``[openshell.gateway.gateway_jwt]`` with an Ed25519 signing keypair is
    mandatory; ``allow_unauthenticated_users`` keeps the local single-user CLI
    from needing its own auth. ``ttl_secs = 0`` = non-expiring tokens (local
    only). Key paths are the in-container mount points (``/etc/openshell/jwt``).
    """
    return (
        "[openshell]\n"
        "version = 1\n\n"
        "[openshell.gateway]\n"
        'compute_drivers = ["docker"]\n\n'
        "[openshell.gateway.gateway_jwt]\n"
        'signing_key_path = "/etc/openshell/jwt/signing.pem"\n'
        'public_key_path  = "/etc/openshell/jwt/public.pem"\n'
        'kid_path         = "/etc/openshell/jwt/kid"\n'
        'gateway_id       = "mycelium"\n'
        "ttl_secs         = 0\n\n"
        "[openshell.gateway.auth]\n"
        "allow_unauthenticated_users = true\n\n"
        "[openshell.drivers.docker]\n"
        'socket_path   = "/var/run/docker.sock"\n'
        f'grpc_endpoint = "http://host.openshell.internal:{GATEWAY_PORT}"\n'
    )


def build_gateway_run_command(
    *,
    state: Path,
    jwt: Path,
    config: Path,
    supervisor: Path,
    enable_metrics: bool = True,
) -> list[str]:
    """The ``docker run`` argv for the gateway: the validated invocation.

    Runs as root (docker.sock access), TLS off for local, with ``HOME`` set to
    the mirrored *state* dir so the gateway stages the supervisor binary + minted
    sandbox JWT tokens under a path that exists on the host too (else Docker
    denies the sandbox's bind-mount). All host artifacts are absolute so the
    host==container mirroring holds.
    """
    st, jw, cfg, sup = (str(p) for p in (state, jwt, config, supervisor))
    cmd = [
        "docker", "run", "-d", "--name", GATEWAY_CONTAINER,
        "--restart", "unless-stopped", "--user", "0:0",
        "-p", f"127.0.0.1:{GATEWAY_PORT}:{GATEWAY_PORT}",
    ]  # fmt: skip
    if enable_metrics:
        cmd += ["-p", f"127.0.0.1:{METRICS_PORT}:{METRICS_PORT}"]
    cmd += [
        "-e", f"HOME={st}",
        "-v", f"{st}:{st}",
        "-v", f"{cfg}:/etc/openshell/gateway.toml:ro",
        "-v", f"{jw}:/etc/openshell/jwt:ro",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{sup}:{sup}:ro",
        "-e", "OPENSHELL_GATEWAY_CONFIG=/etc/openshell/gateway.toml",
        "-e", "OPENSHELL_DRIVERS=docker",
        "-e", f"OPENSHELL_DOCKER_SUPERVISOR_BIN={sup}",
        "-e", f"OPENSHELL_DB_URL=sqlite:{st}/openshell.db?mode=rwc",
        "-e", "OPENSHELL_DISABLE_TLS=true",
    ]  # fmt: skip
    if enable_metrics:
        cmd += [
            "-e",
            f"OPENSHELL_METRICS_PORT={METRICS_PORT}",
            "-e",
            "OPENSHELL_BIND_ADDRESS=0.0.0.0",
        ]
    cmd.append(GATEWAY_IMAGE)
    return cmd


def ensure_scrape_target(config: MyceliumConfig) -> bool:
    """Add the gateway's ``grpc_red`` scrape target to config if absent.

    Returns True if it was added (caller persists + regenerates env). Idempotent:
    a target already named ``openshell-gateway`` is left as-is.
    """
    from mycelium.config import ScrapeTarget

    if any(t.name == SCRAPE_TARGET_NAME for t in config.metrics.scrape):
        return False
    config.metrics.scrape.append(
        ScrapeTarget(name=SCRAPE_TARGET_NAME, url=SCRAPE_TARGET_URL, kind=SCRAPE_TARGET_KIND)
    )
    return True


# ── Orchestration (touches docker / the openshell CLI) ───────────────────────


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=capture, text=True, check=True)
    except FileNotFoundError as exc:
        raise OpenShellError(f"command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() if capture else str(exc)
        raise OpenShellError(f"`{' '.join(cmd[:3])} …` failed: {detail[:400]}") from exc


def cli_installed() -> bool:
    return shutil.which("openshell") is not None


def ensure_cli() -> None:
    """Install the ``openshell`` CLI via uv if it isn't already on PATH."""
    if cli_installed():
        return
    if shutil.which("uv") is None:
        raise OpenShellError(
            "`openshell` not found and `uv` is unavailable to install it. "
            "Install OpenShell: curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh"
        )
    _run(["uv", "tool", "install", "-U", "openshell"], capture=True)


def generate_jwt_keypair(dest: Path) -> None:
    """Write an Ed25519 signing keypair + ``kid`` (the gateway's required alg).

    Idempotent: existing keys are kept (regenerating would invalidate any live
    sandbox tokens). Shells to ``openssl``, the same path validated live.
    """
    dest.mkdir(parents=True, exist_ok=True)
    signing, public, kid = dest / "signing.pem", dest / "public.pem", dest / "kid"
    if signing.exists() and public.exists() and kid.exists():
        return
    if shutil.which("openssl") is None:
        raise OpenShellError("`openssl` not found, needed to generate the gateway JWT keypair.")
    _run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(signing)], capture=True)
    _run(["openssl", "pkey", "-in", str(signing), "-pubout", "-out", str(public)], capture=True)
    kid.write_text("mycelium", encoding="utf-8")
    for p in (signing, public, kid):
        p.chmod(0o644)


def extract_supervisor(dest: Path) -> None:
    """Copy the supervisor binary out of the supervisor image to a host path."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = "mycelium-openshell-supervisor-extract"
    subprocess.run(["docker", "rm", "-f", tmp], capture_output=True, text=True, check=False)
    _run(["docker", "create", "--name", tmp, SUPERVISOR_IMAGE], capture=True)
    try:
        _run(["docker", "cp", f"{tmp}:/openshell-sandbox", str(dest)], capture=True)
    finally:
        subprocess.run(["docker", "rm", tmp], capture_output=True, text=True, check=False)
    dest.chmod(0o755)


def gateway_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", GATEWAY_CONTAINER],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return result.returncode == 0 and result.stdout.strip() == "true"


def wait_gateway_ready(timeout_s: float = 25.0) -> None:
    """Block until the ``openshell`` CLI reports the gateway Connected.

    The gateway needs a moment after ``docker run`` before it serves the gRPC
    API; issuing ``sandbox create`` too early races into a broken-pipe/transport
    error. Polls ``openshell status`` until it says Connected or the deadline.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["openshell", "status"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and "Connected" in result.stdout:
            return
        time.sleep(1.0)
    raise OpenShellError(f"gateway did not become ready within {timeout_s:.0f}s")


def run_gateway(*, enable_metrics: bool = True) -> None:
    """(Re)create the gateway container from the validated recipe."""
    subprocess.run(
        ["docker", "rm", "-f", GATEWAY_CONTAINER], capture_output=True, text=True, check=False
    )
    cmd = build_gateway_run_command(
        state=state_dir(),
        jwt=jwt_dir(),
        config=gateway_toml(),
        supervisor=supervisor_bin(),
        enable_metrics=enable_metrics,
    )
    _run(cmd, capture=True)


def register_gateway() -> None:
    """Register + select the local gateway with the ``openshell`` CLI.

    Idempotent: ``gateway add`` errors if the name already exists, so the add is
    best-effort (a re-install re-uses the existing registration) and only the
    ``select`` is required to succeed.
    """
    subprocess.run(
        ["openshell", "gateway", "add", GATEWAY_ENDPOINT, "--local", "--name", "mycelium"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    _run(["openshell", "gateway", "select", "mycelium"], capture=True)


def create_pi_sandbox(name: str = PI_SANDBOX_NAME, *, attempts: int = 3) -> None:
    """Create the bundled Pi sandbox (``--from pi``), if it doesn't exist.

    Waits for the gateway to be ready first, then retries a couple of times: a
    freshly-started gateway can drop the first ``create`` with a transient
    transport/broken-pipe error before its driver + supervisor are fully wired.
    """
    existing = subprocess.run(
        ["openshell", "sandbox", "get", name], capture_output=True, text=True, check=False
    )
    if existing.returncode == 0:
        return
    wait_gateway_ready()
    last: OpenShellError | None = None
    for i in range(attempts):
        try:
            _run(["openshell", "sandbox", "create", "--from", "pi", "--name", name], capture=True)
            return
        except OpenShellError as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(4.0)
    if last is not None:
        raise last
