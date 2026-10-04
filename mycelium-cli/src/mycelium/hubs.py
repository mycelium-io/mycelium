# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every Mycelium hub this machine can see, and what is wrong with the set.

Two stacks on one machine is easy to get into (a Docker stack left over from
an eval, the Mac app's own hub, a ``uvicorn`` from a checkout) and hard to
notice: whichever answers the port first gets every write, and nothing else
says so. :func:`find_hubs` looks in three places:

- Docker containers from a Mycelium backend image, or that compose names as
  the ``mycelium-backend`` service, with the host folder their data is mounted
  from and the compose project they belong to;
- ``mycelium-hub`` and ``uvicorn app.main`` processes outside any container;
- whatever answers ``/health`` on the port the app wants.

Each hub that answers says its version and its store's id (``/health``'s
``storage.id``, a random id written once into the data dir), which is how two
hubs, or a hub and this machine's own data dir, are told apart wherever each
sees the folder. :func:`warnings` says what deserves a person's attention:
more than one hub, a hub writing somewhere other than this machine's data
dir, and a hub older than this CLI or built from a development image.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from mycelium.integrations.herdr.bridge import version_tuple

#: The file in a data dir that names its store. The backend writes the same
#: one (``app/services/filesystem.py``), whichever of the two gets there first.
STORE_ID_FILE = ".store-id"
#: Where the backend image keeps its data inside the container.
CONTAINER_DATA_DIR = "/home/mycelium/.mycelium"
#: The compose service the hub runs as.
COMPOSE_SERVICE = "mycelium-backend"
#: How long any one look (a docker call, a /health probe) may take.
TIMEOUT_S = 3.0

Source = Literal["docker", "process", "port"]

_PROCESS = re.compile(r"(?:^|[/\s])(?:mycelium-hub|uvicorn\s+(?:\S+\s+)*?app\.main:app)(?:\s|$)")
_PORT_ARG = re.compile(r"--port[=\s]+(\d+)")


@dataclass
class Hub:
    """One hub on this machine, as much as could be found out about it."""

    source: Source
    #: The host port it answers on, when known.
    port: int | None = None
    version: str | None = None
    #: Where its data is on this machine (a container's mount source).
    data_path: str | None = None
    store_id: str | None = None
    image: str | None = None
    project: str | None = None
    container: str | None = None
    pid: int | None = None
    #: Whether ``/health`` answered.
    answering: bool = False

    @property
    def dev_build(self) -> bool:
        tag = (self.image or "").rpartition(":")[2] if ":" in (self.image or "") else ""
        return tag == "dev" or "dev" in (self.version or "")

    def owner(self) -> str:
        """Who runs it, said for a person: the Docker project, the process, or the port."""
        if self.source == "docker":
            what = f"Docker project `{self.project}`" if self.project else "Docker"
            container = f" (container `{self.container}`)" if not self.project else ""
            return f"{what}{container}, `{self.image}`" if self.image else what + container
        if self.source == "process":
            return f"process {self.pid}"
        return f"something on port {self.port}"

    def describe(self) -> str:
        """``Docker project `x`, `img:dev`, version 3.0.12, data in ~/.x, on port 8000``."""
        parts = [self.owner()]
        if self.version:
            parts.append(f"version {self.version}")
        parts.append(f"data in {tilde(self.data_path)}" if self.data_path else "data dir unknown")
        if self.port:
            parts.append(f"on port {self.port}")
        return ", ".join(parts)

    def wire(self) -> dict[str, Any]:
        body = asdict(self)
        body["owner"] = self.owner()
        body["description"] = self.describe()
        body["dev_build"] = self.dev_build
        return body


def tilde(path: str | None) -> str:
    if not path:
        return "unknown"
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + "/") else path


# ── this machine's own store ─────────────────────────────────────────────────


def store_id(data_dir: Path, *, create: bool = True) -> str | None:
    """The id of the store at ``data_dir``, written there first when ``create``."""
    path = data_dir.expanduser() / STORE_ID_FILE
    with contextlib.suppress(OSError):
        if found := path.read_text().strip():
            return found
    if not create or not data_dir.expanduser().is_dir():
        return None
    new = uuid.uuid4().hex
    try:
        with path.open("x", encoding="utf-8") as f:
            f.write(new + "\n")
    except FileExistsError:
        with contextlib.suppress(OSError):
            return path.read_text().strip() or None
        return None
    except OSError:
        return None
    return new


def same_store(hub: Hub, data_dir: Path, own_id: str | None) -> bool | None:
    """Whether ``hub`` writes to ``data_dir``; ``None`` when it can't be told."""
    if hub.store_id and own_id:
        return hub.store_id == own_id
    if hub.data_path:
        with contextlib.suppress(OSError):
            return Path(hub.data_path).expanduser().resolve() == data_dir.expanduser().resolve()
    return None


# ── looking ──────────────────────────────────────────────────────────────────


def _run(argv: list[str]) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def health(port: int, host: str = "127.0.0.1") -> dict[str, Any] | None:
    """What ``/health`` says on ``port``, or ``None`` when no hub answers there."""
    try:
        resp = httpx.get(f"http://{host}:{port}/health", timeout=TIMEOUT_S)
        body = resp.json() if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("service") != "mycelium-backend":
        return None
    return body


def _apply_health(hub: Hub, body: dict[str, Any]) -> None:
    hub.answering = True
    hub.version = hub.version or body.get("version")
    storage = body.get("storage") or {}
    hub.store_id = hub.store_id or storage.get("id")
    if not hub.data_path:
        if storage.get("host_path"):
            hub.data_path = os.path.expanduser(storage["host_path"])
        elif hub.source == "process" or not str(storage.get("path", "")).startswith(
            CONTAINER_DATA_DIR
        ):
            hub.data_path = storage.get("path")


def docker_hubs() -> list[Hub]:
    """Running containers from a Mycelium backend image or its compose service."""
    if shutil.which("docker") is None:
        return []
    listed = _run(
        [
            "docker",
            "ps",
            "--no-trunc",
            "--format",
            '{{.ID}}\t{{.Image}}\t{{.Label "com.docker.compose.service"}}',
        ]
    )
    if not listed:
        return []
    ids = []
    for line in listed.splitlines():
        cid, image, service = [*line.split("\t"), "", ""][:3]
        if service == COMPOSE_SERVICE or "mycelium-backend" in image:
            ids.append(cid)
    if not ids:
        return []
    inspected = _run(["docker", "inspect", *ids])
    try:
        containers = json.loads(inspected or "[]")
    except ValueError:
        return []
    return [_from_container(c) for c in containers if isinstance(c, dict)]


def _from_container(c: dict[str, Any]) -> Hub:
    config = c.get("Config") or {}
    labels = config.get("Labels") or {}
    data_path = next(
        (
            m.get("Source")
            for m in c.get("Mounts") or []
            if m.get("Destination") == CONTAINER_DATA_DIR
        ),
        None,
    )
    port = None
    for binding in ((c.get("NetworkSettings") or {}).get("Ports") or {}).get("8000/tcp") or []:
        with contextlib.suppress(TypeError, ValueError):
            port = int(binding.get("HostPort"))
            break
    return Hub(
        source="docker",
        port=port,
        data_path=data_path,
        image=config.get("Image"),
        project=labels.get("com.docker.compose.project"),
        container=str(c.get("Name") or "").lstrip("/") or str(c.get("Id", ""))[:12],
    )


def _in_container(pid: int) -> bool:
    """Linux shows a container's processes too; those are Docker's to report."""
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return False
    return any(word in cgroup for word in ("docker", "containerd", "kubepods", "libpod"))


def _environ(pid: int, name: str) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    for entry in raw.split(b"\0"):
        key, _, value = entry.decode(errors="replace").partition("=")
        if key == name:
            return value
    return None


def process_hubs(ps_output: str | None = None) -> list[Hub]:
    """Hub processes on this machine outside any container, one per port."""
    listed = ps_output if ps_output is not None else _run(["ps", "-axo", "pid=,command="])
    hubs: dict[int, Hub] = {}
    me = os.getpid()
    for line in (listed or "").splitlines():
        pid_s, _, command = line.strip().partition(" ")
        if not pid_s.isdigit() or not _PROCESS.search(command):
            continue
        pid = int(pid_s)
        if pid == me or _in_container(pid):
            continue
        found = _PORT_ARG.search(command)
        port = int(found.group(1)) if found else 8000
        if port in hubs:
            continue  # `uv run` and the uvicorn under it, say
        hubs[port] = Hub(
            source="process", port=port, pid=pid, data_path=_environ(pid, "MYCELIUM_DATA_DIR")
        )
    return list(hubs.values())


def find_hubs(port: int = 8000, *, docker: bool = True, processes: bool = True) -> list[Hub]:
    """Every hub this machine can see, the one answering on ``port`` first."""
    hubs = (docker_hubs() if docker else []) + (process_hubs() if processes else [])
    answered: dict[int, dict[str, Any] | None] = {}
    for hub in hubs:
        if hub.port is None:
            continue
        if hub.port not in answered:
            answered[hub.port] = health(hub.port)
        if body := answered[hub.port]:
            _apply_health(hub, body)
    if port not in answered:
        answered[port] = health(port)
        if body := answered[port]:
            seen = Hub(source="port", port=port)
            _apply_health(seen, body)
            hubs.append(seen)
    return sorted(hubs, key=lambda h: (h.port != port, h.source != "docker"))


def at_port(hubs: list[Hub], port: int) -> Hub | None:
    """The hub that answers on ``port``, if any did."""
    return next((h for h in hubs if h.port == port and h.answering), None)


# ── what to say ──────────────────────────────────────────────────────────────


def stale(hub: Hub, app_version: str) -> str | None:
    """Why ``hub``'s version deserves a look next to ``app_version``, if it does."""
    if hub.dev_build:
        return "a development build"
    have, want = version_tuple(hub.version), version_tuple(app_version)
    if have and want and "dev" not in app_version and have < want:
        return f"older than this Mycelium ({app_version})"
    return None


def warnings(hubs: list[Hub], data_dir: Path, app_version: str) -> list[str]:
    """What a person should hear about these hubs, one sentence each."""
    said: list[str] = []
    if len(hubs) > 1:
        said.append(
            f"{len(hubs)} Mycelium hubs are running on this machine; "
            "only the one on the app's port gets its writes."
        )
    own = store_id(data_dir, create=False)
    for hub in hubs:
        if same_store(hub, data_dir, own) is False:
            said.append(
                f"{hub.owner()} writes to {tilde(hub.data_path)}, not {tilde(str(data_dir))}."
            )
        if why := stale(hub, app_version):
            said.append(f"{hub.owner()} is {why} (version {hub.version or 'unknown'}).")
    return said
