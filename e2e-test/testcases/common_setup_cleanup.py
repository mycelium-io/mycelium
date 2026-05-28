"""CommonSetup and CommonCleanup base classes for Mycelium E2E suites.

Every suite script inherits from these to get consistent environment
detection, service client initialization, pre-suite hygiene, and
post-suite teardown. Follows the motific-performance pattern of layered
subsections in CommonSetup with state accumulated in ``testscript.parameters``.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.cfn_api import CfnMgmtAPI, CfnNodeSvcAPI
from libs.environment import EnvironmentInfo, detect_environment
from libs.openclaw import (
    reset_agent_sessions,
    trim_agent_sessions,
    trim_remote_agent_sessions,
    wait_for_agents_idle,
)

log = logging.getLogger(__name__)

# Script-level default parameters — overridden by datafile and job.
parameters = {}

# Agent topology for local + remote hosts
_DEFAULT_LOCAL_AGENTS = ("agent-alpha", "agent-beta", "agent-gamma", "agent-delta")


class MyceliumCommonSetup(aetest.CommonSetup):
    """Shared setup subsections: env detection, service clients, pre-suite hygiene."""

    @aetest.subsection
    def initialize_clients(self, testscript, topology=None):
        """Create API/CLI client instances from topology config."""
        topo = topology or {}
        backend_cfg = topo.get("backend", {})
        cfn_mgmt_cfg = topo.get("cfn_mgmt", {})
        cfn_node_cfg = topo.get("cfn_node_svc", {})
        matrix_cfg = topo.get("matrix", {})

        backend_url = self._resolve_env(backend_cfg.get("base_url", "http://localhost:8000"))
        cfn_mgmt_url = self._resolve_env(cfn_mgmt_cfg.get("base_url", "http://localhost:9000"))
        cfn_svc_url = self._resolve_env(cfn_node_cfg.get("base_url", "http://localhost:9002"))
        matrix_url = self._resolve_env(matrix_cfg.get("base_url", "http://localhost:8008"))
        api_path = backend_cfg.get("api_path", "/api")

        try:
            testscript.parameters["api"] = MyceliumAPI(base_url=backend_url, api_path=api_path)
            testscript.parameters["cli"] = MyceliumCLI()
            testscript.parameters["cfn_mgmt"] = CfnMgmtAPI(base_url=cfn_mgmt_url)
            testscript.parameters["cfn_node_svc"] = CfnNodeSvcAPI(base_url=cfn_svc_url)
        except Exception as exc:
            self.failed(
                f"Client initialization failed: {exc}",
                goto=["common_cleanup"],
            )

        testscript.parameters["matrix_url"] = matrix_url
        testscript.parameters["matrix_config"] = {
            k: self._resolve_env(v) if isinstance(v, str) else v
            for k, v in matrix_cfg.items()
        }
        testscript.parameters["backend_url"] = backend_url

        log.info("Clients initialized: backend=%s cfn_mgmt=%s cfn_svc=%s matrix=%s",
                 backend_url, cfn_mgmt_url, cfn_svc_url, matrix_url)

    @aetest.subsection
    def configure_cli(self, testscript, shared_mycelium_room="mycelium_room"):
        """Ensure the mycelium CLI config points at the correct backend.

        Runs ``mycelium init --api-url <backend>`` to seed
        ``~/.mycelium/config.toml`` if absent, then unconditionally sets
        the API URL and active room via ``config set`` and verifies the
        values were persisted correctly.

        Config keys (from mycelium CLI's ``MyceliumConfig``):
          - ``server.api_url`` — backend URL
          - ``rooms.active``   — default room name
        """
        cli: MyceliumCLI = testscript.parameters["cli"]
        backend_url: str = testscript.parameters["backend_url"]
        room = self._resolve_env(shared_mycelium_room)

        r = cli.run("init", "--api-url", backend_url)
        if not r.ok:
            log.debug("mycelium init returned rc=%d (may already be initialized)", r.returncode)

        expected = {"server.api_url": backend_url, "rooms.active": room}
        for key, value in expected.items():
            r = cli.config_set(key, value)
            if not r.ok:
                log.warning("Failed to set CLI %s: %s", key, r.error_message)

        self._ensure_dotenv()

        errors = []
        for key, value in expected.items():
            r = cli.config_get(key)
            actual = r.stdout.strip() if r.ok else None
            if actual != value:
                errors.append(f"{key}: expected={value!r} got={actual!r}")
        if errors:
            log.warning("CLI config verification failed: %s", "; ".join(errors))

        r = cli.doctor()
        if r.ok:
            log.info("CLI doctor: %s", r.stdout.strip()[:200])
        else:
            log.warning("CLI doctor failed (rc=%d): %s", r.returncode, r.error_message[:200])

        log.info("CLI configured: server.api_url=%s rooms.active=%s", backend_url, room)

    @aetest.subsection
    def detect_environment(self, testscript, room_prefix="e2e-test"):
        """Probe all services and set skip flags."""
        api: MyceliumAPI = testscript.parameters["api"]
        cfn_mgmt: CfnMgmtAPI = testscript.parameters["cfn_mgmt"]
        cfn_node_svc: CfnNodeSvcAPI = testscript.parameters["cfn_node_svc"]
        matrix_url: str = testscript.parameters["matrix_url"]

        env = detect_environment(api, cfn_mgmt, cfn_node_svc, matrix_url, room_prefix)
        testscript.parameters["env"] = env

        if not env.backend_reachable:
            self.failed("Backend unreachable — cannot proceed", goto=["common_cleanup"])

        log.info("Environment: llm=%s cfn=%s matrix=%s blocked=%s",
                 not env.skip_llm_tests, not env.skip_cfn_tests,
                 not env.skip_matrix_tests, env.coordination_blocked_reason)

    @aetest.subsection
    def presuite_hygiene(self, testscript, room_prefix="e2e-test"):
        """Clean stale sessions and trim agent history.

        Must run before create_test_room so we don't delete our own room.
        """
        api: MyceliumAPI = testscript.parameters["api"]
        owned = testscript.parameters.get("owned_rooms", set())

        for prefix in ("e2e-", "dist-e2e-", "mycelium_room:session:"):
            deleted = api.cleanup_rooms(prefix, exclude=owned)
            if deleted:
                log.info("Cleaned %d stale '%s*' rooms", deleted, prefix)

        trimmed = trim_agent_sessions(max_files=5)
        if trimmed:
            log.info("Trimmed %d local session files", trimmed)

        remote_hosts = self._get_remote_hosts(testscript)
        containers = self._get_containers(testscript)
        if remote_hosts:
            trim_remote_agent_sessions(remote_hosts, max_files=5, containers=containers)

    @aetest.subsection
    def create_test_room(self, testscript, room_prefix="e2e-test"):
        """Create the session-scoped test room."""
        room_suffix = str(int(time.time()))[-7:]
        room_name = f"{room_prefix}-{room_suffix}"
        testscript.parameters["room_name"] = room_name
        testscript.parameters["owned_rooms"] = {room_name}

        api: MyceliumAPI = testscript.parameters["api"]
        status, data = api.create_room(room_name, description="pyATS E2E test room")
        if status not in (200, 201):
            self.failed(
                f"Failed to create test room {room_name}: status={status}",
                goto=["common_cleanup"],
            )
        log.info("Test room created: %s", room_name)

    @aetest.subsection
    def reset_agent_sessions(self, testscript):
        """Reset negotiation-carrying sessions via gateway RPC."""
        agents_by_host = self._get_agents_by_host(testscript)
        containers = self._get_containers(testscript)
        ok, failed = reset_agent_sessions(agents_by_host, containers=containers)
        if ok or failed:
            log.info("Session reset: %d ok, %d failed", ok, failed)

    @aetest.subsection
    def wait_agents_idle(self, testscript):
        """Wait for any in-flight agent turns to finish."""
        agents_by_host = self._get_agents_by_host(testscript)
        containers = self._get_containers(testscript)
        counts = wait_for_agents_idle(agents_by_host, timeout=15, poll_interval=2.0, containers=containers)
        busy = {h: c for h, c in counts.items() if c > 0}
        if busy:
            log.warning("Agents still busy after 15s: %s", busy)
        else:
            log.info("All agents idle")

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_dotenv() -> None:
        """Write ``~/.mycelium/.env`` with LLM credentials from the environment.

        The CLI reads this file for LLM_API_KEY, LLM_BASE_URL, and
        LLM_MODEL when running commands like ``synthesize`` and ``catchup``.
        ``mycelium init`` may not create it, so we ensure it exists.
        """
        env_path = pathlib.Path.home() / ".mycelium" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            val = os.environ.get(var)
            if val:
                lines.append(f"{var}={val}")

        if lines:
            env_path.write_text("\n".join(lines) + "\n")
            log.info("Wrote %s (%d vars)", env_path, len(lines))
        elif not env_path.exists():
            env_path.touch()
            log.debug("Created empty %s (no LLM vars in environment)", env_path)

    @staticmethod
    def _resolve_env(value: str) -> str:
        """Resolve %ENV{VAR, default} patterns in datafile values."""
        if not value.startswith("%ENV{"):
            return value
        inner = value[5:-1]  # strip %ENV{ and }
        parts = inner.split(",", 1)
        var_name = parts[0].strip()
        default = parts[1].strip() if len(parts) > 1 else ""
        return os.environ.get(var_name, default)

    @staticmethod
    def _get_remote_hosts(testscript) -> list[str]:
        remote_cfg = testscript.parameters.get("remote_hosts", {})
        hosts = []
        for host_info in remote_cfg.values():
            ip = host_info.get("ip", "")
            if ip.startswith("%ENV{"):
                ip = MyceliumCommonSetup._resolve_env(ip)
            if ip:
                hosts.append(ip)
        if not hosts:
            hosts = [
                os.environ.get("OCLW3_IP", "10.0.50.171"),
                os.environ.get("OCLW5_IP", "10.0.50.142"),
            ]
        return hosts

    @staticmethod
    def _get_containers(testscript) -> dict[str, str]:
        """Extract Docker container mappings from remote_hosts config.

        Returns a dict mapping host IP/name to container name for hosts
        that use the docker transport (set ``transport: docker`` and
        ``container: <name>`` in the datafile's remote_hosts section).
        """
        remote_cfg = testscript.parameters.get("remote_hosts", {})
        containers: dict[str, str] = {}
        for host_info in remote_cfg.values():
            transport = host_info.get("transport", "")
            ctr = host_info.get("container", "")
            ip = host_info.get("ip", "")
            if ip.startswith("%ENV{"):
                ip = MyceliumCommonSetup._resolve_env(ip)
            if transport == "docker" and ctr and ip:
                containers[ip] = ctr
        return containers

    @staticmethod
    def _get_agents_by_host(testscript) -> dict[str | None, tuple[str, ...]]:
        agents_cfg = testscript.parameters.get("agents", {})
        result: dict[str | None, tuple[str, ...]] = {}
        local_agents = tuple(agents_cfg.get("local", {}).keys()) or _DEFAULT_LOCAL_AGENTS
        result[None] = local_agents

        remote_cfg = testscript.parameters.get("remote_hosts", {})
        for host_info in remote_cfg.values():
            ip = host_info.get("ip", "")
            if ip.startswith("%ENV{"):
                ip = MyceliumCommonSetup._resolve_env(ip)
            agent_names = tuple(host_info.get("agents", {}).keys())
            if ip and agent_names:
                result[ip] = agent_names
        if not remote_cfg:
            result[os.environ.get("OCLW3_IP", "10.0.50.171")] = ("claire-agent",)
            result[os.environ.get("OCLW5_IP", "10.0.50.142")] = ("oclw5-agent",)
        return result


class MyceliumCommonCleanup(aetest.CommonCleanup):
    """Shared cleanup: delete test rooms, reap leaked sessions."""

    @aetest.subsection
    def cleanup_test_room(self, testscript):
        """Delete the session-scoped test room."""
        api: MyceliumAPI = testscript.parameters.get("api")
        room_name = testscript.parameters.get("room_name")
        if api and room_name:
            api.delete_room(room_name)
            log.info("Deleted test room: %s", room_name)

    @aetest.subsection
    def reap_leaked_sessions(self, testscript):
        """Find and delete any rooms still in negotiating/waiting state."""
        api: MyceliumAPI = testscript.parameters.get("api")
        owned = testscript.parameters.get("owned_rooms", set())
        if not api:
            return

        status, rooms = api.list_rooms()
        if status != 200:
            return

        leaked_states = ("negotiating", "waiting", "synthesizing")
        room_list = rooms if isinstance(rooms, list) else []
        reaped = 0
        for room in room_list:
            name = room.get("name", "")
            base = name.split(":session:")[0]
            if base not in owned:
                continue
            if room.get("coordination_state") in leaked_states:
                st, _ = api.delete_room(name)
                if 200 <= st < 300:
                    reaped += 1
                    log.info("Reaped leaked session: %s (state=%s)", name, room.get("coordination_state"))
        if reaped:
            log.info("Reaped %d leaked sessions total", reaped)
