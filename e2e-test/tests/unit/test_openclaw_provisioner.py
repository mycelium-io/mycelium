"""Unit tests for :mod:`libs.provisioners.openclaw`.

Covers prereq checks, idempotent create_agent (verify-only in stage 1),
the wake_agent role gate, and cleanup best-effort semantics. All
subprocess calls are stubbed via :mod:`unittest.mock` so the tests run
without any infrastructure.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.provisioners import PrereqMissing
from libs.provisioners.openclaw import OpenClawProvisioner


def _device(role: str = "hub", **extra) -> SimpleNamespace:
    custom = {"transport": "local", "role": role, **extra}
    return SimpleNamespace(custom=custom, name="hub")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


# ── check_prereqs ───────────────────────────────────────────────────


def test_check_prereqs_passes_when_cli_present():
    prov = OpenClawProvisioner()
    with patch("libs.host_exec.execute", return_value=_ok("mycelium 1.2.3")):
        prov.check_prereqs(_device())


def test_check_prereqs_raises_when_cli_missing():
    prov = OpenClawProvisioner()
    with patch("libs.host_exec.execute", return_value=_fail("command not found")):
        with pytest.raises(PrereqMissing, match="--version"):
            prov.check_prereqs(_device())


# ── create_agent ────────────────────────────────────────────────────


def test_create_agent_returns_ref_when_handle_present():
    prov = OpenClawProvisioner()
    listing = "agent-alpha   openclaw   ready\nagent-beta    openclaw   ready"
    with patch("libs.host_exec.execute", return_value=_ok(listing)) as mock_exec:
        ref = prov.create_agent(_device(), handle="agent-alpha", room="r1")
    assert ref.handle == "agent-alpha"
    assert ref.adapter == "openclaw"
    assert ref.metadata["room"] == "r1"
    # Matrix token env follows the canonical convention
    assert ref.metadata["matrix_token_env"] == "MATRIX_TOKEN_AGENT_ALPHA"
    # Regression: must pass --room so ``mycelium agent ls`` doesn't
    # exit 1 with "No room specified" on a device with no active room.
    argv = mock_exec.call_args[0][1]
    assert "--room" in argv
    assert "r1" in argv


def test_create_agent_raises_when_handle_absent():
    prov = OpenClawProvisioner()
    with patch("libs.host_exec.execute", return_value=_ok("only-other-agent")):
        with pytest.raises(PrereqMissing, match="agent-alpha"):
            prov.create_agent(_device(), handle="agent-alpha", room="r1")


# ── wake_agent role gate ────────────────────────────────────────────


def _consume_coro(coro, *_args, **_kwargs):
    """asyncio.run replacement that consumes the coroutine without awaiting it.

    Prevents ``RuntimeWarning: coroutine was never awaited`` from polluting
    test output when we patch out the real Matrix dispatch.
    """
    if hasattr(coro, "close"):
        coro.close()


def test_wake_agent_noop_for_hub_role():
    prov = OpenClawProvisioner()
    ref = _make_ref()
    # Should not attempt any Matrix call at all when role=hub
    with patch("libs.provisioners.openclaw.asyncio.run", side_effect=_consume_coro) as run:
        prov.wake_agent(_device(role="hub"), ref, session_room="r-sess")
    run.assert_not_called()


def test_wake_agent_skips_when_matrix_env_missing(monkeypatch):
    prov = OpenClawProvisioner()
    ref = _make_ref()
    # No MATRIX_URL / E2E_MATRIX_ROOM_ID / token in env
    for var in ("MATRIX_URL", "E2E_MATRIX_ROOM_ID", "MATRIX_TOKEN_AGENT_ALPHA"):
        monkeypatch.delenv(var, raising=False)

    with patch("libs.provisioners.openclaw.asyncio.run", side_effect=_consume_coro) as run:
        prov.wake_agent(_device(role="spoke"), ref, session_room="r-sess")

    run.assert_not_called()


def test_wake_agent_posts_matrix_dm_when_spoke_and_env_set(monkeypatch):
    prov = OpenClawProvisioner()
    ref = _make_ref()
    monkeypatch.setenv("MATRIX_URL", "http://localhost:8008")
    monkeypatch.setenv("E2E_MATRIX_ROOM_ID", "!room:local")
    monkeypatch.setenv("MATRIX_TOKEN_AGENT_ALPHA", "secret-token")

    with patch("libs.provisioners.openclaw.asyncio.run", side_effect=_consume_coro) as run:
        prov.wake_agent(_device(role="spoke"), ref, session_room="r-sess")

    run.assert_called_once()


# ── cleanup_agent ───────────────────────────────────────────────────


def test_cleanup_agent_swallows_dispatch_failures(caplog):
    prov = OpenClawProvisioner()
    ref = _make_ref()

    def raise_dispatch(*_args, **_kwargs):
        from libs.host_exec import HostExecError

        raise HostExecError("ssh broken")

    with patch("libs.host_exec.execute", side_effect=raise_dispatch):
        prov.cleanup_agent(_device(), ref, room="r1")
    # No exception; logged as warning
    assert any("list sessions failed" in rec.message for rec in caplog.records)


def test_cleanup_agent_resets_listed_sessions():
    prov = OpenClawProvisioner()
    ref = _make_ref()

    list_resp = _ok(
        stdout='[{"key": "mycelium-room:r1:session:abc"}, {"key": "irrelevant-session"}]',
    )
    reset_resp = _ok("ok")

    calls: list[tuple[tuple, dict]] = []

    def fake_execute(device, argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        if argv[:2] == ["openclaw", "sessions"]:
            return list_resp
        if argv[:2] == ["openclaw", "gateway"]:
            return reset_resp
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.cleanup_agent(_device(), ref, room="r1")

    # First call lists, second call resets only the mycelium-room session
    reset_calls = [c for c in calls if c[0][:2] == ("openclaw", "gateway")]
    assert len(reset_calls) == 1
    assert "mycelium-room:r1:session:abc" in reset_calls[0][0][-1]


# ── helpers ─────────────────────────────────────────────────────────


def _make_ref():
    from libs.provisioners.base import AgentRef

    return AgentRef(
        handle="agent-alpha",
        adapter="openclaw",
        device_name="hub",
        metadata={
            "matrix_token_env": "MATRIX_TOKEN_AGENT_ALPHA",
            "room": "r1",
        },
    )
