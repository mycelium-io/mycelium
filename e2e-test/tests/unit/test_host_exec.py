"""Unit tests for :mod:`libs.host_exec`.

The dispatcher is the single point of contact between adapter
provisioners and the runtime, so these tests pin down its behaviour
for all three transports plus the error paths.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs import host_exec
from libs.host_exec import HostExecError

# ── helpers ──────────────────────────────────────────────────────────


def _device(**custom) -> SimpleNamespace:
    """Build a minimal device-like object with the requested custom block."""
    return SimpleNamespace(custom=custom, name="dev0")


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── transport dispatch ──────────────────────────────────────────────


def test_local_transport_runs_argv_directly():
    device = _device(transport="local")
    with patch("libs.host_exec.subprocess.run", return_value=_completed(0, "hi", "")) as run:
        result = host_exec.execute(device, ["echo", "hi"], timeout=5.0)

    assert result.returncode == 0
    assert result.stdout == "hi"
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0] == ["echo", "hi"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 5.0


def test_local_transport_shell_mode_passes_through():
    device = _device(transport="local")
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, "echo hi && date", shell=True)

    args, kwargs = run.call_args
    assert args[0] == "echo hi && date"
    assert kwargs["shell"] is True


def test_docker_transport_wraps_with_docker_exec_and_sh():
    device = _device(transport="docker", container="e2e-mycelium-spoke1")
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["mycelium", "agent", "ls"])

    args, _ = run.call_args
    full = args[0]
    assert full[:3] == ["docker", "exec", "-i"]
    assert full[3:5] == ["-u", "spoke"]
    assert full[5:7] == ["-e", "HOME=/home/spoke"]
    # One "-e VAR" pair per _DOCKER_PASSTHROUGH_ENV entry (CURSOR_API_KEY,
    # CURSOR_MODEL) comes next, before the container name — host_exec passes
    # the *names* through so docker inherits the values from its own
    # environment, it doesn't bake values in here.
    assert full[7:11] == ["-e", "CURSOR_API_KEY", "-e", "CURSOR_MODEL"]
    assert full[11] == "e2e-mycelium-spoke1"
    assert full[12] == "sh"
    assert full[13] == "-c"
    wrapped = full[14]
    assert "mycelium agent ls" in wrapped
    # PATH prelude is present so installed-via-uv binaries resolve
    assert "$HOME/.local/bin" in wrapped
    assert 'export HOME="/home/spoke"' in wrapped


def test_docker_transport_requires_container():
    device = _device(transport="docker")  # no container
    with pytest.raises(HostExecError, match="container"):
        host_exec.execute(device, ["echo", "hi"])


def test_ssh_transport_constructs_proper_ssh_invocation(tmp_path):
    key = tmp_path / "fake-key"
    key.write_text("fake")
    device = _device(
        transport="ssh",
        ssh_ip="10.0.50.171",
        ssh_user="ubuntu",
        ssh_key=str(key),
    )

    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["mycelium", "doctor"])

    args, _ = run.call_args
    full = args[0]
    assert full[0] == "ssh"
    assert "-i" in full and str(key) in full
    assert "ubuntu@10.0.50.171" in full
    # last element is the wrapped remote command
    assert "mycelium doctor" in full[-1]
    assert "$HOME/.local/bin" in full[-1]


def test_ssh_transport_requires_ssh_ip():
    device = _device(transport="ssh")
    with pytest.raises(HostExecError, match="ssh_ip"):
        host_exec.execute(device, ["echo", "hi"])


def test_ssh_transport_rejects_missing_key():
    device = _device(transport="ssh", ssh_ip="10.0.50.171", ssh_key="/nonexistent/key")
    with pytest.raises(HostExecError, match="ssh key not found"):
        host_exec.execute(device, ["echo", "hi"])


def test_unknown_transport_raises():
    device = _device(transport="carrier-pigeon")
    with pytest.raises(HostExecError, match="unknown transport"):
        host_exec.execute(device, ["echo", "hi"])


def test_default_transport_is_local_when_custom_missing():
    device = SimpleNamespace()  # no custom at all
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["echo", "hi"])
    args, kwargs = run.call_args
    assert args[0] == ["echo", "hi"]
    assert kwargs["shell"] is False


# ── argv/shell validation ───────────────────────────────────────────


def test_shell_requires_string_argv():
    device = _device(transport="local")
    with pytest.raises(HostExecError, match="single command string"):
        host_exec.execute(device, ["echo", "hi"], shell=True)


def test_non_shell_requires_list_argv():
    device = _device(transport="local")
    with pytest.raises(HostExecError, match="list of strings"):
        host_exec.execute(device, "echo hi")


# ── dict-shaped device ──────────────────────────────────────────────


def test_dict_device_is_accepted():
    """Plain dicts should work too, to keep tests trivial."""
    device = {"transport": "local"}
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["echo", "hi"])
    run.assert_called_once()


def test_dict_with_custom_key_is_accepted():
    device = {"custom": {"transport": "local"}}
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["echo", "hi"])
    run.assert_called_once()


# ── %ENV{} substitution in custom fields ────────────────────────────


def test_env_substitution_resolves_from_environment(tmp_path, monkeypatch):
    """%ENV{VAR, default} in custom values must read os.environ at exec time."""
    key = tmp_path / "fake-key"
    key.write_text("fake")
    monkeypatch.setenv("E2E_TEST_HOST", "192.168.99.99")
    device = _device(
        transport="ssh",
        ssh_ip="%ENV{E2E_TEST_HOST, 10.0.0.1}",
        ssh_user="ubuntu",
        ssh_key=str(key),
    )
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["true"])

    args, _ = run.call_args
    assert "ubuntu@192.168.99.99" in args[0]


def test_env_substitution_falls_back_to_default(tmp_path, monkeypatch):
    """When the env var is unset, %ENV uses its default value."""
    key = tmp_path / "fake-key"
    key.write_text("fake")
    monkeypatch.delenv("E2E_UNSET_HOST", raising=False)
    device = _device(
        transport="ssh",
        ssh_ip="%ENV{E2E_UNSET_HOST, 10.0.0.7}",
        ssh_user="ubuntu",
        ssh_key=str(key),
    )
    with patch("libs.host_exec.subprocess.run", return_value=_completed()) as run:
        host_exec.execute(device, ["true"])

    args, _ = run.call_args
    assert "ubuntu@10.0.0.7" in args[0]


# ── describe() ──────────────────────────────────────────────────────


def test_describe_local():
    assert host_exec.describe(_device(transport="local")) == "local"


def test_describe_docker():
    assert host_exec.describe(_device(transport="docker", container="c1")) == "docker:c1"


def test_describe_ssh():
    assert host_exec.describe(_device(transport="ssh", ssh_ip="10.0.0.1", ssh_user="u")) == "ssh:u@10.0.0.1"


def test_describe_returns_diagnostic_on_unresolved():
    assert "transport" in host_exec.describe(_device(transport="bogus"))
