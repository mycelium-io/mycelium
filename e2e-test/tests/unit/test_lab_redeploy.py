"""Unit tests for :mod:`libs.lab_redeploy`.

The module shells out to ssh/docker via :mod:`libs.host_exec`, so every
test patches ``host_exec.execute`` and asserts both the *command we
asked the device to run* (the shell string) and the *control flow*
(which phases ran, what the failure modes did).

We intentionally **don't** patch ``subprocess.run`` directly — patching
``host_exec.execute`` keeps tests at the right level of abstraction
(commands, not raw argv), and mirrors how the real call chain works.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from libs import lab_redeploy
from libs.lab_redeploy import (
    DeviceResult,
    LabCleanupMode,
    LabRedeployConfig,
    _backend_url,
    _parse_provisioned_ids,
    _role,
    _uv_install_cmd,
    apply_env_overrides,
    cleanup_device,
    configure_spoke,
    install_cli,
    persist_workspace_and_mas,
    provision_workspace_and_mas,
    redeploy_device,
    redeploy_testbed,
    verify_cfn_alignment,
)

# ── fake execute() that captures every call ───────────────────────────


@dataclass
class FakeExec:
    """Drop-in replacement for ``host_exec.execute`` that records calls.

    Each call returns the next entry from ``results`` (a list of
    ``CompletedProcess`` instances). When the list is exhausted, falls
    back to a successful empty result so single tests don't have to
    enumerate every phase.
    """

    calls: list[tuple[Any, str]] = field(default_factory=list)
    results: list[subprocess.CompletedProcess[str]] = field(default_factory=list)

    def __call__(
        self,
        device: Any,
        argv: str,
        *,
        shell: bool = False,
        timeout: float = 30.0,
        input: str | None = None,  # noqa: A002
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((device, argv))
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


@pytest.fixture
def fake_exec(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeExec]:
    """Patch host_exec.execute and yield the recorder for assertions."""
    fx = FakeExec()
    monkeypatch.setattr(lab_redeploy.host_exec, "execute", fx)
    yield fx


def _device(name: str = "hub", **custom: Any) -> SimpleNamespace:
    """Build a pyATS-shaped device with a ``custom`` AttrDict-equivalent."""
    return SimpleNamespace(name=name, custom=custom)


def _completed(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


# ── small helpers ─────────────────────────────────────────────────────


class TestRoleAndBackendUrl:
    def test_role_default_spoke(self) -> None:
        assert _role(_device()) == "spoke"

    def test_role_lowercased(self) -> None:
        assert _role(_device(role="HUB")) == "hub"

    def test_role_env_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FOO_ROLE", "hub")
        d = _device(role="%ENV{FOO_ROLE, spoke}")
        assert _role(d) == "hub"

    def test_backend_url_env_default(self) -> None:
        d = _device(mycelium_backend_url="%ENV{NOPE, http://10.0.0.1:8000}")
        assert _backend_url(d) == "http://10.0.0.1:8000"


# ── _uv_install_cmd ───────────────────────────────────────────────────


class TestUvInstallCmd:
    def test_includes_ref_and_client(self) -> None:
        cfg = LabRedeployConfig(ref="main")
        cmd = _uv_install_cmd(cfg)
        # CLI from the ref
        assert "@main#subdirectory=mycelium-cli" in cmd
        # Client from the same ref (drift guard)
        assert "@main#subdirectory=mycelium-client" in cmd
        # Force-overwrites prior installs
        assert "uv tool install --force" in cmd

    def test_custom_repo_url(self) -> None:
        cfg = LabRedeployConfig(
            ref="abc123",
            repo_url="https://example.com/fork.git",
        )
        cmd = _uv_install_cmd(cfg)
        assert "https://example.com/fork.git@abc123" in cmd
        # Strips trailing .git when re-appending the subdirectory hook
        assert "https://example.com/fork.git@abc123#subdirectory=" in cmd

    def test_sha_ref_works(self) -> None:
        # SHAs are valid git refs for ``uv tool install``; just confirm
        # the command renders without raising.
        cmd = _uv_install_cmd(LabRedeployConfig(ref="a1b2c3d"))
        assert "@a1b2c3d#subdirectory=mycelium-cli" in cmd


# ── cleanup_device ────────────────────────────────────────────────────


class TestCleanupDevice:
    def test_moderate_runs_compose_down_then_data_wipe(self, fake_exec: FakeExec) -> None:
        cfg = LabRedeployConfig(cleanup_mode=LabCleanupMode.MODERATE)
        result = DeviceResult(device_name="hub", role="hub", success=False)

        assert cleanup_device(_device("hub"), cfg, result) is True
        assert len(fake_exec.calls) == 2
        first_cmd = fake_exec.calls[0][1]
        second_cmd = fake_exec.calls[1][1]
        assert "docker compose" in first_cmd
        assert "down -v" in first_cmd
        # Moderate must NOT wipe the whole ~/.mycelium tree (config /
        # .env survive). It MAY wipe nested data dirs.
        assert "rm -rf $HOME/.mycelium;" not in second_cmd
        assert "rm -rf $HOME/.mycelium " not in second_cmd
        assert "rm -rf $HOME/.mycelium\n" not in second_cmd
        # And explicitly preserve the config file.
        assert "config.toml" not in second_cmd
        assert "$HOME/.mycelium/rooms" in second_cmd

    def test_nuclear_uninstalls_cli_and_wipes_dotmycelium(self, fake_exec: FakeExec) -> None:
        cfg = LabRedeployConfig(cleanup_mode=LabCleanupMode.NUCLEAR)
        result = DeviceResult(device_name="hub", role="hub", success=False)

        assert cleanup_device(_device("hub"), cfg, result) is True
        nuke_cmd = fake_exec.calls[1][1]
        assert "rm -rf $HOME/.mycelium" in nuke_cmd
        assert "uv tool uninstall mycelium-cli" in nuke_cmd

    def test_compose_down_failure_aborts(self, fake_exec: FakeExec) -> None:
        fake_exec.results.append(_completed(rc=1, stderr="docker offline"))
        result = DeviceResult(device_name="hub", role="hub", success=False)

        assert cleanup_device(_device("hub"), LabRedeployConfig(), result) is False
        # Only the compose-down call was made — data wipe didn't fire.
        assert len(fake_exec.calls) == 1


# ── install_cli ───────────────────────────────────────────────────────


class TestInstallCli:
    def test_runs_uv_install_then_version(self, fake_exec: FakeExec) -> None:
        result = DeviceResult(device_name="hub", role="hub", success=False)
        assert install_cli(_device("hub"), LabRedeployConfig(ref="main"), result) is True

        assert len(fake_exec.calls) == 2
        assert "uv tool install" in fake_exec.calls[0][1]
        assert "@main#subdirectory=mycelium-cli" in fake_exec.calls[0][1]
        assert "mycelium --version" in fake_exec.calls[1][1]

    def test_install_failure_short_circuits_version_check(self, fake_exec: FakeExec) -> None:
        fake_exec.results.append(_completed(rc=1, stderr="network unreachable"))
        result = DeviceResult(device_name="hub", role="hub", success=False)

        assert install_cli(_device("hub"), LabRedeployConfig(), result) is False
        # Only the install attempt ran; we don't probe --version on failure.
        assert len(fake_exec.calls) == 1


# ── apply_env_overrides ───────────────────────────────────────────────


class TestApplyEnvOverrides:
    def test_no_overrides_is_noop(self, fake_exec: FakeExec) -> None:
        cfg = LabRedeployConfig(env_overrides={})
        result = DeviceResult(device_name="hub", role="hub", success=False)
        assert apply_env_overrides(_device("hub"), cfg, result) is True
        assert fake_exec.calls == []

    def test_writes_keys_in_single_call(self, fake_exec: FakeExec) -> None:
        cfg = LabRedeployConfig(env_overrides={"LLM_MODEL": "anthropic/claude", "LLM_BASE_URL": "https://x"})
        result = DeviceResult(device_name="hub", role="hub", success=False)
        assert apply_env_overrides(_device("hub"), cfg, result) is True

        assert len(fake_exec.calls) == 1
        cmd = fake_exec.calls[0][1]
        # Both keys present in the rendered command (logging only mentions
        # keys, but the command itself must contain values).
        assert "LLM_MODEL=" in cmd
        assert "LLM_BASE_URL=" in cmd

    def test_rejects_value_with_single_quote(self, fake_exec: FakeExec) -> None:
        # Single quotes break our shell quoting; reject loudly rather
        # than silently corrupt the .env file.
        cfg = LabRedeployConfig(env_overrides={"FOO": "it's broken"})
        result = DeviceResult(device_name="hub", role="hub", success=False)
        with pytest.raises(ValueError, match="single quote"):
            apply_env_overrides(_device("hub"), cfg, result)

    def test_rejects_invalid_key(self) -> None:
        with pytest.raises(ValueError, match="shell identifier"):
            apply_env_overrides(
                _device("hub"),
                LabRedeployConfig(env_overrides={"1BAD": "x"}),
                DeviceResult(device_name="hub", role="hub", success=False),
            )

    def test_log_redaction(self, fake_exec: FakeExec, caplog: pytest.LogCaptureFixture) -> None:
        """Successful writes must not log the values (they're often secrets)."""
        import logging

        caplog.set_level(logging.INFO)
        cfg = LabRedeployConfig(env_overrides={"LLM_API_KEY": "sk-very-secret-12345"})
        result = DeviceResult(device_name="hub", role="hub", success=False)
        apply_env_overrides(_device("hub"), cfg, result)

        log_text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "LLM_API_KEY" in log_text  # key is logged
        assert "sk-very-secret-12345" not in log_text  # value is NOT


# ── configure_spoke ───────────────────────────────────────────────────


class TestConfigureSpoke:
    def test_sets_api_url_then_applies(self, fake_exec: FakeExec) -> None:
        result = DeviceResult(device_name="spoke1", role="spoke", success=False)
        ok = configure_spoke(_device("spoke1"), "http://10.0.0.1:8000", result)

        assert ok is True
        assert len(fake_exec.calls) == 1
        cmd = fake_exec.calls[0][1]
        assert "mycelium config set server.api_url http://10.0.0.1:8000" in cmd
        assert "mycelium config apply" in cmd


# ── redeploy_device orchestration ─────────────────────────────────────


def _hub_phase_results(provisioned: bool = True) -> list[subprocess.CompletedProcess[str]]:
    """Return CompletedProcess entries for every hub phase.

    Hub pipeline order (after our provisioning + restart additions):
      1 compose down
      2 data wipe
      3 uv install
      4 mycelium --version
      5 clone
      6 docker build
      7 compose up
      8 /health
      9 provision workspace + MAS  (returns stdout with IDs)
      10 persist workspace + MAS + CFN URLs to config
      11 restart backend
    """
    pre_provision = [_completed(rc=0) for _ in range(8)]
    if not provisioned:
        return pre_provision
    provision_stdout = (
        "WORKSPACE_ID=00000000-0000-0000-0000-000000000001\nMAS_ID=00000000-0000-0000-0000-000000000002\n"
    )
    return [
        *pre_provision,
        _completed(rc=0, stdout=provision_stdout),
        _completed(rc=0),  # persist
        _completed(rc=0),  # backend restart
    ]


class TestRedeployDeviceFlow:
    def test_hub_runs_full_pipeline(self, fake_exec: FakeExec) -> None:
        # Inject results for every phase, including the provisioning
        # call that needs WORKSPACE_ID/MAS_ID lines on stdout.
        fake_exec.results.extend(_hub_phase_results())

        hub = _device(
            "hub",
            role="hub",
            mycelium_backend_url="http://10.0.0.1:8000",
        )
        cfg = LabRedeployConfig(ref="main")
        result = redeploy_device(hub, cfg)

        assert result.success, result.error
        phases = [phase for phase, *_ in result.logs]
        assert "compose down" in phases
        assert any("uv tool install" in p for p in phases)
        assert any("clone" in p for p in phases)
        assert any("docker build" in p for p in phases)
        assert any("compose up" in p for p in phases)
        assert any("/health" in p for p in phases)
        # New post-provisioning phases must be present.
        assert any("provision workspace" in p for p in phases)
        assert any("persist workspace" in p for p in phases)
        assert any("restart backend" in p for p in phases)
        # IDs must be threaded into the result for the orchestrator.
        assert result.workspace_id == "00000000-0000-0000-0000-000000000001"
        assert result.mas_id == "00000000-0000-0000-0000-000000000002"

    def test_spoke_skips_image_build(self, fake_exec: FakeExec) -> None:
        spoke = _device(
            "spoke1",
            role="spoke",
            mycelium_backend_url="http://10.0.0.1:8000",
        )
        result = redeploy_device(spoke, LabRedeployConfig())

        assert result.success, result.error
        phases = [phase for phase, *_ in result.logs]
        # Spokes don't clone or build
        assert not any("clone" in p for p in phases)
        assert not any("docker build" in p for p in phases)
        # They do configure + reach the hub
        assert any("point CLI" in p for p in phases)
        assert any("spoke can reach" in p for p in phases)

    def test_spoke_uses_explicit_hub_url(self, fake_exec: FakeExec) -> None:
        spoke = _device("spoke1", role="spoke")  # no custom URL
        result = redeploy_device(spoke, LabRedeployConfig(), hub_url="http://hub.example:8000")

        assert result.success, result.error
        # Find the configure-spoke command and confirm it carries our URL
        config_cmd = next(
            (cmd for _, cmd in fake_exec.calls if "mycelium config set" in cmd),
            "",
        )
        assert "http://hub.example:8000" in config_cmd

    def test_spoke_no_hub_url_fails_cleanly(self, fake_exec: FakeExec) -> None:
        spoke = _device("spoke1", role="spoke")
        result = redeploy_device(spoke, LabRedeployConfig())

        assert result.success is False
        assert result.error is not None
        assert "hub_url" in result.error or "backend_url" in result.error

    def test_cleanup_failure_stops_pipeline(self, fake_exec: FakeExec) -> None:
        # First call (compose down) fails → no further phases run
        fake_exec.results.append(_completed(rc=1, stderr="docker not running"))
        hub = _device("hub", role="hub", mycelium_backend_url="http://10.0.0.1:8000")

        result = redeploy_device(hub, LabRedeployConfig())

        assert result.success is False
        assert result.error == "cleanup failed"
        # Only the compose down attempt was made
        assert len(fake_exec.calls) == 1

    def test_health_check_failure_fails_redeploy(self, fake_exec: FakeExec) -> None:
        # Make every call succeed EXCEPT the final health check.
        # Phase order on the hub:
        #   1 compose down, 2 data wipe, 3 uv install, 4 mycelium --version,
        #   5 clone, 6 build, 7 compose up, 8 health
        for _ in range(7):
            fake_exec.results.append(_completed(rc=0))
        fake_exec.results.append(_completed(rc=1, stderr="backend NOT healthy"))

        hub = _device("hub", role="hub", mycelium_backend_url="http://10.0.0.1:8000")
        result = redeploy_device(hub, LabRedeployConfig())

        assert result.success is False
        assert result.error == "backend health check failed"

    def test_provisioning_failure_fails_redeploy(self, fake_exec: FakeExec) -> None:
        # 8 calls succeed (through health check), then provisioning
        # fails with non-zero exit code.
        for _ in range(8):
            fake_exec.results.append(_completed(rc=0))
        fake_exec.results.append(_completed(rc=1, stderr="CFN mgmt unreachable"))

        hub = _device("hub", role="hub", mycelium_backend_url="http://10.0.0.1:8000")
        result = redeploy_device(hub, LabRedeployConfig())

        assert result.success is False
        assert result.error == "workspace/MAS provisioning failed"
        # ID fields stay None on failure.
        assert result.workspace_id is None
        assert result.mas_id is None

    def test_provisioning_malformed_output_fails(self, fake_exec: FakeExec) -> None:
        # Provisioning script exits 0 but emits garbage — we must still fail.
        for _ in range(8):
            fake_exec.results.append(_completed(rc=0))
        fake_exec.results.append(_completed(rc=0, stdout="WORKSPACE_ID=\nfoo"))

        hub = _device("hub", role="hub", mycelium_backend_url="http://10.0.0.1:8000")
        result = redeploy_device(hub, LabRedeployConfig())

        assert result.success is False
        assert result.error == "workspace/MAS provisioning failed"


# ── redeploy_testbed ──────────────────────────────────────────────────


class TestRedeployTestbed:
    def _make_testbed(self) -> SimpleNamespace:
        return SimpleNamespace(
            devices={
                "hub": _device("hub", role="hub", mycelium_backend_url="http://10.0.0.1:8000"),
                "spoke1": _device("spoke1", role="spoke", mycelium_backend_url="http://10.0.0.1:8000"),
                "spoke2": _device("spoke2", role="spoke", mycelium_backend_url="http://10.0.0.1:8000"),
            }
        )

    def test_runs_hub_first_then_spokes(self, fake_exec: FakeExec) -> None:
        # Hub needs the full 11-call sequence (with provisioning
        # stdout); spokes default to rc=0 stdout="" which is fine for
        # the simple spoke phases.
        fake_exec.results.extend(_hub_phase_results())

        testbed = self._make_testbed()
        results = redeploy_testbed(testbed, LabRedeployConfig())

        assert [r.device_name for r in results] == ["hub", "spoke1", "spoke2"]
        assert all(r.success for r in results)

    def test_propagates_provisioned_ids_to_spokes(self, fake_exec: FakeExec) -> None:
        """Workspace + MAS IDs from the hub must flow into each spoke's persist call."""
        fake_exec.results.extend(_hub_phase_results())

        testbed = self._make_testbed()
        results = redeploy_testbed(testbed, LabRedeployConfig())

        assert all(r.success for r in results)
        # Find the spoke persist commands and confirm they carry the
        # hub-provisioned IDs.
        persist_cmds = [
            cmd
            for _, cmd in fake_exec.calls
            if "mycelium config set server.workspace_id" in cmd and "00000000-0000-0000-0000-000000000001" in cmd
        ]
        # Two spokes should each get one persist call carrying both IDs.
        assert len(persist_cmds) >= 2
        for cmd in persist_cmds:
            assert "00000000-0000-0000-0000-000000000002" in cmd

    def test_skips_spokes_when_hub_fails(self, fake_exec: FakeExec) -> None:
        # Fail the hub's very first call (compose down)
        fake_exec.results.append(_completed(rc=1, stderr="docker offline"))

        testbed = self._make_testbed()
        results = redeploy_testbed(testbed, LabRedeployConfig())

        # Only the hub gets a result entry.
        assert len(results) == 1
        assert results[0].device_name == "hub"
        assert results[0].success is False

    def test_rejects_zero_hubs(self) -> None:
        testbed = SimpleNamespace(
            devices={
                "s1": _device("s1", role="spoke"),
                "s2": _device("s2", role="spoke"),
            }
        )
        with pytest.raises(ValueError, match="no device with custom.role=hub"):
            redeploy_testbed(testbed, LabRedeployConfig())

    def test_rejects_two_hubs(self) -> None:
        testbed = SimpleNamespace(
            devices={
                "h1": _device("h1", role="hub"),
                "h2": _device("h2", role="hub"),
            }
        )
        with pytest.raises(ValueError, match="2 hubs"):
            redeploy_testbed(testbed, LabRedeployConfig())


# ── provisioning helpers ──────────────────────────────────────────────


class TestParseProvisionedIds:
    def test_parses_clean_output(self) -> None:
        out = "WORKSPACE_ID=abc\nMAS_ID=def\n"
        assert _parse_provisioned_ids(out) == ("abc", "def")

    def test_extracts_from_noisy_output(self) -> None:
        # Tolerates extra log lines around the IDs.
        out = "logging stuff\nWORKSPACE_ID=ws-1\nmore noise\nMAS_ID=mas-1\n"
        assert _parse_provisioned_ids(out) == ("ws-1", "mas-1")

    def test_missing_workspace_returns_none(self) -> None:
        assert _parse_provisioned_ids("MAS_ID=mas\n") is None

    def test_missing_mas_returns_none(self) -> None:
        assert _parse_provisioned_ids("WORKSPACE_ID=ws\n") is None

    def test_empty_value_treated_as_missing(self) -> None:
        # Anchors against the live observed failure mode (backend
        # returns empty string for the id).
        assert _parse_provisioned_ids("WORKSPACE_ID=\nMAS_ID=\n") is None


class TestProvisionWorkspaceAndMas:
    def test_invokes_python3_with_url(self, fake_exec: FakeExec) -> None:
        fake_exec.results.append(_completed(stdout="WORKSPACE_ID=w1\nMAS_ID=m1\n"))
        result = DeviceResult(device_name="hub", role="hub", success=False)

        out = provision_workspace_and_mas(_device("hub"), "http://localhost:9000", result)
        assert out == ("w1", "m1")

        cmd = fake_exec.calls[0][1]
        # Calls the embedded python script over heredoc with the URL as argv[1].
        assert "python3 - http://localhost:9000" in cmd
        assert "WORKSPACE_ID" in cmd  # script body present

    def test_orchestrator_passes_cfn_mgmt_url_not_backend(self, fake_exec: FakeExec) -> None:
        """Regression: provisioning must hit :9000 (CFN mgmt), never :8000 (backend)."""
        fake_exec.results.extend(_hub_phase_results())

        hub = _device("hub", role="hub", mycelium_backend_url="http://10.0.50.125:8000")
        result = redeploy_device(hub, LabRedeployConfig())
        assert result.success, result.error

        # Find the provisioning shell call.
        provision_call = next(
            (cmd for _, cmd in fake_exec.calls if "python3 - " in cmd),
            None,
        )
        assert provision_call is not None, "no provision call recorded"
        assert ":9000" in provision_call, f"provision must target CFN mgmt plane :9000, got: {provision_call[:200]}"
        assert ":8000" not in provision_call, (
            "provision must NOT target the backend :8000 — it doesn't serve POST /api/workspaces"
        )

    def test_cfn_mgmt_url_from_helper(self) -> None:
        from libs.lab_redeploy import _cfn_mgmt_url_from

        assert _cfn_mgmt_url_from("http://10.0.50.125:8000") == "http://10.0.50.125:9000"
        # Trailing path and query strings are stripped (we only need scheme+host).
        assert _cfn_mgmt_url_from("https://example.com:8000/api/v1") == "https://example.com:9000"
        # Bare hostnames default scheme/port behaviour.
        assert _cfn_mgmt_url_from("http://localhost") == "http://localhost:9000"

    def test_non_zero_exit_returns_none(self, fake_exec: FakeExec) -> None:
        fake_exec.results.append(_completed(rc=1, stderr="connection refused"))
        result = DeviceResult(device_name="hub", role="hub", success=False)

        assert provision_workspace_and_mas(_device("hub"), "http://localhost:9000", result) is None
        # Failure is recorded with full stderr for debugging.
        last_phase = result.logs[-1]
        assert last_phase[1] is False  # ok=False


class TestPersistWorkspaceAndMas:
    def test_hub_writes_cfn_urls(self, fake_exec: FakeExec) -> None:
        result = DeviceResult(device_name="hub", role="hub", success=False)
        ok = persist_workspace_and_mas(_device("hub"), "ws-1", "mas-1", result, is_hub=True)
        assert ok is True

        cmd = fake_exec.calls[0][1]
        # Hub flavour sets all four keys.
        assert "server.workspace_id ws-1" in cmd
        assert "server.mas_id mas-1" in cmd
        assert "runtime.cfn_mgmt_url http://ioc-cfn-mgmt-plane-svc:9000" in cmd
        assert "runtime.cognition_fabric_node_url http://ioc-cognition-fabric-node-svc:9002" in cmd
        assert "mycelium config apply" in cmd

    def test_spoke_skips_cfn_urls(self, fake_exec: FakeExec) -> None:
        result = DeviceResult(device_name="spoke1", role="spoke", success=False)
        ok = persist_workspace_and_mas(_device("spoke1"), "ws-1", "mas-1", result)
        assert ok is True

        cmd = fake_exec.calls[0][1]
        # Spokes don't run CFN locally — those keys must NOT be set
        # (would otherwise point the spoke CLI at hostnames it can't
        # resolve).
        assert "cfn_mgmt_url" not in cmd
        assert "cognition_fabric_node_url" not in cmd
        # But workspace + MAS must be there.
        assert "server.workspace_id ws-1" in cmd
        assert "server.mas_id mas-1" in cmd

    @pytest.mark.parametrize(
        "bad_id",
        [
            "",  # empty
            "ws id with space",  # whitespace
            "ws-1; rm -rf /",  # shell metachar
            "ws-1`evil`",  # backticks
            "ws-1$(payload)",  # command substitution
        ],
    )
    def test_rejects_unsafe_values(self, fake_exec: FakeExec, bad_id: str) -> None:
        # Defence-in-depth: even though we control the IDs we get back
        # from CFN mgmt, refuse anything that could escape ``mycelium
        # config set <key> <value>`` into a shell.
        result = DeviceResult(device_name="hub", role="hub", success=False)
        ok = persist_workspace_and_mas(_device("hub"), bad_id, "mas-1", result)
        assert ok is False
        assert fake_exec.calls == []  # no shell call attempted


# ── env_overrides safety contract ─────────────────────────────────────


class TestRedeployConfigDefaults:
    def test_default_cleanup_is_moderate(self) -> None:
        # Preserves the documented "iterate locally without re-entering
        # creds" behaviour the user explicitly asked for.
        assert LabRedeployConfig().cleanup_mode is LabCleanupMode.MODERATE

    def test_default_ref_is_main(self) -> None:
        assert LabRedeployConfig().ref == "main"

    def test_default_excludes_ui_build(self) -> None:
        # UI build adds ~3 min and isn't needed for the scenario suite.
        assert LabRedeployConfig().include_ui is False


# ── script entrypoint smoke ───────────────────────────────────────────


def test_redeploy_lab_script_dry_run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``scripts/redeploy_lab.py --dry-run`` must short-circuit before
    touching the network or genie."""
    # Import lazily so the sys.path tweak in the script picks up our
    # workspace layout.
    import importlib.util
    import pathlib

    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "redeploy_lab.py"
    spec = importlib.util.spec_from_file_location("redeploy_lab_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Use the lab testbed which we know exists in the repo
    testbed = pathlib.Path(__file__).resolve().parents[2] / "testbeds" / "lab.yaml"
    rc = module.main(["--testbed", str(testbed), "--ref", "main", "--dry-run"])
    assert rc == 0
    # Dry-run returning 0 without raising confirms testbed path
    # validation, env-override merging, and LabRedeployConfig
    # construction all succeeded (capsys not needed — logging goes to
    # stderr and isn't easily compared cross-platform).
    _ = capsys.readouterr()


def test_redeploy_lab_script_missing_testbed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import importlib.util
    import pathlib

    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "redeploy_lab.py"
    spec = importlib.util.spec_from_file_location("redeploy_lab_script_missing", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rc = module.main(["--testbed", str(tmp_path / "nope.yaml"), "--dry-run"])
    assert rc == 2


def test_redeploy_lab_script_env_from_shell_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--env-from-shell on a missing key must SystemExit cleanly."""
    import importlib.util
    import pathlib

    monkeypatch.delenv("LLM_API_KEY_TEST_REDEPLOY", raising=False)

    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "redeploy_lab.py"
    spec = importlib.util.spec_from_file_location("redeploy_lab_script_envmiss", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    testbed = pathlib.Path(__file__).resolve().parents[2] / "testbeds" / "lab.yaml"
    with pytest.raises(SystemExit) as exc_info:
        module.main(
            [
                "--testbed",
                str(testbed),
                "--env-from-shell",
                "LLM_API_KEY_TEST_REDEPLOY",
                "--dry-run",
            ]
        )
    # _build_env_overrides raises SystemExit with a string message
    assert "LLM_API_KEY_TEST_REDEPLOY" in str(exc_info.value)


# ── verify_cfn_alignment ──────────────────────────────────────────────


class TestVerifyCfnAlignment:
    """Cover every branch of the CFN alignment helper.

    The helper has a strict call sequence:

    1. ``docker ps`` to confirm both containers are running.
    2. ``provision_workspace_and_mas`` → runs a python heredoc that
       hits the CFN mgmt plane.
    3. ``docker exec mycelium-backend env`` to read the current env.
    4. (drift only) ``mycelium config set ... && config apply``.
    5. (drift only) ``docker inspect`` to discover the compose dir.
    6. (drift only) ``docker compose ... up -d --force-recreate``.
    7. (drift only) ``docker exec mycelium-backend env | grep ...``
       to confirm the new env stuck.

    We assert at each phase: the right command was issued, the
    right ``DeviceResult`` flags came back, and a failure at step N
    short-circuits the chain at step N+1.
    """

    _CFN_OK_STDOUT = "WORKSPACE_ID=ws-aligned\nMAS_ID=mas-aligned\n"

    def test_no_cfn_container_returns_none(self, fake_exec: FakeExec) -> None:
        # docker ps shows nothing → caller skips silently. The
        # compose-only path lives here.
        fake_exec.results.extend([_completed(rc=0, stdout="")])
        result = verify_cfn_alignment(_device("hub"))
        assert result is None
        assert len(fake_exec.calls) == 1
        assert "docker ps" in fake_exec.calls[0][1]

    def test_partial_cfn_returns_none(self, fake_exec: FakeExec) -> None:
        # Only one of the two required containers — we'd hang on
        # CFN reads, so treat as "not deployed" and skip.
        fake_exec.results.extend([_completed(rc=0, stdout="mycelium-backend\n")])
        result = verify_cfn_alignment(_device("hub"))
        assert result is None

    def test_aligned_returns_success_without_changes(self, fake_exec: FakeExec) -> None:
        # CFN says ws-aligned/mas-aligned, container env matches,
        # no writes happen.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),  # provision_workspace_and_mas
                _completed(stdout="WORKSPACE_ID=ws-aligned\nMAS_ID=mas-aligned\n"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is True
        assert result.workspace_id == "ws-aligned"
        assert result.mas_id == "mas-aligned"
        # Exactly 3 shell calls — no config writes, no recreate.
        assert len(fake_exec.calls) == 3
        for _, cmd in fake_exec.calls:
            assert "config set" not in cmd
            assert "force-recreate" not in cmd
        # The "no drift" detail should land in the structured log.
        assert any("no drift" in (detail or "") for _, _, detail in result.logs)

    def test_drift_triggers_persist_and_recreate(self, fake_exec: FakeExec) -> None:
        # CFN says ws-aligned, backend env still on ws-stale →
        # persist + recreate path fires end-to-end.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),
                _completed(stdout="WORKSPACE_ID=ws-stale\nMAS_ID=mas-stale\n"),
                _completed(stdout=""),  # config set ... && config apply
                _completed(stdout="/srv/mycelium/cli/docker\n"),  # docker inspect
                _completed(stdout=""),  # docker compose up -d --force-recreate
                _completed(stdout="WORKSPACE_ID=ws-aligned\nMAS_ID=mas-aligned\n"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is True
        assert result.workspace_id == "ws-aligned"
        assert result.mas_id == "mas-aligned"

        cmds = [c for _, c in fake_exec.calls]
        # Phase markers in order
        assert "docker ps" in cmds[0]
        assert "python3" in cmds[1]  # provision heredoc
        assert "docker exec mycelium-backend env" in cmds[2]
        # Persist call uses the CLI to write canonical IDs
        assert "config set server.workspace_id ws-aligned" in cmds[3]
        assert "config set server.mas_id mas-aligned" in cmds[3]
        assert "config apply" in cmds[3]
        assert "docker inspect" in cmds[4]
        assert "force-recreate" in cmds[5]
        assert "/srv/mycelium/cli/docker" in cmds[5]
        assert "mycelium-backend" in cmds[5]
        assert "ioc-cognition-fabric-node-svc" in cmds[5]
        # Final verify uses the same env probe
        assert "docker exec mycelium-backend env" in cmds[6]
        assert any("drift corrected" in (detail or "") for _, _, detail in result.logs)

    def test_provision_failure_short_circuits(self, fake_exec: FakeExec) -> None:
        # CFN GET returns no workspace → provision returns None and
        # we bail before touching the backend container.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(rc=1, stderr="ERR: no workspaces in CFN mgmt"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is False
        # No env read attempted after provisioning failed.
        cmds = [c for _, c in fake_exec.calls]
        assert len(cmds) == 2
        assert "docker exec mycelium-backend env" not in " ".join(cmds)

    def test_env_read_failure_records_and_aborts(self, fake_exec: FakeExec) -> None:
        # Backend container disappeared between ``docker ps`` and
        # ``docker exec`` → record and abort, don't try to recreate.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),
                _completed(rc=1, stderr="container not running"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is False
        # No persist / recreate attempted.
        cmds = " ".join(c for _, c in fake_exec.calls)
        assert "config set" not in cmds
        assert "force-recreate" not in cmds

    def test_drift_but_persist_fails_aborts_before_recreate(self, fake_exec: FakeExec) -> None:
        # Drift detected, but the CLI ``config set`` returns non-zero
        # → we must not proceed to ``docker compose ... up -d
        # --force-recreate`` on a half-written config.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),
                _completed(stdout="WORKSPACE_ID=ws-stale\nMAS_ID=mas-stale\n"),
                _completed(rc=1, stderr="config: permission denied"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is False
        cmds = " ".join(c for _, c in fake_exec.calls)
        assert "force-recreate" not in cmds
        assert "docker inspect" not in cmds

    def test_drift_with_missing_compose_dir_label_aborts(self, fake_exec: FakeExec) -> None:
        # Container running but somehow lacks the
        # ``com.docker.compose.project.working_dir`` label → we can't
        # locate compose.yml safely, so we refuse to recreate.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),
                _completed(stdout="WORKSPACE_ID=ws-stale\nMAS_ID=mas-stale\n"),
                _completed(stdout=""),  # persist
                _completed(stdout=""),  # docker inspect → empty label
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is False
        cmds = " ".join(c for _, c in fake_exec.calls)
        assert "force-recreate" not in cmds

    def test_post_restart_check_catches_silent_drift(self, fake_exec: FakeExec) -> None:
        # Recreate runs cleanly but the env STILL shows the stale
        # workspace — we MUST surface this as a failure rather than
        # claim success and let later tests time out mysteriously.
        fake_exec.results.extend(
            [
                _completed(stdout="ioc-cfn-mgmt-plane-svc\nmycelium-backend\n"),
                _completed(stdout=self._CFN_OK_STDOUT),
                _completed(stdout="WORKSPACE_ID=ws-stale\nMAS_ID=mas-stale\n"),
                _completed(stdout=""),  # persist
                _completed(stdout="/srv/mycelium/cli/docker\n"),
                _completed(stdout=""),  # force-recreate ok
                _completed(stdout="WORKSPACE_ID=ws-stale\nMAS_ID=mas-stale\n"),
            ]
        )
        result = verify_cfn_alignment(_device("hub"))
        assert result is not None
        assert result.success is False
        # The diagnostic should mention the stale env so debugging
        # doesn't require re-running with --loglevel debug.
        assert any("ws-stale" in (detail or "") for _, ok, detail in result.logs if ok is False)
