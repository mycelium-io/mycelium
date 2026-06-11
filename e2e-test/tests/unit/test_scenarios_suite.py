"""Unit tests for :mod:`suites.scenarios_suite`.

These tests focus on the new lifecycle subsections introduced in the
matrix refactor:

- ``LabRedeployCommonSetup.provision_matrix_agents`` deduplicates
  agents across active rows, runs ``ensure_runtime`` per unique
  ``(adapter, handle, host)``, and stashes refs in
  ``testscript.parameters``.
- ``MatrixCommonCleanup.teardown_matrix_agents`` reads those refs
  back and calls ``teardown_runtime`` for each, gated on
  ``MYCELIUM_E2E_KEEP_AGENTS``.

We exercise both subsections directly (without spinning up pyATS) by
constructing the bound-method, providing a minimal stub testbed/
testscript, and asserting on call counts + parameter mutations.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyats.aetest.signals import AEtestFailedSignal, AEtestSkippedSignal

from libs.provisioners.base import AgentRef

# ── module bootstrap ────────────────────────────────────────────────


@pytest.fixture
def suite_module(monkeypatch):
    """Reload ``suites.scenarios_suite`` with a stubbed
    ``MYCELIUM_E2E_SCENARIOS_FILE`` env var so import-time loading
    doesn't depend on the real datafile."""
    import suites.scenarios_suite as mod

    return mod


# ── helpers ─────────────────────────────────────────────────────────


def _make_testscript():
    """Mimic the pyATS Testscript shape — just needs ``parameters``."""
    return SimpleNamespace(parameters={})


def _make_testbed(devices: dict[str, object] | None = None):
    devices = devices or {}
    return SimpleNamespace(devices=devices)


def _device(name: str = "hub"):
    return SimpleNamespace(name=name)


# ── provision_matrix_agents ─────────────────────────────────────────


def test_provision_matrix_agents_short_circuits_on_skip_env(monkeypatch, suite_module):
    """``MYCELIUM_E2E_SKIP_AGENT_PROVISIONING=1`` skips the heavy
    pre-spawn and writes an empty registry. Used when agents are
    pre-baked on the target environment."""
    monkeypatch.setenv("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", "1")

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    # ``self.skipped(...)`` raises ``AEtestSkippedSignal`` which is
    # the canonical short-circuit. The registry must have been set
    # BEFORE the skip fired, so per-test setup never sees an
    # unset key (it falls back to the slow path if absent).
    with pytest.raises(AEtestSkippedSignal):
        section.provision_matrix_agents(testscript, testbed=_make_testbed())

    assert testscript.parameters["matrix_agents_provisioned"] == {}


def test_provision_matrix_agents_dedups_across_rows(monkeypatch, suite_module):
    """Two scenarios sharing the same (adapter, handle, host)
    should produce ONE ensure_runtime call, not two."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", raising=False)

    fake_rows = [
        {
            "name": "row1",
            "agents": [
                {"adapter": "openclaw", "handle": "alpha", "host": "hub"},
                {"adapter": "openclaw", "handle": "beta", "host": "spoke1"},
            ],
        },
        {
            "name": "row2",
            "agents": [
                # alpha@hub is a duplicate — must collapse to one call
                {"adapter": "openclaw", "handle": "alpha", "host": "hub"},
                {"adapter": "cursor", "handle": "gamma", "host": "spoke2"},
            ],
        },
    ]

    hub = _device("hub")
    spoke1 = _device("spoke1")
    spoke2 = _device("spoke2")
    testbed = _make_testbed({"hub": hub, "spoke1": spoke1, "spoke2": spoke2})

    # Stub the provisioner registry with a recording fake.
    calls: list[tuple[str, str, str]] = []

    class _RecordingProvisioner:
        def __init__(self, adapter: str):
            self.adapter = adapter

        def check_prereqs(self, device):
            return None

        def ensure_runtime(self, device, handle, **kwargs):
            calls.append((self.adapter, handle, device.name))
            return AgentRef(
                handle=handle,
                adapter=self.adapter,
                device_name=device.name,
                metadata={"pre_existing": False},
            )

    def fake_get_provisioner(name):
        return _RecordingProvisioner(name)

    monkeypatch.setattr(suite_module, "_ACTIVE_ROWS", fake_rows)
    monkeypatch.setattr(suite_module, "get_provisioner", fake_get_provisioner)

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    section.provision_matrix_agents(testscript, testbed=testbed)

    # Three unique tuples: (oc, alpha, hub), (oc, beta, spoke1),
    # (cu, gamma, spoke2). alpha@hub appearing twice must collapse.
    assert sorted(calls) == [
        ("cursor", "gamma", "spoke2"),
        ("openclaw", "alpha", "hub"),
        ("openclaw", "beta", "spoke1"),
    ]

    refs = testscript.parameters["matrix_agents_provisioned"]
    assert set(refs.keys()) == {
        ("openclaw", "alpha", "hub"),
        ("openclaw", "beta", "spoke1"),
        ("cursor", "gamma", "spoke2"),
    }
    for ref in refs.values():
        assert isinstance(ref, AgentRef)


def test_provision_matrix_agents_collects_failures(monkeypatch, suite_module):
    """Failures across multiple agents collect into one bulk
    ``self.failed(...)`` rather than failing on the first error."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", raising=False)

    fake_rows = [
        {
            "name": "row1",
            "agents": [
                {"adapter": "openclaw", "handle": "alpha", "host": "hub"},
                {"adapter": "openclaw", "handle": "ghost", "host": "missing-host"},
            ],
        },
    ]
    hub = _device("hub")
    testbed = _make_testbed({"hub": hub})  # ``missing-host`` deliberately absent

    from libs.provisioners.base import PrereqMissing

    class _FailingProvisioner:
        def check_prereqs(self, device):
            return None

        def ensure_runtime(self, device, handle, **kwargs):
            if handle == "alpha":
                raise PrereqMissing("LLM key missing")
            return AgentRef(handle=handle, adapter="openclaw", device_name="hub")

    monkeypatch.setattr(suite_module, "_ACTIVE_ROWS", fake_rows)
    monkeypatch.setattr(suite_module, "get_provisioner", lambda _: _FailingProvisioner())

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    with pytest.raises(AEtestFailedSignal) as excinfo:
        section.provision_matrix_agents(testscript, testbed=testbed)

    msg = str(excinfo.value)
    # Both failures should be reported in the bulk message.
    assert "alpha" in msg
    assert "ghost" in msg


def test_provision_matrix_agents_handles_empty_rows(monkeypatch, suite_module):
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", raising=False)
    monkeypatch.setattr(suite_module, "_ACTIVE_ROWS", [])

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    # Should not raise; just sets an empty registry.
    section.provision_matrix_agents(testscript, testbed=_make_testbed())
    assert testscript.parameters["matrix_agents_provisioned"] == {}


# ── teardown_matrix_agents ──────────────────────────────────────────


def test_teardown_matrix_agents_short_circuits_on_keep_env(monkeypatch, suite_module):
    """``MYCELIUM_E2E_KEEP_AGENTS=1`` is the dev convenience knob:
    leave the heavyweight openclaw agents around between runs so
    iteration doesn't pay the spawn cost."""
    monkeypatch.setenv("MYCELIUM_E2E_KEEP_AGENTS", "1")

    section = suite_module.MatrixCommonCleanup()
    testscript = _make_testscript()
    testscript.parameters["matrix_agents_provisioned"] = {
        ("openclaw", "alpha", "hub"): AgentRef(handle="alpha", adapter="openclaw", device_name="hub"),
    }

    with pytest.raises(AEtestSkippedSignal):
        section.teardown_matrix_agents(testscript, testbed=_make_testbed())


def test_teardown_matrix_agents_calls_teardown_runtime_for_each(monkeypatch, suite_module):
    monkeypatch.delenv("MYCELIUM_E2E_KEEP_AGENTS", raising=False)

    teardowns: list[tuple[str, str]] = []

    class _RecordingProvisioner:
        def teardown_runtime(self, device, agent):
            teardowns.append((agent.handle, device.name))

    monkeypatch.setattr(suite_module, "get_provisioner", lambda _: _RecordingProvisioner())

    hub = _device("hub")
    spoke1 = _device("spoke1")
    testbed = _make_testbed({"hub": hub, "spoke1": spoke1})

    section = suite_module.MatrixCommonCleanup()
    testscript = _make_testscript()
    testscript.parameters["matrix_agents_provisioned"] = {
        ("openclaw", "alpha", "hub"): AgentRef(handle="alpha", adapter="openclaw", device_name="hub"),
        ("openclaw", "beta", "spoke1"): AgentRef(handle="beta", adapter="openclaw", device_name="spoke1"),
    }

    section.teardown_matrix_agents(testscript, testbed=testbed)

    assert sorted(teardowns) == [("alpha", "hub"), ("beta", "spoke1")]


def test_teardown_matrix_agents_swallows_failures(monkeypatch, suite_module):
    """One agent's teardown failing must not block the others."""
    monkeypatch.delenv("MYCELIUM_E2E_KEEP_AGENTS", raising=False)

    completed: list[str] = []

    class _FlakyProvisioner:
        def teardown_runtime(self, device, agent):
            if agent.handle == "alpha":
                raise RuntimeError("ssh down")
            completed.append(agent.handle)

    monkeypatch.setattr(suite_module, "get_provisioner", lambda _: _FlakyProvisioner())

    hub = _device("hub")
    testbed = _make_testbed({"hub": hub})

    section = suite_module.MatrixCommonCleanup()
    testscript = _make_testscript()
    testscript.parameters["matrix_agents_provisioned"] = {
        ("openclaw", "alpha", "hub"): AgentRef(handle="alpha", adapter="openclaw", device_name="hub"),
        ("openclaw", "beta", "hub"): AgentRef(handle="beta", adapter="openclaw", device_name="hub"),
    }

    # Should NOT raise — beta still gets torn down.
    section.teardown_matrix_agents(testscript, testbed=testbed)
    assert completed == ["beta"]


def test_teardown_matrix_agents_handles_empty_registry(monkeypatch, suite_module):
    """Suite that ran with skip-provisioning or no rows still
    reaches common_cleanup; an empty registry must just exit
    cleanly without trying to look up nonexistent agents."""
    monkeypatch.delenv("MYCELIUM_E2E_KEEP_AGENTS", raising=False)
    section = suite_module.MatrixCommonCleanup()
    testscript = _make_testscript()  # no params

    # Returns cleanly.
    section.teardown_matrix_agents(testscript, testbed=_make_testbed())


# ── verify_cfn_alignment subsection ─────────────────────────────────


def _hub_device(name: str = "hub", role: str = "hub", **extra):
    """Build a hub-shaped device with a ``custom`` AttrDict-like dict."""
    custom = {"role": role}
    custom.update(extra)
    return SimpleNamespace(name=name, custom=custom)


def test_verify_cfn_alignment_skipped_via_env(monkeypatch, suite_module):
    """``MYCELIUM_E2E_SKIP_CFN_ALIGNMENT=1`` skips the subsection."""
    monkeypatch.setenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", "1")
    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    with pytest.raises(AEtestSkippedSignal):
        section.verify_cfn_alignment(testscript, testbed=_make_testbed())


def test_verify_cfn_alignment_no_hub_role_logs_and_returns(monkeypatch, suite_module):
    """Testbeds without a hub-role device (rare but valid in dev
    setups) shouldn't fail the suite — just log and continue."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", raising=False)

    calls: list[tuple] = []

    def fake_verify(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(suite_module, "verify_cfn_alignment", fake_verify)

    spoke = SimpleNamespace(name="spoke1", custom={"role": "spoke"})
    testbed = _make_testbed({"spoke1": spoke})

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    # Returns cleanly, never invokes the helper.
    section.verify_cfn_alignment(testscript, testbed=testbed)
    assert calls == []


def test_verify_cfn_alignment_skips_compose_paths(monkeypatch, suite_module):
    """When the helper returns ``None`` (no CFN container running),
    the subsection treats that as a silent skip and moves on."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", raising=False)

    monkeypatch.setattr(suite_module, "verify_cfn_alignment", lambda *a, **kw: None)

    hub = _hub_device("hub", mycelium_backend_url="http://10.0.0.1:8000")
    testbed = _make_testbed({"hub": hub})

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    section.verify_cfn_alignment(testscript, testbed=testbed)
    # No results stashed because every hub returned None.
    assert testscript.parameters.get("cfn_alignment_results", []) == []


def test_verify_cfn_alignment_success_stashes_result(monkeypatch, suite_module):
    """Successful alignment populates the testscript params so
    downstream subsections / scenarios can inspect what got aligned."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", raising=False)

    from libs.lab_redeploy import DeviceResult

    fake_result = DeviceResult(device_name="hub", role="hub", success=True)
    fake_result.workspace_id = "ws-aligned"
    fake_result.mas_id = "mas-aligned"
    monkeypatch.setattr(
        suite_module,
        "verify_cfn_alignment",
        lambda *args, **kwargs: fake_result,
    )

    hub = _hub_device("hub", mycelium_backend_url="http://10.0.0.1:8000")
    testbed = _make_testbed({"hub": hub})

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    section.verify_cfn_alignment(testscript, testbed=testbed)

    results = testscript.parameters["cfn_alignment_results"]
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].workspace_id == "ws-aligned"


def test_verify_cfn_alignment_failure_aborts_suite(monkeypatch, suite_module):
    """If the helper returns a failed result, the subsection must
    self.failed() so subsequent scenarios don't run against a
    half-aligned backend (which would just look like consensus
    timeouts and burn the time budget)."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", raising=False)

    from libs.lab_redeploy import DeviceResult

    fake_result = DeviceResult(device_name="hub", role="hub", success=False)
    fake_result.error = "could not force-recreate backend"
    monkeypatch.setattr(
        suite_module,
        "verify_cfn_alignment",
        lambda *args, **kwargs: fake_result,
    )

    hub = _hub_device("hub")
    testbed = _make_testbed({"hub": hub})

    section = suite_module.LabRedeployCommonSetup()
    testscript = _make_testscript()

    with pytest.raises(AEtestFailedSignal) as excinfo:
        section.verify_cfn_alignment(testscript, testbed=testbed)

    # The error from the helper must propagate into the failure
    # message; otherwise the operator can't tell which hub broke.
    assert "force-recreate" in str(excinfo.value)


def test_verify_cfn_alignment_passes_backend_url_from_custom(monkeypatch, suite_module):
    """The subsection must hand the per-hub
    ``custom.mycelium_backend_url`` down to the helper rather than
    always using ``localhost:8000`` (which only works on the hub
    when ssh'd in)."""
    monkeypatch.delenv("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", raising=False)
    monkeypatch.delenv("MYCELIUM_BACKEND_URL", raising=False)

    captured: list[tuple[object, str]] = []

    def fake_verify(device, *, backend_url, **kwargs):
        captured.append((device, backend_url))
        return None

    monkeypatch.setattr(suite_module, "verify_cfn_alignment", fake_verify)

    hub = _hub_device("hub", mycelium_backend_url="http://10.42.0.5:8000")
    testbed = _make_testbed({"hub": hub})

    section = suite_module.LabRedeployCommonSetup()
    section.verify_cfn_alignment(_make_testscript(), testbed=testbed)

    assert captured == [(hub, "http://10.42.0.5:8000")]
