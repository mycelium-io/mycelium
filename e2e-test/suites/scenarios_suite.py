"""Three-axis scenario suite.

Loads ``data/scenarios.yaml``, filters by ``MYCELIUM_E2E_TIERS``, and
materialises one pyATS ``Testcase`` per row at import time.

Run standalone:
    MYCELIUM_E2E_TIERS=pr pyats run job suites/scenarios_suite.py \\
        --testbed-file testbeds/compose.yaml

Optional lab redeploy (only fires when running against
``testbeds/lab.yaml`` with ``MYCELIUM_LAB_REDEPLOY=1`` set):

    MYCELIUM_LAB_REDEPLOY=1 MYCELIUM_LAB_REF=main \\
        MYCELIUM_E2E_TIERS=pr pyats run job suites/scenarios_suite.py \\
        --testbed-file testbeds/lab.yaml

This module is intentionally thin — all the scenario logic lives in
:mod:`testcases.scenarios`. The suite's only job is to wire the
generated classes into the pyATS-discovered namespace and (optionally)
redeploy lab hardware before the first testcase runs.
"""

from __future__ import annotations

import logging
import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from libs import host_exec  # noqa: E402 - sys.path tweak first
from libs.host_exec import HostExecError  # noqa: E402 - sys.path tweak first
from libs.lab_redeploy import (  # noqa: E402 - sys.path tweak first
    LabCleanupMode,
    LabRedeployConfig,
    redeploy_testbed,
    verify_cfn_alignment,
)
from libs.provisioners import (  # noqa: E402 - sys.path tweak first
    AgentRef,
    PrereqMissing,
    get_provisioner,
)
from testcases.scenarios import (  # noqa: E402 - sys.path tweak first
    active_tiers,
    filter_by_tier,
    load_rows,
    make_scenarios,
)

log = logging.getLogger(__name__)


# ── load + filter + materialise ─────────────────────────────────────

_SCENARIOS_FILE = os.environ.get(
    "MYCELIUM_E2E_SCENARIOS_FILE",
    os.path.join(_ROOT, "data", "scenarios.yaml"),
)

_ALL_ROWS = load_rows(_SCENARIOS_FILE)
_ACTIVE_TIERS = active_tiers()
_ACTIVE_ROWS = filter_by_tier(_ALL_ROWS, _ACTIVE_TIERS)

log.info(
    "scenarios_suite: %d/%d rows active (tiers=%s)",
    len(_ACTIVE_ROWS),
    len(_ALL_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_ACTIVE_ROWS)


# ── optional lab redeploy CommonSetup ───────────────────────────────


def _redeploy_requested() -> bool:
    """Return True when the operator opted into the lab redeploy hook.

    Compose runs never set this (they're born fresh every time), so the
    default is off and the CommonSetup short-circuits with a single
    skipped subsection on the standard PR path.
    """
    return os.environ.get("MYCELIUM_LAB_REDEPLOY", "").lower() in {"1", "true", "yes"}


def _redeploy_config_from_env() -> LabRedeployConfig:
    """Build a :class:`LabRedeployConfig` from environment variables.

    Mirrors the flags supported by ``scripts/redeploy_lab.py`` so the
    same knobs are reachable from either path. Sensitive values
    (LLM_API_KEY, LLM_BASE_URL) are pulled from the live env via
    ``MYCELIUM_LAB_ENV_KEYS`` rather than from the testbed YAML so they
    never land on disk in the repo.
    """
    ref = os.environ.get("MYCELIUM_LAB_REF", "main")
    repo = os.environ.get("MYCELIUM_REPO_URL", "https://github.com/mycelium-io/mycelium.git")
    mode_raw = os.environ.get("MYCELIUM_LAB_CLEANUP", LabCleanupMode.MODERATE.value)
    try:
        mode = LabCleanupMode(mode_raw)
    except ValueError:
        log.warning("Unknown MYCELIUM_LAB_CLEANUP=%r — falling back to moderate", mode_raw)
        mode = LabCleanupMode.MODERATE

    overrides: dict[str, str] = {}
    raw_keys = os.environ.get("MYCELIUM_LAB_ENV_KEYS", "")
    for key in (k.strip() for k in raw_keys.split(",") if k.strip()):
        if key in os.environ:
            overrides[key] = os.environ[key]
        else:
            log.warning(
                "MYCELIUM_LAB_ENV_KEYS lists %r but it isn't in the process env — skipped",
                key,
            )

    return LabRedeployConfig(
        ref=ref,
        repo_url=repo,
        cleanup_mode=mode,
        include_ui=os.environ.get("MYCELIUM_LAB_INCLUDE_UI", "").lower() in {"1", "true", "yes"},
        env_overrides=overrides,
    )


class LabRedeployCommonSetup(aetest.CommonSetup):
    """Pre-suite setup: optional lab redeploy + matrix-agent provisioning.

    Subsections, in order:

    1. ``redeploy_lab`` — opt-in (``MYCELIUM_LAB_REDEPLOY=1``).
       Wipes and reinstalls the Mycelium stack on every device in the
       testbed. Compose paths skip this; only used against persistent
       lab hardware.
    2. ``verify_cfn_alignment`` — always runs. Reconciles
       ``WORKSPACE_ID`` / ``MAS_ID`` drift between the CFN mgmt
       plane, ``~/.mycelium/config.toml``, and the running backend
       container's env. Cheap when aligned (one CFN GET + one
       ``docker inspect``); only does a backend recreate when drift
       is detected. Skips silently on compose-only paths where
       there is no CFN.
    3. ``provision_matrix_agents`` — always runs (unless explicitly
       disabled). Walks ``_ACTIVE_ROWS``, collects unique
       ``(adapter, handle, host)`` tuples, and calls
       ``Provisioner.ensure_runtime`` on each. The resulting
       :class:`AgentRef` map is stashed in
       ``testscript.parameters['matrix_agents_provisioned']`` so
       per-test setup can do the lightweight ``register_in_room``
       step instead of repeating the heavy spawn each scenario.
    """

    @aetest.subsection
    def redeploy_lab(self, testscript, testbed=None):
        if not _redeploy_requested():
            self.skipped(
                "MYCELIUM_LAB_REDEPLOY unset — skipping lab redeploy",
            )

        if testbed is None:
            self.failed(
                "MYCELIUM_LAB_REDEPLOY=1 but no testbed was provided. Pass --testbed-file testbeds/lab.yaml.",
            )

        cfg = _redeploy_config_from_env()
        log.info(
            "Lab redeploy requested: ref=%s mode=%s include_ui=%s",
            cfg.ref,
            cfg.cleanup_mode.value,
            cfg.include_ui,
        )

        try:
            results = redeploy_testbed(testbed, cfg)
        except ValueError as exc:
            self.failed(f"Lab redeploy aborted: {exc}")
            return

        # Persist results into testscript params so testcases can
        # inspect them if they care (currently nobody does, but it's
        # cheap insurance for debugging a flaky redeploy).
        testscript.parameters["lab_redeploy_results"] = results

        failed = [r for r in results if not r.success]
        if failed:
            details = "; ".join(f"{r.device_name}={r.error}" for r in failed)
            self.failed(f"Lab redeploy failed on {len(failed)} device(s): {details}")

    @aetest.subsection
    def verify_cfn_alignment(self, testscript, testbed=None):
        """Reconcile workspace + default MAS drift before any scenarios run.

        Walks every hub-role device on the testbed and asks
        :func:`libs.lab_redeploy.verify_cfn_alignment` to confirm
        the running backend container's ``WORKSPACE_ID`` /
        ``MAS_ID`` env matches what the CFN mgmt plane actually
        has. When they diverge — common after manual config edits,
        partial reinstalls, or volume wipes — the helper rewrites
        ``config.toml``, runs ``mycelium config apply``, and
        force-recreates the backend so new rooms get a real
        ``mas_id`` assigned at create-time.

        Why this lives in CommonSetup and not in
        :meth:`redeploy_lab`:

        - ``redeploy_lab`` is opt-in (``MYCELIUM_LAB_REDEPLOY=1``)
          and only fires on a full wipe-and-redeploy. The drift
          this catches accumulates between redeploys on a
          long-lived lab.
        - The alignment check is **cheap when aligned** (one CFN
          GET + one ``docker inspect``), so running it on every
          ``pyats run`` is essentially free.
        - On compose-only paths (no CFN profile, no
          ``ioc-cfn-mgmt-plane-svc`` container), the helper
          returns ``None`` and we skip silently — compose comes up
          fresh every time and can't drift.

        Opt out via ``MYCELIUM_E2E_SKIP_CFN_ALIGNMENT=1`` for
        environments where the operator is deliberately running
        with a mismatched config (e.g. pointing at a different
        CFN for A/B testing).
        """
        if os.environ.get("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            self.skipped("MYCELIUM_E2E_SKIP_CFN_ALIGNMENT set")

        if testbed is None:
            self.skipped("no testbed — alignment needs device handles")

        hubs: list[tuple[str, object]] = []
        for name, dev in testbed.devices.items():
            custom = getattr(dev, "custom", None) or {}
            role = ""
            if hasattr(custom, "get"):
                role = (custom.get("role") or "").lower()
            if role == "hub":
                hubs.append((name, dev))

        if not hubs:
            log.info(
                "verify_cfn_alignment: no hub-role device in testbed; nothing to align",
            )
            return

        results: list[object] = []
        for name, hub in hubs:
            custom = getattr(hub, "custom", None) or {}
            backend_url = "http://localhost:8000"
            if hasattr(custom, "get"):
                backend_url = (
                    custom.get("mycelium_backend_url") or os.environ.get("MYCELIUM_BACKEND_URL") or backend_url
                )

            result = verify_cfn_alignment(hub, backend_url=backend_url)
            if result is None:
                # No CFN / backend on this host — perfectly fine
                # on compose paths. Log once and move on.
                log.info(
                    "  ↳ %s: no CFN backend running here, skipped",
                    name,
                )
                continue

            results.append(result)
            # Pretty-print structured logs so the operator can
            # see exactly which step (probe / read env / persist
            # / recreate / re-check) succeeded.
            for phase, ok, detail in result.logs:
                tag = "  ✓" if ok else "  ✗"
                bare = detail if len(detail) < 200 else detail[:200] + "…"
                log.info("  %s  %s: %s — %s", name, tag, phase, bare)

        testscript.parameters["cfn_alignment_results"] = results

        failures = [r for r in results if not r.success]
        if failures:
            details = "; ".join(
                f"{getattr(r, 'device_name', '?')}={getattr(r, 'error', None) or 'see logs'}" for r in failures
            )
            self.failed(f"verify_cfn_alignment: drift on {len(failures)} hub(s) could not be corrected: {details}")

    @aetest.subsection
    def provision_matrix_agents(self, testscript, testbed=None):
        """Idempotently provision every agent the active rows need.

        For each unique ``(adapter, handle, host)`` in
        ``_ACTIVE_ROWS``:

        - Resolve the host name to a pyATS Device on the testbed.
        - ``check_prereqs(device)`` — surface missing adapters as
          a single skipped subsection rather than a swarm of
          per-scenario skips later.
        - ``ensure_runtime(device, handle)`` — heavyweight idempotent
          create. Defaults to no-op for cursor/hermes; openclaw
          actually spawns the OpenClaw runtime + writes a manifest
          in the bootstrap room.

        Stashes a ``(adapter, handle, host) -> AgentRef`` map in
        ``testscript.parameters['matrix_agents_provisioned']``.

        Opt out via ``MYCELIUM_E2E_SKIP_AGENT_PROVISIONING=1`` for
        environments where agents are pre-baked and creating them
        again would fail (e.g. running scenarios against a shared
        prod-like environment for smoke-testing).
        """
        if os.environ.get("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            log.info("provision_matrix_agents: skipped via env opt-out")
            testscript.parameters["matrix_agents_provisioned"] = {}
            self.skipped("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING set")

        if testbed is None:
            self.skipped(
                "no testbed available; provision_matrix_agents requires host -> device resolution",
            )

        if not _ACTIVE_ROWS:
            log.info("provision_matrix_agents: no active rows; nothing to do")
            testscript.parameters["matrix_agents_provisioned"] = {}
            return

        # Build a deduped set of (adapter, handle, host) tuples
        # across every active row. ``ensure_runtime`` is idempotent
        # so re-running for the same handle is fine, but
        # de-duplicating here keeps the subsection logs scannable.
        wants: set[tuple[str, str, str]] = set()
        for row in _ACTIVE_ROWS:
            for ag in row.get("agents", []):
                wants.add((ag["adapter"], ag["handle"], ag["host"]))

        log.info(
            "provision_matrix_agents: ensuring %d unique agent(s) across %d row(s)",
            len(wants),
            len(_ACTIVE_ROWS),
        )

        # Reclaim ownership of ``~/.mycelium`` on each host we'll
        # touch. The backend (Docker container, runs as root) creates
        # room/agent files via a volume mount, so successive
        # ``mycelium agent create`` calls hit "owned by root" write
        # failures on a freshly-redeployed box. One sudo chown per
        # host before we start makes the rest of the subsection
        # work for the user account the CLI runs as.
        unique_hosts = {host for (_, _, host) in wants}
        for host in sorted(unique_hosts):
            device = testbed.devices.get(host)
            if device is None:
                continue
            try:
                host_exec.execute(
                    device,
                    'if [ -d "$HOME/.mycelium" ]; then '
                    'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                    "2>/dev/null || true; fi",
                    shell=True,
                    timeout=20.0,
                )
                log.info("  ↳ chowned ~/.mycelium on %s", host)
            except HostExecError as exc:
                log.warning("  ↳ chown failed on %s (continuing): %s", host, exc)

        provisioned: dict[tuple[str, str, str], AgentRef] = {}
        failures: list[str] = []
        for adapter, handle, host in sorted(wants):
            device = testbed.devices.get(host)
            if device is None:
                failures.append(f"{handle}@{host}: testbed has no device named {host!r}")
                continue

            try:
                provisioner = get_provisioner(adapter)
            except KeyError as exc:
                failures.append(f"{handle}@{host}: {exc}")
                continue

            try:
                provisioner.check_prereqs(device)
            except (PrereqMissing, HostExecError) as exc:
                failures.append(f"{handle}@{host} ({adapter}): prereq missing — {exc}")
                continue

            try:
                ref = provisioner.ensure_runtime(device, handle)
            except PrereqMissing as exc:
                failures.append(f"{handle}@{host} ({adapter}): ensure_runtime — {exc}")
                continue
            except HostExecError as exc:
                failures.append(f"{handle}@{host} ({adapter}): transport — {exc}")
                continue

            provisioned[(adapter, handle, host)] = ref
            log.info(
                "  ✓ %s/%s on %s (pre_existing=%s)",
                adapter,
                handle,
                host,
                ref.metadata.get("pre_existing", "n/a"),
            )

        testscript.parameters["matrix_agents_provisioned"] = provisioned

        if failures:
            # Bail noisily — scenarios that depend on these agents
            # would skip with confusing errors otherwise. Listing
            # them all in one go is friendlier than 30 separate
            # "prereq missing" skips downstream.
            joined = "\n  ".join(failures)
            self.failed(f"provision_matrix_agents: {len(failures)} agent(s) could not be ensured:\n  {joined}")


class MatrixCommonCleanup(aetest.CommonCleanup):
    """Suite-level teardown for matrix-provisioned agents.

    Gates on ``MYCELIUM_E2E_KEEP_AGENTS`` — devs iterating on a
    flaky scenario want their OpenClaw agents to stick around between
    runs so they don't pay the spawn cost over and over. The lab CI
    job leaves the env var unset and runs full teardown so successive
    runs don't accumulate stale gateway-side state.
    """

    @aetest.subsection
    def teardown_matrix_agents(self, testscript, testbed=None):
        if os.environ.get("MYCELIUM_E2E_KEEP_AGENTS", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            self.skipped(
                "MYCELIUM_E2E_KEEP_AGENTS set — leaving runtime agents alive",
            )

        if testbed is None:
            self.skipped("no testbed; runtime teardown needs device handles")

        provisioned: dict[tuple[str, str, str], AgentRef] = testscript.parameters.get("matrix_agents_provisioned") or {}
        if not provisioned:
            log.info("teardown_matrix_agents: nothing to tear down")
            return

        for (adapter, handle, host), ref in sorted(provisioned.items()):
            device = testbed.devices.get(host)
            if device is None:
                log.warning(
                    "teardown_matrix_agents: %s/%s — device %r vanished, skipping",
                    adapter,
                    handle,
                    host,
                )
                continue
            try:
                provisioner = get_provisioner(adapter)
            except KeyError:
                # An adapter that was loadable in setup but isn't
                # now would be a very weird state — log and move on
                # rather than blocking teardown.
                log.warning(
                    "teardown_matrix_agents: %s/%s — provisioner %r gone, skipping",
                    adapter,
                    handle,
                    adapter,
                )
                continue

            try:
                provisioner.teardown_runtime(device, ref)
                log.info("  ✓ tore down %s/%s on %s", adapter, handle, host)
            except Exception as exc:  # noqa: BLE001 - teardown is best-effort
                log.warning(
                    "  ✗ %s/%s teardown failed (ignored): %s",
                    adapter,
                    handle,
                    exc,
                )


# Inject generated classes into the module namespace so pyATS's class
# discovery picks them up. Names look like ``TwoAgentConsensus_oc_cu``.
#
# pyATS discovers testcase classes by walking the testscript's
# ``__dict__`` and filtering on ``cls.__module__ == testscript_module``.
# Our classes were created via ``type(name, (_ConsensusBase,), ...)``
# inside ``testcases.scenarios.make_scenarios``, so they inherit that
# module name and would otherwise be silently rejected. Rebrand each
# class to this module so discovery (and downstream reporting) treats
# them as native suite members.
globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


# ── direct-run entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    aetest.main()
