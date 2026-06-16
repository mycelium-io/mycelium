"""Unit tests for :mod:`libs.provisioners.hermes`."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.host_exec import HostExecError
from libs.provisioners import PrereqMissing
from libs.provisioners.base import BOOTSTRAP_ROOM, AgentRef
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


# ── ensure_runtime ──────────────────────────────────────────────────


def test_ensure_runtime_skips_create_when_handle_already_present():
    prov = HermesProvisioner()

    with patch(
        "libs.host_exec.execute",
        return_value=_ok("@he-1  hermes\n"),
    ) as exec_mock:
        ref = prov.ensure_runtime(_device(), handle="he-1")

    assert ref.handle == "he-1"
    assert ref.metadata["pre_existing"] is True
    assert ref.metadata["bootstrap_room"] == BOOTSTRAP_ROOM
    argv = exec_mock.call_args.args[1]
    assert argv == ["mycelium", "agent", "ls", "--room", BOOTSTRAP_ROOM]


def test_ensure_runtime_creates_agent_in_bootstrap_room():
    prov = HermesProvisioner()
    responses = iter(
        [
            _ok("no agents"),  # agent ls
            _ok(),  # agent create
        ]
    )

    def fake_execute(_device, argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute) as exec_mock:
        ref = prov.ensure_runtime(_device(), handle="he-1")

    assert ref.handle == "he-1"
    assert ref.metadata["pre_existing"] is False
    create_argv = exec_mock.call_args_list[1].args[1]
    assert create_argv == [
        "mycelium",
        "agent",
        "create",
        "he-1",
        "--adapter",
        "hermes",
        "--room",
        BOOTSTRAP_ROOM,
    ]


def test_ensure_runtime_surfaces_create_failure():
    prov = HermesProvisioner()
    responses = iter(
        [
            _ok("no agents"),
            _fail(stderr="hermes-gateway: timed out waiting for plugin restart"),
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="hermes-gateway"):
            prov.ensure_runtime(_device(), handle="he-down")


def test_ensure_runtime_uses_generous_timeout_on_create():
    prov = HermesProvisioner()
    responses = iter([_ok("no agents"), _ok()])

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute) as exec_mock:
        prov.ensure_runtime(_device(), handle="he-2")

    create_call = exec_mock.call_args_list[1]
    assert create_call.kwargs.get("timeout", 0) >= 30


# ── register_in_room ───────────────────────────────────────────────


def test_register_in_room_returns_ref_with_room_metadata():
    prov = HermesProvisioner()

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        ref = prov.register_in_room(_device(), handle="he-1", room="r1")

    assert ref.handle == "he-1"
    assert ref.adapter == "hermes"
    assert ref.metadata == {"room": "r1"}

    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "agent", "create"]
    assert "--adapter" in argv
    assert argv[argv.index("--adapter") + 1] == "hermes"
    assert "--room" in argv
    assert argv[argv.index("--room") + 1] == "r1"


def test_register_in_room_surfaces_subscription_failure():
    prov = HermesProvisioner()

    with patch(
        "libs.host_exec.execute",
        return_value=_fail(stderr="hermes-gateway: timed out waiting for plugin restart"),
    ):
        with pytest.raises(PrereqMissing, match="room subscription"):
            prov.register_in_room(_device(), handle="he-down", room="r2")


# ── wake_agent ──────────────────────────────────────────────────────


def test_wake_agent_is_noop():
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute") as exec_mock:
        prov.wake_agent(_device(), ref, session_room="r-sess")

    exec_mock.assert_not_called()


# ── unregister_from_room ────────────────────────────────────────────


def test_unregister_from_room_removes_via_cli():
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        prov.unregister_from_room(_device(), ref, room="r1")

    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "agent", "rm"]
    assert "--force" in argv
    assert "--room" in argv and argv[argv.index("--room") + 1] == "r1"


def test_unregister_from_room_swallows_failures(caplog):
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute", return_value=_fail("rm failed")):
        prov.unregister_from_room(_device(), ref, room="r1")  # no raise

    assert any("unregister_from_room" in r.message and "agent rm" in r.message for r in caplog.records)


def test_unregister_from_room_swallows_dispatch_errors(caplog):
    prov = HermesProvisioner()
    ref = AgentRef(handle="he-1", adapter="hermes", device_name="hub", metadata={})

    with patch("libs.host_exec.execute", side_effect=HostExecError("ssh down")):
        prov.unregister_from_room(_device(), ref, room="r1")

    assert any("unregister_from_room" in r.message for r in caplog.records)


# ── teardown_runtime ────────────────────────────────────────────────


def test_teardown_runtime_skips_pre_existing_agents():
    prov = HermesProvisioner()
    ref = AgentRef(
        handle="he-1",
        adapter="hermes",
        device_name="hub",
        metadata={"pre_existing": True, "bootstrap_room": BOOTSTRAP_ROOM},
    )

    with patch("libs.host_exec.execute") as exec_mock:
        prov.teardown_runtime(_device(), ref)

    exec_mock.assert_not_called()


def test_teardown_runtime_removes_from_bootstrap_room():
    prov = HermesProvisioner()
    ref = AgentRef(
        handle="he-1",
        adapter="hermes",
        device_name="hub",
        metadata={"bootstrap_room": BOOTSTRAP_ROOM, "pre_existing": False},
    )

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        prov.teardown_runtime(_device(), ref)

    argv = exec_mock.call_args.args[1]
    assert argv == ["mycelium", "agent", "rm", "he-1", "--room", BOOTSTRAP_ROOM, "--force"]
