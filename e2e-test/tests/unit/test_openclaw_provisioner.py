"""Unit tests for :mod:`libs.provisioners.openclaw`.

Covers the two-phase lifecycle introduced in the matrix refactor:
``ensure_runtime`` (heavy, idempotent, suite-level) and
``register_in_room`` (lightweight, per-test), plus
``unregister_from_room``, ``teardown_runtime``, the wake_agent role
gate, and cleanup best-effort semantics. All subprocess calls are
stubbed via :mod:`unittest.mock` so the tests run without any
infrastructure.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.provisioners import PrereqMissing
from libs.provisioners.base import BOOTSTRAP_ROOM, AgentRef
from libs.provisioners.openclaw import OpenClawProvisioner


def _device(role: str = "hub", **extra) -> SimpleNamespace:
    custom = {"transport": "local", "role": role, **extra}
    return SimpleNamespace(custom=custom, name="hub")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "boom", rc: int = 1) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout="", stderr=stderr)


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


# ── ensure_runtime ──────────────────────────────────────────────────


def _is_chown(argv) -> bool:
    """Match the chown best-effort step in ``ensure_bootstrap_room``.

    ``argv`` may be a list (argv form) or a plain str (shell form);
    the chown is always passed as a single shell-quoted string, so we
    just substring-check.
    """
    s = argv if isinstance(argv, str) else " ".join(argv)
    return "chown" in s


def test_ensure_runtime_short_circuits_when_agent_already_present():
    """Idempotent fast path: if ``openclaw agents list`` shows the handle, no
    create call is issued. This is the steady-state for repeated
    suite runs."""
    prov = OpenClawProvisioner()

    calls: list = []

    def fake_execute(_device, argv, **_kwargs):
        calls.append(argv if isinstance(argv, str) else list(argv))
        if _is_chown(argv):
            return _ok()
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("- agent-alpha\n- agent-beta")
        # If we reach here the test caught a regression — log enough to debug.
        raise AssertionError(f"unexpected call in fast path: {argv}")

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        ref = prov.ensure_runtime(_device(), handle="agent-alpha")

    assert ref.adapter == "openclaw"
    assert ref.handle == "agent-alpha"
    assert ref.metadata["bootstrap_room"] == BOOTSTRAP_ROOM
    assert ref.metadata["pre_existing"] is True
    # Specifically: no `agent create` call was made.
    list_calls = [c for c in calls if isinstance(c, list)]
    assert not any(c[:3] == ["mycelium", "agent", "create"] for c in list_calls)


def test_ensure_runtime_creates_when_agent_absent(monkeypatch):
    """Slow path: agent missing from bootstrap room → run
    ``mycelium agent create``. Seed agent (for --copy-auth-from)
    pulled from the canonical env var (fallback when no per-host
    override is set)."""
    monkeypatch.delenv("MYCELIUM_E2E_OPENCLAW_SEED_AGENT", raising=False)
    monkeypatch.setenv("MYCELIUM_E2E_OPENCLAW_SEED_AGENT", "seed-agent")

    prov = OpenClawProvisioner()
    calls: list = []

    def fake_execute(_device, argv, **_kwargs):
        calls.append(argv if isinstance(argv, str) else list(argv))
        if _is_chown(argv):
            return _ok()
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("")  # no agents configured
        if argv[:3] == ["mycelium", "agent", "create"]:
            return _ok("created")
        raise AssertionError(f"unexpected call: {argv}")

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        ref = prov.ensure_runtime(_device(), handle="agent-alpha")

    assert ref.metadata["pre_existing"] is False
    create_calls = [c for c in calls if isinstance(c, list) and c[:3] == ["mycelium", "agent", "create"]]
    assert len(create_calls) == 1
    create_argv = create_calls[0]
    # Sanity: handle + adapter + bootstrap room + seed flag are all on the argv.
    assert "agent-alpha" in create_argv
    assert "--adapter" in create_argv and "openclaw" in create_argv
    assert "--room" in create_argv and BOOTSTRAP_ROOM in create_argv
    assert "--copy-auth-from" in create_argv and "seed-agent" in create_argv


def test_ensure_runtime_prefers_device_custom_seed_over_env(monkeypatch):
    """Per-host ``custom.openclaw_seed_agent`` wins over the global
    env var so lab boxes with different pre-authed seeds work
    out of the box."""
    monkeypatch.setenv("MYCELIUM_E2E_OPENCLAW_SEED_AGENT", "shared-seed")
    prov = OpenClawProvisioner()

    captured: list[str] = []

    def fake_execute(_device, argv, **_kwargs):
        if isinstance(argv, str):
            captured.append(argv)
            return _ok()
        captured.extend(argv)
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("")
        if argv[:3] == ["mycelium", "agent", "create"]:
            return _ok("created")
        return _ok()

    # Device declares a per-host override.
    device = _device(role="spoke", openclaw_seed_agent="per-host-seed")
    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.ensure_runtime(device, handle="alpha")

    # ``per-host-seed`` should be on the argv, NOT ``shared-seed``.
    assert "per-host-seed" in captured
    assert "shared-seed" not in captured


def test_ensure_runtime_propagates_create_failure(monkeypatch):
    """Non-root-ownership failures are surfaced directly (no retry)."""
    monkeypatch.delenv("MYCELIUM_E2E_OPENCLAW_SEED_AGENT", raising=False)
    prov = OpenClawProvisioner()

    def fake_execute(_device, argv, **_kwargs):
        if _is_chown(argv):
            return _ok()
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("")
        if argv[:3] == ["mycelium", "agent", "create"]:
            return _fail("LLM auth missing", rc=2)
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        with pytest.raises(PrereqMissing, match="agent create failed"):
            prov.ensure_runtime(_device(), handle="agent-alpha")


def test_ensure_runtime_retries_on_root_ownership_race():
    """``agent create`` exits non-zero with "is owned by root" when
    the backend (in Docker) wrote the manifest as root before the
    CLI could update it. Retry once after a chown."""
    prov = OpenClawProvisioner()
    attempts: list[int] = []

    def fake_execute(_device, argv, **_kwargs):
        if _is_chown(argv):
            return _ok()
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("")
        if argv[:3] == ["mycelium", "agent", "create"]:
            attempts.append(1)
            if len(attempts) == 1:
                # First attempt loses the root-ownership race.
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="created OpenClaw agent agent-alpha",
                    stderr="✗ Cannot write to ./agents/agent-alpha.md is owned by root",
                )
            return _ok("created")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        ref = prov.ensure_runtime(_device(), handle="agent-alpha")

    assert ref.handle == "agent-alpha"
    assert ref.metadata["pre_existing"] is False
    # Exactly two create attempts: initial + retry.
    assert len(attempts) == 2


# ── register_in_room ────────────────────────────────────────────────


def test_register_in_room_calls_agent_add_with_room():
    prov = OpenClawProvisioner()
    with patch("libs.host_exec.execute", return_value=_ok("added")) as mock_exec:
        ref = prov.register_in_room(_device(), handle="agent-alpha", room="r1")

    assert ref.handle == "agent-alpha"
    assert ref.metadata["room"] == "r1"
    # Matrix token env follows the canonical convention
    assert ref.metadata["matrix_token_env"] == "MATRIX_TOKEN_AGENT_ALPHA"

    argv = mock_exec.call_args[0][1]
    assert argv[:3] == ["mycelium", "agent", "add"]
    assert "agent-alpha" in argv
    assert "--room" in argv and "r1" in argv


def test_register_in_room_raises_on_failure():
    prov = OpenClawProvisioner()
    with patch("libs.host_exec.execute", return_value=_fail("agent not found")):
        with pytest.raises(PrereqMissing, match="agent add"):
            prov.register_in_room(_device(), handle="agent-alpha", room="r1")


# ── legacy create_agent ─────────────────────────────────────────────


def test_create_agent_chains_ensure_runtime_and_register():
    """The legacy one-shot calls both phases so old callers keep
    working without knowing about the split."""
    prov = OpenClawProvisioner()
    seen: list = []

    def fake_execute(_device, argv, **_kwargs):
        seen.append(argv if isinstance(argv, str) else list(argv))
        if _is_chown(argv):
            return _ok()
        if argv[:3] == ["mycelium", "room", "create"]:
            return _ok()
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("- agent-alpha")  # already present
        if argv[:3] == ["mycelium", "agent", "add"]:
            return _ok("added")
        raise AssertionError(f"unexpected: {argv}")

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        ref = prov.create_agent(_device(), handle="agent-alpha", room="r1")

    assert ref.metadata["room"] == "r1"
    # Both ensure_runtime (agents list, no create) and register_in_room (add) ran.
    list_seen = [c for c in seen if isinstance(c, list)]
    assert any(c[:3] == ["openclaw", "agents", "list"] for c in list_seen)
    assert any(c[:3] == ["mycelium", "agent", "add"] for c in list_seen)


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


# ── unregister_from_room ─────────────────────────────────────────────


def test_unregister_from_room_calls_agent_rm_then_session_reset():
    """The new unregister combines the legacy ``cleanup_agent``
    session-reset with the manifest drop. Both should fire."""
    prov = OpenClawProvisioner()
    ref = _make_ref()

    seen: list[list[str]] = []

    def fake_execute(_device, argv, **_kwargs):
        seen.append(list(argv))
        if argv[:3] == ["mycelium", "agent", "rm"]:
            return _ok("removed")
        if argv[:2] == ["openclaw", "sessions"]:
            return _ok('[{"key": "mycelium-room:r1:session:abc"}]')
        if argv[:2] == ["openclaw", "gateway"]:
            return _ok("ok")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        prov.unregister_from_room(_device(), ref, room="r1")

    # 1) manifest drop ran
    rm_calls = [c for c in seen if c[:3] == ["mycelium", "agent", "rm"]]
    assert len(rm_calls) == 1
    assert "--room" in rm_calls[0] and "r1" in rm_calls[0]

    # 2) session reset ran for the mycelium-room session
    reset_calls = [c for c in seen if c[:2] == ["openclaw", "gateway"]]
    assert len(reset_calls) == 1
    assert "mycelium-room:r1:session:abc" in reset_calls[0][-1]


def test_unregister_from_room_swallows_rm_failure(caplog):
    """If the manifest drop fails we still try the session reset."""
    prov = OpenClawProvisioner()
    ref = _make_ref()

    def fake_execute(_device, argv, **_kwargs):
        if argv[:3] == ["mycelium", "agent", "rm"]:
            return _fail("not found")
        if argv[:2] == ["openclaw", "sessions"]:
            return _ok("[]")
        return _ok()

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        # Should not raise even though manifest drop "failed".
        prov.unregister_from_room(_device(), ref, room="r1")

    assert any("exited" in rec.message for rec in caplog.records)


# ── teardown_runtime ────────────────────────────────────────────────


def test_teardown_runtime_skips_pre_existing_agent():
    prov = OpenClawProvisioner()
    ref = AgentRef(
        handle="agent-alpha",
        adapter="openclaw",
        device_name="hub",
        metadata={"pre_existing": True, "bootstrap_room": BOOTSTRAP_ROOM},
    )

    with patch("libs.host_exec.execute") as mock_exec:
        prov.teardown_runtime(_device(), ref)

    # Pre-existing agents are operator-owned; we must NOT destroy them.
    mock_exec.assert_not_called()


def test_teardown_runtime_runs_full_rm_for_owned_agent():
    prov = OpenClawProvisioner()
    ref = AgentRef(
        handle="agent-alpha",
        adapter="openclaw",
        device_name="hub",
        metadata={"pre_existing": False, "bootstrap_room": BOOTSTRAP_ROOM},
    )

    with patch("libs.host_exec.execute", return_value=_ok("destroyed")) as mock_exec:
        prov.teardown_runtime(_device(), ref)

    argv = mock_exec.call_args[0][1]
    assert argv[:3] == ["mycelium", "agent", "rm"]
    assert "--full" in argv
    assert "--force" in argv
    assert "--room" in argv and BOOTSTRAP_ROOM in argv


# ── legacy cleanup_agent ────────────────────────────────────────────


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


# ── discover_available ───────────────────────────────────────────────


def test_discover_available_returns_healthy_agents():
    """Agents listed by ``openclaw agents list`` AND passing the gateway probe are returned."""
    prov = OpenClawProvisioner()

    def fake_execute(_device, argv, **_kwargs):
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("- claire-agent\n- selina-agent")
        if argv[:2] == ["openclaw", "sessions"]:
            return _ok("[]")  # gateway responds → healthy
        raise AssertionError(f"unexpected: {argv}")

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        refs = prov.discover_available(_device())

    handles = [r.handle for r in refs]
    assert "claire-agent" in handles
    assert "selina-agent" in handles
    assert all(r.adapter == "openclaw" for r in refs)
    assert all(r.metadata["pre_existing"] is True for r in refs)


def test_discover_available_skips_agents_with_dead_gateway():
    """An agent known to openclaw but rejected by the gateway probe is excluded."""
    prov = OpenClawProvisioner()

    def fake_execute(_device, argv, **_kwargs):
        if argv[:3] == ["openclaw", "agents", "list"]:
            return _ok("- ghost-agent")
        if argv[:2] == ["openclaw", "sessions"]:
            return _fail("gateway not running", rc=1)
        raise AssertionError(f"unexpected: {argv}")

    with patch("libs.host_exec.execute", side_effect=fake_execute):
        refs = prov.discover_available(_device())

    assert refs == []


def test_discover_available_returns_empty_when_no_agents_in_room():
    prov = OpenClawProvisioner()

    with patch("libs.host_exec.execute", return_value=_ok("")):
        refs = prov.discover_available(_device())

    assert refs == []


def test_discover_available_returns_empty_on_ls_failure():
    prov = OpenClawProvisioner()

    with patch("libs.host_exec.execute", return_value=_fail("room not found")):
        refs = prov.discover_available(_device())

    assert refs == []


# ── helpers ─────────────────────────────────────────────────────────


def _make_ref():
    return AgentRef(
        handle="agent-alpha",
        adapter="openclaw",
        device_name="hub",
        metadata={
            "matrix_token_env": "MATRIX_TOKEN_AGENT_ALPHA",
            "room": "r1",
        },
    )
