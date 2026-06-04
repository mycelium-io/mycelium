"""Unit tests for :mod:`libs.provisioners.cursor`.

All ``host_exec.execute`` calls are stubbed via :mod:`unittest.mock`.
Each test asserts both the resulting :class:`AgentRef` state and the
exact CLI arguments dispatched, so a future refactor of
``libs.cursor`` flag names will surface as a clear test failure.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.provisioners import PrereqMissing
from libs.provisioners.cursor import CursorProvisioner


def _device(**custom) -> SimpleNamespace:
    return SimpleNamespace(custom={"transport": "local", **custom}, name="hub")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


# ── check_prereqs ───────────────────────────────────────────────────


def test_check_prereqs_passes_when_all_present():
    prov = CursorProvisioner()
    responses = iter(
        [
            _ok("mycelium 1.2.3"),  # mycelium --version
            _ok("/home/me/.local/bin/cursor-agent\n"),  # which cursor-agent
            _ok("cc-daemon: active"),  # mycelium daemon status
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.check_prereqs(_device())


def test_check_prereqs_skips_when_cursor_agent_missing():
    prov = CursorProvisioner()
    responses = iter(
        [
            _ok("mycelium 1.2.3"),
            _fail("which: cursor-agent: not found"),
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="cursor-agent"):
            prov.check_prereqs(_device())


def test_check_prereqs_skips_when_daemon_dead():
    prov = CursorProvisioner()
    responses = iter(
        [
            _ok("mycelium 1.2.3"),
            _ok("/home/me/.local/bin/cursor-agent"),
            _fail("daemon socket: connection refused"),
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="daemon"):
            prov.check_prereqs(_device())


# ── create_agent ────────────────────────────────────────────────────


def test_create_agent_creates_workspace_and_subscribes_daemon():
    prov = CursorProvisioner()
    calls: list[list[str]] = []

    def fake_execute(_device, argv, **_kwargs):
        calls.append(list(argv))
        if argv[0] == "mktemp":
            return _ok(stdout="/tmp/cursor-e2e-abc123\n")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        ref = prov.create_agent(_device(), handle="cu-1", room="r1")

    assert ref.handle == "cu-1"
    assert ref.adapter == "cursor"
    assert ref.metadata["workspace"] == "/tmp/cursor-e2e-abc123"
    assert ref.metadata["room"] == "r1"

    # CLI ordering matters: subscribe BEFORE create_agent so the
    # daemon doesn't miss the first tick.
    cli_calls = [c for c in calls if c[0] == "mycelium"]
    subscribe_idx = next(i for i, c in enumerate(cli_calls) if c[:3] == ["mycelium", "daemon", "subscribe"])
    create_idx = next(i for i, c in enumerate(cli_calls) if c[:3] == ["mycelium", "agent", "create"])
    assert subscribe_idx < create_idx


def test_create_agent_passes_workspace_to_agent_create():
    prov = CursorProvisioner()

    def fake_execute(_device, argv, **_kwargs):
        if argv[0] == "mktemp":
            return _ok(stdout="/tmp/cursor-e2e-xyz789")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute) as exec_mock:
        prov.create_agent(_device(), handle="cu-2", room="r-x")

    create_calls = [c.args[1] for c in exec_mock.call_args_list if c.args[1][:3] == ["mycelium", "agent", "create"]]
    assert len(create_calls) == 1
    argv = create_calls[0]
    assert "--cwd" in argv
    assert argv[argv.index("--cwd") + 1] == "/tmp/cursor-e2e-xyz789"
    assert "--room" in argv and argv[argv.index("--room") + 1] == "r-x"


def test_create_agent_rejects_bogus_workspace_path():
    prov = CursorProvisioner()

    def fake_execute(_device, argv, **_kwargs):
        if argv[0] == "mktemp":
            # Malicious mktemp output that doesn't match the safe prefix
            return _ok(stdout="/etc/passwd")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="unexpected path"):
            prov.create_agent(_device(), handle="cu-evil", room="r1")


def test_create_agent_propagates_create_failure():
    prov = CursorProvisioner()
    responses = iter(
        [
            _ok("/tmp/cursor-e2e-abc123"),  # mktemp
            _ok(),  # daemon subscribe
            _fail("agent create: room not found"),  # agent create
        ]
    )

    def fake_execute(_device, _argv, **_kwargs):
        return next(responses)

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="agent create"):
            prov.create_agent(_device(), handle="cu-3", room="bogus")


# ── wake_agent ──────────────────────────────────────────────────────


def test_wake_agent_invokes_with_room():
    prov = CursorProvisioner()
    ref = _make_ref()

    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        prov.wake_agent(_device(), ref, session_room="r-sess")

    argv = exec_mock.call_args.args[1]
    assert argv[:4] == ["mycelium", "agent", "invoke", ref.handle]
    assert "--room" in argv
    assert argv[argv.index("--room") + 1] == "r-sess"


def test_wake_agent_swallows_dispatch_failures(caplog):
    prov = CursorProvisioner()
    ref = _make_ref()

    def boom(*_args, **_kwargs):
        from libs.host_exec import HostExecError

        raise HostExecError("ssh broken")

    with patch("libs.host_exec.execute", side_effect=boom):
        prov.wake_agent(_device(), ref, session_room="r-sess")  # no raise

    assert any("dispatch failed" in r.message for r in caplog.records)


# ── cleanup_agent ───────────────────────────────────────────────────


def test_cleanup_agent_runs_in_order():
    prov = CursorProvisioner()
    ref = _make_ref(workspace="/tmp/cursor-e2e-cleanup")
    calls: list[list[str]] = []

    def fake_execute(_device, argv, **_kwargs):
        calls.append(list(argv))
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.cleanup_agent(_device(), ref, room="r1")

    assert calls[0][:3] == ["mycelium", "agent", "rm"]
    assert calls[1][:3] == ["mycelium", "daemon", "unsubscribe"]
    assert calls[2][:2] == ["rm", "-rf"]
    assert calls[2][-1] == "/tmp/cursor-e2e-cleanup"


def test_cleanup_agent_refuses_unsafe_workspace(caplog):
    prov = CursorProvisioner()
    ref = _make_ref(workspace="/etc")  # NOT cursor-e2e prefix
    calls: list[list[str]] = []

    def fake_execute(_device, argv, **_kwargs):
        calls.append(list(argv))
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.cleanup_agent(_device(), ref, room="r1")

    # rm -rf must never run for a non-cursor-e2e path
    rm_calls = [c for c in calls if c[:2] == ["rm", "-rf"]]
    assert rm_calls == []
    assert any("refusing to remove" in r.message for r in caplog.records)


# ── helpers ─────────────────────────────────────────────────────────


def _make_ref(**meta) -> "AgentRef":  # noqa: F821 - quoted forward ref
    from libs.provisioners.base import AgentRef

    metadata = {"workspace": "/tmp/cursor-e2e-default", "room": "r1", **meta}
    return AgentRef(
        handle="cu-test",
        adapter="cursor",
        device_name="hub",
        metadata=metadata,
    )
