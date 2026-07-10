"""Transport-agnostic command execution against a pyATS testbed device.

Every E2E adapter dispatch funnels through :func:`execute`, which reads the
device's ``custom.transport`` hint to choose between three execution paths:

- ``local``  - run on the runner host with :mod:`subprocess`.
- ``docker`` - run via ``docker exec <container> ...``.
- ``ssh``    - run via ``ssh <user@ip> ...``.

The function accepts either a real :class:`pyats.topology.Device` or any
plain dict / namespace exposing a ``custom`` mapping. That keeps unit tests
free of the pyATS bootstrap and lets callers without a Device handy
construct a tiny adapter on the fly.

Design notes
------------

* The function returns :class:`subprocess.CompletedProcess` so callers can
  inspect ``returncode``, ``stdout`` and ``stderr`` uniformly across
  transports. Existing :class:`libs.mycelium_cli.CLIResult` wrappers can be
  built on top.
* Failures to dispatch (missing ssh key, unknown transport, missing
  container) raise :class:`HostExecError` rather than returning a fake
  result, so the caller can decide whether to ``self.skipped(...)`` or
  fail the test.
* Process timeouts surface as :class:`subprocess.TimeoutExpired` for
  parity with stdlib ``subprocess.run``.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


# pyATS supports ``%ENV{VAR, default}`` substitution in datafiles but NOT
# in testbed ``custom:`` blocks. We honor the same syntax here so
# operators can write one consistent form across both file types.
_ENV_PATTERN = re.compile(r"%ENV\{\s*([A-Z_][A-Z0-9_]*)\s*(?:,\s*([^}]*?)\s*)?\}")


def _resolve_env(value: Any) -> Any:
    """Substitute ``%ENV{VAR, default}`` markers in a string value.

    Non-string values pass through unchanged. Missing env vars fall
    back to the default; missing both env and default yields an empty
    string (matching pyATS datafile semantics).
    """
    if not isinstance(value, str):
        return value

    def _sub(match: re.Match[str]) -> str:
        var, default = match.group(1), match.group(2) or ""
        return os.environ.get(var, default)

    return _ENV_PATTERN.sub(_sub, value)


SSH_DEFAULT_KEY = os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem")
SSH_DEFAULT_USER = os.environ.get("SSH_USER", "ubuntu")
SSH_DEFAULT_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "5"))

DEFAULT_PATH_PREPEND = "$HOME/.local/bin:$HOME/.nvm/versions/node/current/bin"


class HostExecError(RuntimeError):
    """A command could not be dispatched (vs. running and failing)."""


@dataclass(frozen=True)
class _ResolvedTransport:
    """Internal: normalized view of a device's custom block."""

    transport: str
    container: str | None
    ssh_ip: str | None
    ssh_user: str
    ssh_key: str
    ssh_connect_timeout: int
    path_prepend: str
    exec_user: str | None
    exec_home: str | None


def _custom_mapping(device: Any) -> Mapping[str, Any]:
    """Pull a dict-like custom block out of a device.

    pyATS exposes ``device.custom`` as an ``AttrDict`` that supports
    both attribute and item access; for tests we accept a plain dict
    or a namespace whose ``custom`` attribute is a Mapping.
    """
    if isinstance(device, Mapping):
        if "custom" in device:
            inner = device["custom"]
            if isinstance(inner, Mapping):
                return inner
        return device

    custom = getattr(device, "custom", None)
    if custom is None:
        return {}
    if isinstance(custom, Mapping):
        return custom
    # pyATS AttrDict: convert via to_dict() or vars(). Use vars() to keep
    # the dependency loose - pyATS is heavy and we don't want to import
    # it from the executor.
    try:
        return dict(custom)
    except (TypeError, ValueError):
        return vars(custom)


def _resolve(device: Any) -> _ResolvedTransport:
    raw = _custom_mapping(device)

    def get(key: str) -> Any:
        """Read a custom field with %ENV{VAR, default} substitution applied."""
        return _resolve_env(raw.get(key))

    transport = (get("transport") or "local").lower()
    if transport not in {"local", "docker", "ssh"}:
        raise HostExecError(f"unknown transport {transport!r} (expected local|docker|ssh)")

    container = get("container")
    if transport == "docker" and not container:
        raise HostExecError("transport=docker requires custom.container")

    ssh_ip = get("ssh_ip") or get("ip")
    if transport == "ssh" and not ssh_ip:
        raise HostExecError("transport=ssh requires custom.ssh_ip")

    return _ResolvedTransport(
        transport=transport,
        container=container,
        ssh_ip=ssh_ip,
        ssh_user=get("ssh_user") or SSH_DEFAULT_USER,
        ssh_key=get("ssh_key") or SSH_DEFAULT_KEY,
        ssh_connect_timeout=int(get("ssh_connect_timeout") or SSH_DEFAULT_CONNECT_TIMEOUT),
        path_prepend=get("path_prepend") or DEFAULT_PATH_PREPEND,
        exec_user=get("exec_user") or ("spoke" if transport == "docker" else None),
        exec_home=get("exec_home") or ("/home/spoke" if transport == "docker" else None),
    )


def _shell_wrap(cmd: str, path_prepend: str, *, home: str | None = None) -> str:
    """Wrap a shell command with PATH plumbing for non-interactive shells.

    Both cursor-agent (installed via ``npm i -g`` or ``curl`` under nvm)
    and the mycelium CLI (installed via ``uv tool install`` into
    ``~/.local/bin``) live outside the default non-interactive PATH on
    most spoke hosts, so we always prepend a known set of directories
    and source ``nvm.sh`` if present.
    """
    home_export = f'export HOME="{home}"; ' if home else ""
    prelude = (
        f"{home_export}"
        f'[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1; export PATH="{path_prepend}:$PATH"; '
    )
    return prelude + cmd


def _argv_to_shell(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in argv)


def execute(  # noqa: PLR0913 - keeps subprocess.run-style ergonomics
    device: Any,
    argv: Sequence[str] | str,
    *,
    shell: bool = False,
    timeout: float = 30.0,
    input: str | None = None,  # noqa: A002 - mirrors subprocess.run
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command on ``device`` via its configured transport.

    Args:
        device: A pyATS ``Device`` or any object exposing a ``custom``
            mapping with at minimum a ``transport`` key.
        argv: Command as a list of argv strings, or a single shell
            command string when ``shell=True``.
        shell: When ``True``, ``argv`` is a shell command. For docker
            and ssh transports this is wrapped with ``sh -c``; for
            local it sets ``subprocess.run(shell=True)``.
        timeout: Seconds. Raises :class:`subprocess.TimeoutExpired`.
        input: Optional stdin content (text).
        check: If ``True``, non-zero exit raises
            :class:`subprocess.CalledProcessError`.

    Returns:
        ``subprocess.CompletedProcess[str]`` with stdout/stderr captured.

    Raises:
        HostExecError: The transport could not be resolved.
        subprocess.TimeoutExpired: Wall clock exceeded ``timeout``.
        subprocess.CalledProcessError: When ``check=True`` and exit != 0.
    """
    rt = _resolve(device)

    if shell:
        if not isinstance(argv, str):
            raise HostExecError("shell=True requires argv to be a single command string")
        cmd_str = argv
    else:
        if isinstance(argv, str):
            raise HostExecError("shell=False requires argv to be a list of strings")
        cmd_str = _argv_to_shell(argv)

    if rt.transport == "local":
        full = cmd_str if shell else list(argv)  # type: ignore[arg-type]
        try:
            return subprocess.run(  # noqa: S603 - explicit shell flag, args validated above
                full,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input,
                check=check,
            )
        except FileNotFoundError as exc:
            # Executable not found on the local host — surface as HostExecError
            # so callers with `except HostExecError` handle it gracefully.
            # Common cause: container-only scripts (e.g. /openclaw/*.sh) being
            # invoked via transport=local on a bare host.
            raise HostExecError(f"command not found: {exc.filename!r}") from exc

    if rt.transport == "docker":
        # docker exec runs argv directly when given; for shell mode we
        # invoke ``sh -c`` so we get the PATH wrapping. Spoke images start
        # as root (cursor auth install) but all runtimes live under spoke.
        wrapped = _shell_wrap(cmd_str, rt.path_prepend, home=rt.exec_home)
        full: list[str] = ["docker", "exec", "-i"]
        if rt.exec_user:
            full.extend(["-u", rt.exec_user])
        if rt.exec_home:
            full.extend(["-e", f"HOME={rt.exec_home}"])
        full.extend([rt.container, "sh", "-c", wrapped])
        return subprocess.run(  # noqa: S603 - argv is a constructed list, not shell
            full,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
            check=check,
        )

    # ssh
    key_path = os.path.expanduser(rt.ssh_key)
    if not os.path.exists(key_path):
        raise HostExecError(f"ssh key not found: {key_path}")

    wrapped = _shell_wrap(cmd_str, rt.path_prepend)
    full = [
        "ssh",
        "-i",
        key_path,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={rt.ssh_connect_timeout}",
        f"{rt.ssh_user}@{rt.ssh_ip}",
        wrapped,
    ]
    return subprocess.run(  # noqa: S603 - argv is a constructed list, not shell
        full,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
        check=check,
    )


def describe(device: Any) -> str:
    """Return a short human-readable description of a device's transport.

    Useful for log messages: ``log.info("dispatch %s: %s", describe(device), argv)``.
    """
    try:
        rt = _resolve(device)
    except HostExecError as exc:
        return f"<unresolved transport: {exc}>"
    if rt.transport == "local":
        return "local"
    if rt.transport == "docker":
        return f"docker:{rt.container}"
    return f"ssh:{rt.ssh_user}@{rt.ssh_ip}"
