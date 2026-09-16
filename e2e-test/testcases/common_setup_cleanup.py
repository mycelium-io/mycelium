"""CommonSetup and CommonCleanup base classes for SLIM-native Mycelium E2E suites."""

from __future__ import annotations

import logging
import os
import pathlib
import time
from typing import Any

from pyats import aetest

from libs.environment import EnvironmentInfo, detect_environment
from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

parameters = {}


def require_devices(section: Any, testscript: Any, *device_names: str) -> None:
    """Skip *section* if any of *device_names* are absent from the loaded testbed.

    Call this at the top of a testcase ``@aetest.setup`` or ``@aetest.test``
    when the test requires devices beyond the basic ``hub``::

        @aetest.setup
        def check_topology(self, testscript):
            require_devices(self, testscript, "spoke1", "spoke2")

    If the testbed was not loaded (no ``--testbed-file`` passed), the check
    is skipped — we assume single-host mode where all tests can run.
    """
    devices = testscript.parameters.get("testbed_devices") or {}
    if not devices:
        return  # no testbed loaded — single-host mode, don't gate
    missing = [d for d in device_names if d not in devices]
    if missing:
        section.skipped(
            f"Testbed does not include device(s) {missing!r} — "
            f"available: {list(devices.keys())}. "
            f"Pass a testbed that includes these devices to run this test."
        )


class MyceliumCommonSetup(aetest.CommonSetup):
    """Setup: initialize clients, configure CLI, probe environment, create test room."""

    @aetest.subsection
    def read_testbed_topology(self, testscript, testbed=None):
        """Read device topology from the loaded testbed and store in parameters.

        The ``testbed`` argument is automatically injected by pyATS when
        ``--testbed-file`` is passed to ``pyats run job``.

        Stores ``testbed_devices`` (dict of device_name → custom attrs) and
        ``testbed_name`` so testcases can gate on available topology without
        importing pyATS topology objects directly.
        """
        if testbed is None:
            testscript.parameters["testbed_devices"] = {}
            testscript.parameters["testbed_name"] = "none"
            log.info("No testbed loaded — running in single-host mode")
            return

        devices = {}
        for name, device in testbed.devices.items():
            custom = {}
            if hasattr(device, "custom"):
                custom = dict(device.custom) if device.custom else {}
            devices[name] = custom

        testscript.parameters["testbed_devices"] = devices
        testscript.parameters["testbed_name"] = getattr(testbed, "name", "unknown")
        testscript.parameters["testbed"] = testbed

        log.info(
            "Testbed: name=%s devices=%s",
            testscript.parameters["testbed_name"],
            list(devices.keys()),
        )

        # Use harness_backend_url (localhost, auth-bypassed) when running on the hub.
        # Fall back to backend_url (external IP, needs auth) for remote runners.
        # Never override an explicit MYCELIUM_BACKEND_URL env var.
        hub_custom = devices.get("hub", {})
        if not os.environ.get("MYCELIUM_BACKEND_URL"):
            tb_url = (
                hub_custom.get("harness_backend_url")
                or hub_custom.get("backend_url")
                or ""
            )
            if tb_url:
                resolved = self._resolve_env(tb_url)
                os.environ["MYCELIUM_BACKEND_URL"] = resolved
                log.info("Backend URL from testbed hub.custom: %s", resolved)

    @aetest.subsection
    def initialize_clients(self, testscript, topology=None):
        topo = topology or {}
        backend_cfg = topo.get("backend", {})
        backend_url = self._resolve_env(backend_cfg.get("base_url", "http://localhost:8000"))
        api_path = backend_cfg.get("api_path", "/api")

        try:
            testscript.parameters["api"] = MyceliumAPI(base_url=backend_url, api_path=api_path)
            testscript.parameters["cli"] = MyceliumCLI()
            testscript.parameters["backend_url"] = backend_url
        except Exception as exc:
            self.failed(f"Client initialization failed: {exc}", goto=["common_cleanup"])

        log.info("Clients initialized: backend=%s", backend_url)

    @aetest.subsection
    def configure_cli(self, testscript):
        """Point the CLI at the test backend and verify the config."""
        cli: MyceliumCLI = testscript.parameters["cli"]
        backend_url: str = testscript.parameters["backend_url"]

        r = cli.run("init", "--api-url", backend_url)
        if not r.ok:
            log.debug("mycelium init rc=%d (may already be initialized)", r.returncode)

        r = cli.config_set("server.api_url", backend_url)
        if not r.ok:
            log.warning("Failed to set server.api_url: %s", r.error_message)

        self._ensure_dotenv()

        # `init`/`config_set` above can rewrite config.toml via an atomic
        # tempfile-then-rename, which drops whatever permissive mode the CI
        # workflow set earlier and leaves it owner-only. Later local-write
        # CLI calls (agent create, engine create) may run as a different
        # uid (MYCELIUM_LOCAL_WRITE_UID, to match the backend container's
        # uid — see libs/mycelium_cli.py) and need to read this file too.
        try:
            (pathlib.Path.home() / ".mycelium").chmod(0o777)
            for p in (pathlib.Path.home() / ".mycelium").glob("*"):
                if p.is_file():
                    p.chmod(0o666)
        except OSError:
            pass

        r = cli.doctor()
        if r.ok:
            log.info("CLI doctor: %s", r.stdout.strip()[:200])
        else:
            log.warning("CLI doctor rc=%d: %s", r.returncode, r.error_message[:200])

    @aetest.subsection
    def detect_environment(self, testscript):
        api: MyceliumAPI = testscript.parameters["api"]
        env = detect_environment(api)
        testscript.parameters["env"] = env

        if not env.backend_reachable:
            self.failed("Backend unreachable — cannot proceed", goto=["common_cleanup"])

        log.info(
            "Environment: slim=%s llm=%s",
            env.slim_reachable,
            not env.skip_llm_tests,
        )

    @aetest.subsection
    def presuite_hygiene(self, testscript, room_prefix="qa-"):
        """Clean stale QA rooms from previous runs."""
        from jobs._common import no_cleanup
        if no_cleanup():
            log.info("presuite_hygiene: skipped (MYCELIUM_E2E_NO_CLEANUP)")
            return
        api: MyceliumAPI = testscript.parameters["api"]
        owned = testscript.parameters.get("owned_rooms", set())
        for prefix in ("qa-coord-fresh-", "qa-memory-", "qa-cross-episode-stub-"):
            deleted = api.cleanup_rooms(prefix, exclude=owned)
            if deleted:
                log.info("Cleaned %d stale '%s*' rooms", deleted, prefix)

    @aetest.subsection
    def create_test_room(self, testscript, room_prefix="qa-coord-fresh"):
        suffix = f"{int(time.time()) % 10_000_000:07d}"
        room_name = f"{room_prefix}-{suffix}"
        testscript.parameters["room_name"] = room_name
        testscript.parameters.setdefault("owned_rooms", set()).add(room_name)

        api: MyceliumAPI = testscript.parameters["api"]
        status, _ = api.create_room(room_name, description="E2E test room")
        if status not in (200, 201):
            self.failed(
                f"Failed to create test room {room_name}: status={status}",
                goto=["common_cleanup"],
            )
        log.info("Test room created: %s", room_name)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_dotenv() -> None:
        env_path = pathlib.Path.home() / ".mycelium" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            val = os.environ.get(var)
            if val:
                lines.append(f"{var}={val}")
        if lines:
            env_path.write_text("\n".join(lines) + "\n")
        elif not env_path.exists():
            env_path.touch()

    @staticmethod
    def _resolve_env(value: str) -> str:
        if not value.startswith("%ENV{"):
            return value
        inner = value[5:-1]
        parts = inner.split(",", 1)
        var_name = parts[0].strip()
        default = parts[1].strip() if len(parts) > 1 else ""
        return os.environ.get(var_name, default)


class MyceliumCommonCleanup(aetest.CommonCleanup):
    """Cleanup: delete owned test rooms."""

    @aetest.subsection
    def cleanup_test_rooms(self, testscript):
        from jobs._common import no_cleanup, keep_rooms
        if no_cleanup():
            self.skipped("MYCELIUM_E2E_NO_CLEANUP set — teardown skipped")
            return
        if keep_rooms():
            log.info("cleanup: skipping room deletion (MYCELIUM_E2E_KEEP_ROOMS)")
            return

        api: MyceliumAPI = testscript.parameters.get("api")
        if not api:
            return

        owned: set[str] = set(testscript.parameters.get("owned_rooms") or set())
        room_name = testscript.parameters.get("room_name")
        if room_name:
            owned.add(room_name)

        for name in sorted(owned):
            st, _ = api.delete_room(name)
            if 200 <= st < 300:
                log.info("Deleted room: %s", name)
            else:
                log.debug("Room %s already gone (status=%d)", name, st)

    @aetest.subsection
    def cleanup_stale_rooms(self, testscript):
        from jobs._common import no_cleanup, keep_rooms
        if no_cleanup() or keep_rooms():
            return
        api: MyceliumAPI = testscript.parameters.get("api")
        if not api:
            return
        owned = testscript.parameters.get("owned_rooms") or set()
        for prefix in ("qa-coord-fresh-", "qa-memory-", "qa-cross-episode-stub-"):
            deleted = api.cleanup_rooms(prefix, exclude=owned)
            if deleted:
                log.info("Stale sweep: deleted %d '%s*' rooms", deleted, prefix)
