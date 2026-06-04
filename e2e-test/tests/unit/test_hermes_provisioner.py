"""Unit tests for :mod:`libs.provisioners.hermes`."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.provisioners import PrereqMissing
from libs.provisioners.base import AgentRef
from libs.provisioners.hermes import HermesProvisioner


def _device() -> SimpleNamespace:
    return SimpleNamespace(custom={"transport": "local"}, name="hub")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "boom", stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=stderr)


# ── check_prereqs ───────────────────────────────────────────────────


def test_check_prereqs_ok_when_adapter_registered():
    prov = HermesProvisioner()
    responses = iter(
        [
            _ok("mycelium 1.2.3"),
            _ok("Installed adapters:\n  - openclaw\n  - hermes\n"),
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.check_prereqs(_device())


def test_check_prereqs_fails_when_adapter_missing():
    prov = HermesProvisioner()
    responses = iter(
        [
            _ok("mycelium 1.2.3"),
            _ok("Installed adapters:\n  - openclaw\n"),  # no hermes
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="not registered"):
            prov.check_prereqs(_device())


def test_check_prereqs_fails_when_mycelium_cli_missing():
    prov = HermesProvisioner()

    with patch("libs.host_exec.execute", return_value=_fail("mycelium: command not found")):
        with pytest.raises(PrereqMissing, match="mycelium"):
            prov.check_prereqs(_device())


# ── create_agent ────────────────────────────────────────────────────


def test_create_agent_returns_ref_with_room_metadata():
    prov = HermesProvisioner()

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        ref = prov.create_agent(_device(), handle="he-1", room="r1")

    assert ref.handle == "he-1"
    assert ref.adapter == "hermes"
    assert ref.metadata == {"room": "r1"}

    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "agent", "create"]
    assert "--adapter" in argv
    assert argv[argv.index("--adapter") + 1] == "hermes"
    assert "--room" in argv
    assert argv[argv.index("--room") + 1] == "r1"


def test_create_agent_surfaces_install_failure():
    prov = HermesProvisioner()

    with patch(
        "libs.host_exec.execute",
        return_value=_fail(stderr="hermes-gateway: timed out waiting for plugin restart"),
    ):
        with pytest.raises(PrereqMissing, match="hermes-gateway"):
            prov.create_agent(_device(), handle="he-down", room="r2")


def test_create_agent_uses_generous_timeout():
    prov = HermesProvisioner()

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        prov.create_agent(_device(), handle="he-2", room="r3")

    # Installer wait-and-verify can take ~20s; 60s timeout is the floor.
    assert exec_mock.call_args.kwargs.get("timeout", 0) >= 30


# ── wake_agent ──────────────────────────────────────────────────────


def test_wake_agent_is_noop():
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute") as exec_mock:
        prov.wake_agent(_device(), ref, session_room="r-sess")

    exec_mock.assert_not_called()


# ── cleanup_agent ───────────────────────────────────────────────────


def test_cleanup_agent_removes_via_cli():
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        prov.cleanup_agent(_device(), ref, room="r1")

    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "agent", "rm"]
    assert "--force" in argv
    assert "--room" in argv and argv[argv.index("--room") + 1] == "r1"


def test_cleanup_agent_swallows_failures(caplog):
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute", return_value=_fail("rm failed")):
        prov.cleanup_agent(_device(), ref, room="r1")  # no raise

    assert any("agent rm" in r.message for r in caplog.records)
