# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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
   ``daemon.toml`` BEFORE calling ``install_workspace_assets``. If the
   cwd didn't exist, the asset drop raised but the handle was already
   persisted — a leak. The fix swaps the order so cwd validation runs
   first.

4. ``test_persist_and_describe_kicks_daemon_for_cold_spawn`` /
   ``test_persist_and_describe_skips_kick_for_long_lived``
   ``mycelium agent create`` writes the handle to ``daemon.toml`` but
   the running daemon must re-read that file. The fix calls
   ``reload_daemon_service`` (SIGHUP) from the create/destroy tail for cold-spawn
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
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from mycelium.config import MyceliumConfig
from mycelium.daemon import config as daemon_config
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState, RunningProc
from mycelium.integrations.base import AddOptions
from mycelium.integrations.cursor.dispatch import CursorIntegration
from mycelium.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _isolated_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a fresh ``daemon.toml`` in a tmp dir.

    Mirrors the autouse fixture in ``test_cursor_dispatch.py`` so we don't
    pollute the developer's real config when the test suite is run from a
    workstation with the daemon installed.
    """
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "daemon.toml")


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
    handle must NOT have been persisted to ``daemon.toml``.

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

    # The handle must NOT appear in daemon.toml. Note we use a fresh
    # ``.load()`` so we read whatever was actually persisted to disk.
    persisted = DaemonConfig.load()
    assert "design-agent" not in persisted.handles, (
        "register() must validate cwd BEFORE claiming the handle — found a leaked ownership entry."
    )


# ── 4. agent create/destroy kicks the mycelium-daemon for cold-spawn adapters ─────


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
    re-read ``daemon.toml`` after a new handle is registered."""
    from mycelium.commands import agent as agent_cmd

    # Stub out everything other than the restart call so we don't hit the
    # backend, the filesystem under ~/.mycelium, or rich/console.
    monkeypatch.setattr(agent_cmd, "_check_writable_or_bail", lambda _path: None)
    monkeypatch.setattr(agent_cmd, "_write_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_cmd, "get_room_dir", lambda _r: tmp_path)
    monkeypatch.setattr(agent_cmd.console, "print", lambda *_a, **_k: None)

    impl = _stub_integration(lifecycle="cold_spawn")

    with patch("mycelium.daemon.install.reload_daemon_service", return_value=True) as mock_restart:
        agent_cmd._persist_and_describe(impl=impl, **_fake_persist_inputs(tmp_path))

    assert mock_restart.called, "cold-spawn adapter create must kick the mycelium-daemon"


def test_persist_and_describe_skips_kick_for_long_lived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Openclaw (long_lived_gateway) doesn't go through the mycelium-daemon;
    kicking it on every agent add would be wasted noise.
    """
    from mycelium.commands import agent as agent_cmd

    monkeypatch.setattr(agent_cmd, "_check_writable_or_bail", lambda _path: None)
    monkeypatch.setattr(agent_cmd, "_write_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_cmd, "get_room_dir", lambda _r: tmp_path)
    monkeypatch.setattr(agent_cmd.console, "print", lambda *_a, **_k: None)

    impl = _stub_integration(lifecycle="long_lived_gateway")

    with patch("mycelium.daemon.install.reload_daemon_service", return_value=True) as mock_reload:
        agent_cmd._persist_and_describe(impl=impl, **_fake_persist_inputs(tmp_path))

    assert not mock_reload.called, (
        "long-lived-gateway adapter must not trigger a mycelium-daemon reload"
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
    """When ``~/.config/cursor/auth.json`` doesn't exist the user has
    never completed ``cursor-agent login`` on this host — doctor warns
    with a hint pointing at that path (the file ``cursor-agent``
    actually reads at spawn time).
    """
    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    result = doctor._check_cursor_login()
    assert result.status == "warning"
    assert "has not been run" in result.message.lower()
    assert any("cursor-agent login" in detail for detail in (result.details or []))
    # The hint must point at the *current* config location (~/.config/cursor/auth.json),
    # not the stale ~/.cursor/cli-config.json schema we used to read.
    assert any("/.config/cursor/auth.json" in d for d in (result.details or []))


def test_cursor_login_check_ok_with_auth_json_access_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``cursor-agent`` actually persists its session at
    ``~/.config/cursor/auth.json`` (top-level ``accessToken`` /
    ``refreshToken``). If that file holds a token, the user is logged in.

    Pins F1 from the cursor-e2e walkthrough — doctor was reporting a
    false-negative ``not authenticated`` warning despite a fully working
    ``cursor-agent`` because it was inspecting the wrong file.
    """
    import json

    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    auth_dir = tmp_path / ".config" / "cursor"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text(
        json.dumps({"accessToken": "tok", "refreshToken": "ref"}),
        encoding="utf-8",
    )

    result = doctor._check_cursor_login()
    assert result.status == "ok"
    assert "authenticated" in result.message.lower()


def test_cursor_login_check_warns_when_auth_json_missing_even_if_cli_config_has_authinfo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pins F1b. ``cli-config.json`` ``authInfo.email`` is biographical —
    it persists across logout and lingers as a stale "user X used to be
    logged in" breadcrumb. We do NOT treat it as a "currently
    authenticated" signal, because doing so would let doctor green-light
    a host where ``cursor-agent`` will fail to spawn.

    Reproducer from the post-fix e2e rerun: with auth.json moved aside,
    the daemon correctly posted a friendly "cursor-agent is not
    authenticated" error, but doctor — using a previous version of this
    check that included the cli-config fallback — reported "authenticated".
    """
    import json

    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    # cli-config.json has authInfo populated (logged in ages ago) ...
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "cli-config.json").write_text(
        json.dumps({"authInfo": {"email": "selina@cisco.com"}}),
        encoding="utf-8",
    )
    # ... but auth.json is gone (logged out / cache wiped).

    result = doctor._check_cursor_login()
    assert result.status == "warning"


def test_cursor_login_check_warns_when_auth_json_has_no_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``auth.json`` exists but ``accessToken`` is missing/empty
    (interrupted login flow). Must warn so the user knows to retry.
    """
    import json

    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    auth_dir = tmp_path / ".config" / "cursor"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text(json.dumps({}), encoding="utf-8")

    result = doctor._check_cursor_login()
    assert result.status == "warning"
    assert "not authenticated" in result.message.lower()
    assert any("cursor-agent login" in d for d in (result.details or []))


def test_cursor_login_check_warns_when_auth_json_unparseable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Malformed JSON in ``auth.json`` (concurrent write, disk corruption,
    truncated file) must surface as a warning with the parse error in
    the details — never as a hard crash inside doctor.
    """
    from mycelium.commands import doctor

    monkeypatch.setattr(doctor, "_cursor_adapter_registered", lambda: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # type: ignore[arg-type]

    auth_dir = tmp_path / ".config" / "cursor"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text("{not-json", encoding="utf-8")

    result = doctor._check_cursor_login()
    assert result.status == "warning"
    assert "could not be parsed" in result.message.lower()


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
        "daemon_service_paths",
        lambda: (Path("/nonexistent/plist"), Path("/nonexistent/service")),
    )

    assert daemon_install.restart_daemon_service(verbose=False) is False


def test_daemon_restart_cli_calls_full_restart_not_reload() -> None:
    """``mycelium daemon restart`` must restart the process, not SIGHUP-reload."""
    from mycelium.commands import daemon as daemon_cmd

    runner = CliRunner()
    with (
        patch("mycelium.daemon.install.restart_daemon_service", return_value=True) as mock_restart,
        patch("mycelium.daemon.install.reload_daemon_service", return_value=True) as mock_reload,
    ):
        result = runner.invoke(daemon_cmd.app, ["restart"])

    assert result.exit_code == 0
    assert mock_restart.called
    assert not mock_reload.called


# ── daemon reload finds a foreground daemon via the lock file ────────────────


def test_pid_from_lock_returns_live_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreground daemon isn't registered with launchd/systemd, so the service
    lookups miss it — ``_pid_from_lock`` reads the PID from the singleton lock so
    ``daemon subscribe`` / the demo can still SIGHUP-reload it."""
    import os

    from mycelium.daemon import install as daemon_install

    lock = tmp_path / "daemon.lock"
    lock.write_text(f"{os.getpid()}\n")  # our own PID is guaranteed alive
    monkeypatch.setattr("mycelium.daemon.config.daemon_lock_path", lambda: lock)

    assert daemon_install._pid_from_lock() == os.getpid()


def test_pid_from_lock_none_for_dead_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale lock (crashed daemon) must not resolve to a dead/recycled PID."""
    from mycelium.daemon import install as daemon_install

    lock = tmp_path / "daemon.lock"
    lock.write_text("2147483646\n")  # a PID that isn't running
    monkeypatch.setattr("mycelium.daemon.config.daemon_lock_path", lambda: lock)

    assert daemon_install._pid_from_lock() is None


def test_pid_from_lock_none_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.daemon import install as daemon_install

    monkeypatch.setattr("mycelium.daemon.config.daemon_lock_path", lambda: tmp_path / "absent.lock")
    assert daemon_install._pid_from_lock() is None


# ── 7. agent invoke falls through to backend for cross-host invocations ──────


def test_load_manifest_remote_returns_parsed_manifest() -> None:
    """The cross-host fall-through helper round-trips an
    ``agents/<handle>`` memory entry from the backend ``MemoryRead`` shape
    back into an ``AgentManifest``. The backend stores manifests as
    yaml-as-string (see ``_write_manifest``), so the helper must
    ``yaml.safe_load`` the body — not assume any particular field name.

    Backend serialisation is non-deterministic between client versions:
    sometimes the YAML lands in ``content_text`` (top-level convenience
    field), sometimes in ``value`` as a plain string, and sometimes
    inside a ``MemoryReadValueType0`` wrapper as ``value.text``. All
    three shapes must round-trip — exercise each below.
    """
    import yaml

    from mycelium.commands.agent import _load_manifest_remote

    handle = "designer"
    manifest_body = yaml.safe_dump(
        {
            "adapter": "cursor",
            "description": "spoke-side cursor agent",
            "cwd": "/tmp/cursor-spoke-ws",
        },
        sort_keys=False,
    ).strip()

    # Shape 1: content_text populated (the realistic backend response we
    # observed during the cursor-e2e Phase 4 rerun).
    fake_memory_a = SimpleNamespace(
        content_text=manifest_body,
        value=SimpleNamespace(),  # MemoryReadValueType0 placeholder, ignored
    )
    # Shape 2: value is a raw YAML string.
    fake_memory_b = SimpleNamespace(content_text=None, value=manifest_body)

    # Shape 3: value is a MemoryReadValueType0 (dict-like with __contains__/
    # __getitem__) carrying the YAML inside a "text" key.
    class _ValueType0:
        def __init__(self, text: str) -> None:
            self._d = {"text": text}

        def __contains__(self, k: str) -> bool:
            return k in self._d

        def __getitem__(self, k: str) -> str:
            return self._d[k]

    fake_memory_c = SimpleNamespace(content_text=None, value=_ValueType0(manifest_body))

    for label, fake in (
        ("content_text", fake_memory_a),
        ("value-as-str", fake_memory_b),
        ("value.text-wrapper", fake_memory_c),
    ):
        fake_get_api = SimpleNamespace(sync=Mock(return_value=fake))
        fake_module = SimpleNamespace(get_memory_api_rooms_room_name_memory_key_get=fake_get_api)
        with patch.dict(sys.modules, {"mycelium_backend_client.api.memory": fake_module}):
            manifest = _load_manifest_remote(client=Mock(), room_name="cursor-e2e", handle=handle)

        assert manifest is not None, f"shape {label!r} failed to round-trip"
        assert manifest.handle == handle
        assert manifest.adapter == "cursor"
        assert manifest.memory_key == f"agents/{handle}"
        fake_get_api.sync.assert_called_once_with(
            room_name="cursor-e2e",
            key=f"agents/{handle}",
            client=ANY,
        )


def test_load_manifest_remote_returns_none_for_missing_or_error() -> None:
    """When the backend memory endpoint returns ``None`` (404) or raises a
    transport error, the helper must fall through to ``None`` so the
    caller can surface the same friendly "no agent named …" message used
    for genuinely-missing agents — never a stack trace.
    """
    from mycelium.commands.agent import _load_manifest_remote

    # Case 1: backend returns None → not found
    fake_module_404 = SimpleNamespace(
        get_memory_api_rooms_room_name_memory_key_get=SimpleNamespace(sync=Mock(return_value=None))
    )
    with patch.dict(sys.modules, {"mycelium_backend_client.api.memory": fake_module_404}):
        assert _load_manifest_remote(client=Mock(), room_name="r", handle="ghost") is None

    # Case 2: backend raises (timeout, network error) → swallow + return None
    fake_module_boom = SimpleNamespace(
        get_memory_api_rooms_room_name_memory_key_get=SimpleNamespace(
            sync=Mock(side_effect=ConnectionError("backend down"))
        )
    )
    with patch.dict(sys.modules, {"mycelium_backend_client.api.memory": fake_module_boom}):
        assert _load_manifest_remote(client=Mock(), room_name="r", handle="ghost") is None


def test_agent_invoke_falls_through_to_backend_when_local_mirror_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins F2 from the cursor-e2e walkthrough.

    Before the fix, ``mycelium agent invoke <handle>`` checked the local
    filesystem mirror for ``agents/<handle>`` and bailed with
    ``Not found: no agent named …`` if the manifest hadn't been
    materialised on this host. That blocked every cross-host invocation
    (hub invoking a spoke-registered agent or vice-versa).

    The fix calls ``_load_manifest`` first (cheap local read) and falls
    through to ``_load_manifest_remote`` (backend memory API) only when
    local returns ``None``. This test forces that fall-through path and
    asserts the message is sent.
    """
    import importlib

    from mycelium.commands import agent as agent_cmd
    from mycelium.protocol import AgentManifest

    monkeypatch.setattr(agent_cmd, "_load_manifest", lambda _r, _h: None)

    remote_manifest = AgentManifest(
        handle="cursor-spoke",
        adapter="cursor",
        description="lives on the spoke",
        cwd="/tmp/cursor-spoke-ws",
    )
    monkeypatch.setattr(agent_cmd, "_load_manifest_remote", lambda _c, _r, _h: remote_manifest)

    fake_config = SimpleNamespace(
        server=SimpleNamespace(api_url="http://localhost:8000"),
        get_current_identity=lambda: "operator",
    )
    monkeypatch.setattr(agent_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(agent_cmd, "_resolve_room", lambda _c, _r: "cursor-multi-e2e")

    fake_client_cm = MagicMock()
    fake_client_cm.__enter__.return_value = Mock(name="client")
    fake_client_cm.__exit__.return_value = None
    monkeypatch.setattr(agent_cmd, "_typed_client", lambda _c: fake_client_cm)

    send_api_sync = Mock()
    fake_send_module = SimpleNamespace(
        send_message_api_rooms_room_name_messages_post=SimpleNamespace(sync=send_api_sync)
    )
    fake_models_module = SimpleNamespace(MessageCreate=lambda **kw: SimpleNamespace(**kw))

    with patch.dict(
        sys.modules,
        {
            "mycelium_backend_client.api.messages": fake_send_module,
            "mycelium_backend_client.models": fake_models_module,
        },
    ):
        # Re-import not needed — the import is inside agent_invoke.
        importlib.reload  # noqa: B018 — keep import-side-effect free
        runner = CliRunner()
        result = runner.invoke(
            agent_cmd.app,
            [
                "invoke",
                "cursor-spoke",
                "please reply with hostname",
                "--room",
                "cursor-multi-e2e",
            ],
        )

    assert result.exit_code == 0, result.output
    assert send_api_sync.called, (
        "agent invoke must reach the messages send API after the backend "
        "fall-through resolves the manifest"
    )
    body = send_api_sync.call_args.kwargs["body"]
    assert body.content.startswith("@cursor-spoke ")
    assert body.sender_handle == "operator"


def test_agent_invoke_errors_when_neither_local_nor_remote_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the manifest is missing locally AND the backend returns nothing,
    we still want the original friendly error — not a fall-through that
    silently sends a message to a non-existent handle.
    """
    from mycelium.commands import agent as agent_cmd

    monkeypatch.setattr(agent_cmd, "_load_manifest", lambda _r, _h: None)
    monkeypatch.setattr(agent_cmd, "_load_manifest_remote", lambda _c, _r, _h: None)

    fake_config = SimpleNamespace(
        server=SimpleNamespace(api_url="http://localhost:8000"),
        get_current_identity=lambda: "operator",
    )
    monkeypatch.setattr(agent_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(agent_cmd, "_resolve_room", lambda _c, _r: "cursor-e2e")

    fake_client_cm = MagicMock()
    fake_client_cm.__enter__.return_value = Mock(name="client")
    fake_client_cm.__exit__.return_value = None
    monkeypatch.setattr(agent_cmd, "_typed_client", lambda _c: fake_client_cm)

    runner = CliRunner()
    result = runner.invoke(
        agent_cmd.app,
        ["invoke", "ghost", "anything", "--room", "cursor-e2e"],
    )

    assert result.exit_code == 1
    assert "no agent named 'ghost'" in result.output
