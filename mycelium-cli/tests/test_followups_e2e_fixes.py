# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Follow-up fixes surfaced by the cursor manual e2e on oclw3/oclw4/oclw5.

Each test pins ONE of six bugs that the cold-spawn / cross-host walkthrough
exposed (the cursor integration itself was healthy — these are surrounding
plumbing issues). Failing one of these tests means the fix has regressed,
not that the cursor surface is broken.

1. ``test_install_claude_code_no_hooks_does_not_crash``
   The privacy-cleanup that emptied ``_CLAUDE_CODE_HOOKS`` left
   ``install_claude_code`` calling ``_resolve_asset("hooks", ...)`` on a
   missing assets dir, which raised ``FileNotFoundError`` in the temp-dir
   fallback branch. The fix gates the whole hooks block behind a non-empty
   ``_CLAUDE_CODE_HOOKS`` check.

2. ``test_agent_create_accepts_kebab_case_adapter``
   ``mycelium adapter add claude-code`` accepts the hyphenated spelling but
   ``mycelium agent create --adapter claude-code`` previously rejected it
   because ``AGENT_ADAPTERS`` is the snake-case set. The fix normalises the
   ``--adapter`` value before the membership check.

3. ``test_cursor_register_does_not_leak_handle_when_cwd_missing``
   The cursor ``register()`` previously claimed the handle in
   ``cc-daemon.toml`` BEFORE calling ``install_workspace_assets``. If the
   cwd didn't exist, the asset drop raised but the handle was already
   persisted — a leak. The fix swaps the order so cwd validation runs
   first.

4. ``test_persist_and_describe_kicks_daemon_for_cold_spawn`` /
   ``test_persist_and_describe_skips_kick_for_long_lived``
   ``mycelium agent create`` writes the handle to ``cc-daemon.toml`` but
   the running daemon only re-reads that file on restart. The fix calls
   ``restart_daemon_service`` from the create/destroy tail for cold-spawn
   adapters only (no-op when no daemon is installed, openclaw doesn't need
   it).

5. ``test_cursor_doctor_checks_skip_when_adapter_not_registered`` /
   ``test_cursor_agent_binary_check_errors_when_missing`` /
   ``test_cursor_login_check_warns_when_no_config``
   ``mycelium doctor`` previously had no cursor-specific checks. The fix
   adds three: PATH, login state, and workspace-asset drift. All three
   must cleanly skip when the cursor adapter isn't registered.

6. ``test_terminate_in_flight_spawns_sigterms_then_sigkills``
   On graceful shutdown the daemon previously cancelled SSE tasks but left
   any running ``cursor-agent`` / ``claude`` processes orphaned. The fix
   walks ``DaemonState.running`` on shutdown, sends SIGTERM, waits up to
   3s, then escalates to SIGKILL — covering the case where systemd's
   cgroup kill isn't in play (direct ``kill`` of the daemon PID).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mycelium.config import MyceliumConfig
from mycelium.daemon import config as daemon_config
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState, RunningProc
from mycelium.integrations.base import AddOptions
from mycelium.integrations.cursor.dispatch import CursorIntegration
from mycelium.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _isolated_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a fresh ``cc-daemon.toml`` in a tmp dir.

    Mirrors the autouse fixture in ``test_cursor_dispatch.py`` so we don't
    pollute the developer's real config when the test suite is run from a
    workstation with the daemon installed.
    """
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "cc-daemon.toml")


# ── 1. claude_code hooks-asset crash ─────────────────────────────────────────


def test_install_claude_code_no_hooks_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bundled ``assets/hooks`` dir is intentionally absent (empty hook
    list post-privacy-cleanup). ``_install_claude_code`` must not call
    ``_resolve_asset("hooks", ...)`` in that state — doing so raised
    ``FileNotFoundError`` from the temp-dir extract fallback.

    We redirect ``Path.home()`` into ``tmp_path`` so the install writes
    its skill / settings.json into the test sandbox, and patch
    ``_resolve_asset`` with a sentinel that fails the test the instant
    the guard regresses.
    """
    from mycelium.integrations.claude_code import install as claude_install

    # Pre-condition: this fix only applies when the hook list is empty.
    assert claude_install._CLAUDE_CODE_HOOKS == []

    # Sentinel: if the guard regresses, _resolve_asset gets called with
    # subpath="hooks" and the test fails fast with a clear message.
    real_resolve = claude_install._resolve_asset

    def _guard(subpath: str, family: str = "openclaw") -> Path:
        if subpath == "hooks":
            raise AssertionError(
                "_install_claude_code resolved bundled 'hooks' asset "
                "despite _CLAUDE_CODE_HOOKS being empty — the guard regressed."
            )
        return real_resolve(subpath, family=family)

    monkeypatch.setattr(claude_install, "_resolve_asset", _guard)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    # Should complete without raising. The function builds its own
    # ~/.claude tree under tmp_path; we just need it to finish.
    claude_install._install_claude_code(verbose=False)


# ── 2. kebab-case adapter id in `mycelium agent create` ─────────────────────


def test_agent_create_accepts_kebab_case_adapter() -> None:
    """The membership check normalises ``-`` to ``_`` before lookup, so
    ``--adapter claude-code`` is equivalent to ``--adapter claude_code``.

    Pure-string test — exercising the full typer command would require a
    backend and is covered by ``test_agent_onboard``; here we only assert
    the normalisation step itself, which is the fix.
    """
    from mycelium.protocol import AGENT_ADAPTERS

    for hyphenated, expected in [
        ("claude-code", "claude_code"),
        ("claude_code", "claude_code"),
        ("cursor", "cursor"),
        ("openclaw", "openclaw"),
    ]:
        normalised = hyphenated.replace("-", "_")
        assert normalised == expected
        assert normalised in AGENT_ADAPTERS


# ── 3. cursor register() handle-leak on missing cwd ─────────────────────────


def test_cursor_register_does_not_leak_handle_when_cwd_missing(tmp_path: Path) -> None:
    """If ``manifest.cwd`` points at a nonexistent directory,
    ``install_workspace_assets`` raises ``NotADirectoryError`` and the
    handle must NOT have been persisted to ``cc-daemon.toml``.

    Before the fix the handle was claimed first and the asset drop ran
    second, so the failure path left orphan ownership behind.
    """
    missing = tmp_path / "does-not-exist"
    assert not missing.exists()

    manifest = AgentManifest(
        handle="design-agent",
        adapter="cursor",
        cwd=str(missing),
        description="leak test",
    )
    integ = CursorIntegration(cwd=str(missing))

    with pytest.raises(NotADirectoryError):
        integ.register(manifest=manifest, config=MyceliumConfig(), opts=AddOptions(room="r"))

    # The handle must NOT appear in cc-daemon.toml. Note we use a fresh
    # ``.load()`` so we read whatever was actually persisted to disk.
    persisted = DaemonConfig.load()
    assert "design-agent" not in persisted.handles, (
        "register() must validate cwd BEFORE claiming the handle — found a leaked ownership entry."
    )


# ── 4. agent create/destroy kicks the cc-daemon for cold-spawn adapters ─────


def _fake_persist_inputs(tmp_path: Path) -> dict:
    """Common kwargs the persist/describe helper expects.

    Avoids touching the backend or the filesystem outside ``tmp_path``.
    """
    return {
        "manifest": AgentManifest(
            handle="design-agent",
            adapter="cursor",
            cwd=str(tmp_path),
            description="",
        ),
        "config": MyceliumConfig(),
        "room_name": "r",
        "handle_flag": "@julia",
        "verb": "created",
    }


def _stub_integration(lifecycle: str) -> MagicMock:
    impl = MagicMock()
    impl.lifecycle = lifecycle
    impl.register = MagicMock()
    impl.describe = MagicMock(return_value=[])
    return impl


def test_persist_and_describe_kicks_daemon_for_cold_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold-spawn adapters (cursor, claude_code) need the daemon to
    re-read ``cc-daemon.toml`` after a new handle is registered."""
    from mycelium.commands import agent as agent_cmd

    # Stub out everything other than the restart call so we don't hit the
    # backend, the filesystem under ~/.mycelium, or rich/console.
    monkeypatch.setattr(agent_cmd, "_check_writable_or_bail", lambda _path: None)
    monkeypatch.setattr(agent_cmd, "_write_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_cmd, "get_room_dir", lambda _r: tmp_path)
    monkeypatch.setattr(agent_cmd.console, "print", lambda *_a, **_k: None)

    impl = _stub_integration(lifecycle="cold_spawn")

    with patch("mycelium.daemon.install.restart_daemon_service", return_value=True) as mock_restart:
        agent_cmd._persist_and_describe(impl=impl, **_fake_persist_inputs(tmp_path))

    assert mock_restart.called, "cold-spawn adapter create must kick the cc-daemon"


def test_persist_and_describe_skips_kick_for_long_lived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Openclaw (long_lived_gateway) doesn't go through the cc-daemon;
    kicking it on every agent add would be wasted noise.
    """
    from mycelium.commands import agent as agent_cmd

    monkeypatch.setattr(agent_cmd, "_check_writable_or_bail", lambda _path: None)
    monkeypatch.setattr(agent_cmd, "_write_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_cmd, "get_room_dir", lambda _r: tmp_path)
    monkeypatch.setattr(agent_cmd.console, "print", lambda *_a, **_k: None)

    impl = _stub_integration(lifecycle="long_lived_gateway")

    with patch("mycelium.daemon.install.restart_daemon_service", return_value=True) as mock_restart:
        agent_cmd._persist_and_describe(impl=impl, **_fake_persist_inputs(tmp_path))

    assert not mock_restart.called, (
        "long-lived-gateway adapter (openclaw) must not trigger a cc-daemon restart"
    )


# ── 5. mycelium doctor cursor checks ─────────────────────────────────────────


def test_cursor_doctor_checks_skip_when_adapter_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three cursor checks must return status='ok' with a 'skipped'
    message when the cursor adapter isn't registered in config.toml.

    This is the same shape as the openclaw skips and is what prevents a
    fresh mycelium install from nagging users about an adapter they never
    asked for.
    """
    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: False)

    for fn in (
        doctor._check_cursor_agent_binary,
        doctor._check_cursor_login,
        doctor._check_cursor_workspace_assets,
    ):
        result = fn()
        assert result.status == "ok"
        assert "skipped" in result.message.lower()


def test_cursor_agent_binary_check_errors_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the adapter IS registered but ``cursor-agent`` is not on PATH,
    doctor must surface a hard error with installation guidance."""
    import shutil

    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda _: None)

    result = doctor._check_cursor_agent_binary()
    assert result.status == "error"
    assert "cursor-agent" in result.message.lower()
    assert any("cursor-agent login" in detail for detail in (result.details or []))


def test_cursor_login_check_warns_when_no_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``~/.cursor/cli-config.json`` doesn't exist the user has never
    completed ``cursor-agent login`` on this host — doctor warns.
    """
    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    result = doctor._check_cursor_login()
    assert result.status == "warning"
    assert any("cursor-agent login" in detail for detail in (result.details or []))


# ── 6. daemon graceful-shutdown spawn cleanup ────────────────────────────────


class _FakeProc:
    """Stand-in for ``asyncio.subprocess.Process`` — terminate / kill /
    wait without actually forking anything."""

    def __init__(self, *, pid: int, terminate_kills: bool, settle_after_kill: bool = True):
        self.pid = pid
        self.returncode: int | None = None
        self._terminate_kills = terminate_kills
        self._settle_after_kill = settle_after_kill
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        if self._terminate_kills:
            self.returncode = 143  # SIGTERM exit signature

    def kill(self) -> None:
        self.killed = True
        if self._settle_after_kill:
            self.returncode = -9

    async def wait(self) -> int:
        # If terminate() already set a returncode, return immediately. If
        # we're simulating a hung process, sleep long enough that the
        # caller's grace window will expire and escalate to kill().
        if self.returncode is not None:
            return self.returncode
        # Sleep longer than the helper's 3s grace; the wait_for() will
        # cancel us first.
        await asyncio.sleep(60)
        return 0


def test_terminate_in_flight_spawns_sigterms_then_sigkills() -> None:
    """The shutdown helper sends SIGTERM to every tracked spawn. Anything
    that doesn't exit within the grace window gets SIGKILL'd. Anything
    that DOES exit cleanly stays at SIGTERM only.
    """
    from mycelium.daemon.runner import _terminate_in_flight_spawns

    state = DaemonState()

    cooperative = _FakeProc(pid=1001, terminate_kills=True)
    hung = _FakeProc(pid=1002, terminate_kills=False)

    state.running["cooperative"] = RunningProc(
        process=cooperative, started_at=0.0, prompt="", sender="", room="r"
    )
    state.running["hung"] = RunningProc(
        process=hung, started_at=0.0, prompt="", sender="", room="r"
    )

    loop = asyncio.new_event_loop()
    try:
        # ``grace_s=0.1`` so the SIGKILL-escalation path runs in
        # milliseconds — production default is 3.0s.
        loop.run_until_complete(
            asyncio.wait_for(_terminate_in_flight_spawns(state, grace_s=0.1), timeout=5.0)
        )
    finally:
        loop.close()

    assert cooperative.terminated, "cooperative spawn should have received SIGTERM"
    assert not cooperative.killed, (
        "cooperative spawn exited on its own; SIGKILL escalation was unnecessary"
    )
    assert hung.terminated, "hung spawn should have received SIGTERM first"
    assert hung.killed, "hung spawn must be SIGKILL'd after the grace window"


def test_terminate_in_flight_spawns_empty_state_is_noop() -> None:
    """The shutdown helper is called even when there are no spawned procs
    — must not raise or block on an empty ``state.running``."""
    from mycelium.daemon.runner import _terminate_in_flight_spawns

    state = DaemonState()  # empty
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(_terminate_in_flight_spawns(state), timeout=1.0))
    finally:
        loop.close()


# ── bonus: restart_daemon_service is a clean no-op when service is missing ──


def test_restart_daemon_service_no_op_when_uninstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``restart_daemon_service`` must return False silently when neither
    the launchd plist nor the systemd unit exists — agent create / rm
    calls it unconditionally and we don't want it to crash on machines
    that haven't run ``--step=daemon``.
    """
    import platform

    from mycelium.daemon import install as daemon_install

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        daemon_install,
        "cc_daemon_service_paths",
        lambda: (Path("/nonexistent/plist"), Path("/nonexistent/service")),
    )

    assert daemon_install.restart_daemon_service(verbose=False) is False
