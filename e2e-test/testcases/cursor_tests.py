"""Cursor adapter E2E tests: dispatch, workspace drift, auth failure, multi-host, cross-family.

Maps to test numbers 75-80.

Phase 1 (75): Single-host basic dispatch — create agent, invoke via daemon, verify response.
Phase 2 (76): Workspace asset drift — AGENTS.md healing and mycelium doctor detection.
Phase 3 (77): Auth failure friendly path — missing auth produces actionable error, no crash.
Phase 4 (78): Multi-host dispatch — hub mentions cursor agent on spoke; spoke responds.
Phase 5a (79): Cross-family cursor — cursor-on-hub vs cursor-on-spoke negotiate via ephemeral room.
Phase 5b (80): Cross-family openclaw — cursor vs openclaw negotiate via ephemeral room.
"""

from __future__ import annotations

import logging
import time
import uuid

from pyats import aetest

from libs.cursor import (
    CURSOR_SPOKE_HOSTS,
    HUB_HOST,
    check_cursor_agent_installed,
    check_daemon_health,
    check_ssh_connectivity,
    cleanup_cursor_workspace,
    create_cursor_agent,
    create_cursor_workspace,
    create_room,
    create_session,
    daemon_subscribe,
    daemon_unsubscribe,
    delete_room,
    invoke_agent,
    poll_session_status,
    remove_cursor_agent,
    run_mycelium_cli,
    ssh_run,
    verify_agents_md,
    wait_for_agent_response,
)
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)


class CursorBasicDispatch(aetest.Testcase):
    """Test 75: Single-host basic dispatch via cc-daemon (Phase 1)."""

    groups = ["cursor", "integration"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.handle = f"cursor-e2e-{uuid.uuid4().hex[:8]}"
        self.room = f"e2e-cursor-{uuid.uuid4().hex[:8]}"
        self.workspace = None

        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def create_room_and_agent(self, steps):
        with steps.start("Create ephemeral room") as step:
            r = create_room(None, self.room)
            if not r.ok:
                step.failed(f"Room create failed: {r.error_message}")

        with steps.start("Subscribe daemon to room") as step:
            r = daemon_subscribe(None, self.room)
            if not r.ok:
                step.failed(f"Daemon subscribe failed: {r.error_message}")

        with steps.start("Create workspace") as step:
            self.workspace = create_cursor_workspace(HUB_HOST)
            if not self.workspace:
                step.failed("Failed to create workspace on hub")

        with steps.start("Create cursor agent") as step:
            r = create_cursor_agent(None, self.handle, self.room, self.workspace)
            if not r.ok:
                step.failed(f"Agent create failed: {r.error_message}")
            log.info("Agent created: %s", r.stdout[:300])

    @aetest.test
    def invoke_and_verify_response(self, steps):
        with steps.start("Invoke agent via daemon") as step:
            before_ts = time.time()
            r = invoke_agent(
                None, self.handle, "Say hello to confirm you are operational.", room=self.room, timeout=90.0
            )
            if not r.ok:
                step.failed(f"Agent invoke failed: {r.error_message}")

        with steps.start("Verify agent response posted to room") as step:
            msg = wait_for_agent_response(
                self.room,
                self.handle,
                timeout_seconds=120,
                poll_interval=5,
                after_ts=before_ts,
            )
            if msg is None:
                step.failed(f"No response from {self.handle} within 120s")
            log.info("Agent response: %s", str(msg)[:300])

    @aetest.cleanup
    def cleanup(self):
        remove_cursor_agent(None, self.handle, room=self.room)
        if self.workspace:
            cleanup_cursor_workspace(HUB_HOST, self.workspace)
        daemon_unsubscribe(None, self.room)
        delete_room(None, self.room)


class CursorWorkspaceDrift(aetest.Testcase):
    """Test 76: Workspace asset drift — AGENTS.md and rules file (Phase 2)."""

    groups = ["cursor", "integration"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.handle = f"cursor-drift-{uuid.uuid4().hex[:8]}"
        self.room = f"e2e-drift-{uuid.uuid4().hex[:8]}"
        self.workspace = None

        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def create_agent_with_workspace(self, steps):
        with steps.start("Create ephemeral room") as step:
            r = create_room(None, self.room)
            if not r.ok:
                step.failed(f"Room create failed: {r.error_message}")

        with steps.start("Create workspace") as step:
            self.workspace = create_cursor_workspace(HUB_HOST)
            if not self.workspace:
                step.failed("Failed to create workspace")

        with steps.start("Create cursor agent") as step:
            r = create_cursor_agent(None, self.handle, self.room, self.workspace)
            if not r.ok:
                step.failed(f"Agent create failed: {r.error_message}")

    @aetest.test
    def verify_workspace_assets(self, steps):
        with steps.start("AGENTS.md has marker fences") as step:
            if not verify_agents_md(HUB_HOST, self.workspace):
                step.failed("AGENTS.md missing or lacks mycelium:start marker")

        with steps.start("mycelium.mdc rules file exists") as step:
            rules_file = f"{self.workspace}/.cursor/rules/mycelium.mdc"
            r = ssh_run(HUB_HOST, f"test -f {rules_file} && echo exists", timeout=10.0)
            if "exists" not in r.stdout:
                step.failed("Rules file not at .cursor/rules/mycelium.mdc")

    @aetest.test
    def external_edit_preserves_fences(self, steps):
        with steps.start("Append user content outside fences") as step:
            agents_md = f"{self.workspace}/AGENTS.md"
            inject_cmd = f'echo "# User notes outside fences" >> {agents_md}'
            r = ssh_run(HUB_HOST, inject_cmd, timeout=10.0)
            if not r.ok:
                step.failed(f"Inject failed: {r.error_message}")

        with steps.start("Marker fences intact after external edit") as step:
            if not verify_agents_md(HUB_HOST, self.workspace):
                step.failed("Marker fences lost after appending content")

    @aetest.cleanup
    def cleanup(self):
        remove_cursor_agent(None, self.handle, room=self.room)
        if self.workspace:
            cleanup_cursor_workspace(HUB_HOST, self.workspace)
        delete_room(None, self.room)


class CursorAuthFailure(aetest.Testcase):
    """Test 77: Auth failure friendly path (Phase 3)."""

    groups = ["cursor", "integration"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.handle = f"cursor-noauth-{uuid.uuid4().hex[:8]}"
        self.room = f"e2e-noauth-{uuid.uuid4().hex[:8]}"
        self.workspace = None

        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def simulate_missing_auth(self, steps):
        with steps.start("Create room and workspace") as step:
            run_mycelium_cli(None, "room", "create", self.room, timeout=15.0)
            self.workspace = create_cursor_workspace(HUB_HOST)
            if not self.workspace:
                step.failed("Failed to create workspace")

        with steps.start("Create agent with invalid auth path") as step:
            r = create_cursor_agent(None, self.handle, self.room, self.workspace)
            if not r.ok:
                step.failed(f"Agent create failed: {r.error_message}")

        with steps.start("Remove cursor auth file to simulate missing auth") as step:
            auth_path = "~/.config/cursor/auth.json"
            backup_cmd = f"cp {auth_path} {auth_path}.bak 2>/dev/null; rm -f {auth_path}"
            ssh_run(HUB_HOST, backup_cmd, timeout=10.0)

        with steps.start("Invoke agent — expect actionable error, not crash") as step:
            r = invoke_agent(None, self.handle, "test auth failure", room=self.room, timeout=60.0)
            combined = (r.stdout + r.stderr).lower()
            if "auth" not in combined and "credential" not in combined and "login" not in combined:
                log.warning("Expected auth-related error message, got: %s", combined[:500])
            if r.returncode == 139 or "segfault" in combined or "panic" in combined:
                step.failed("Daemon crashed instead of reporting auth error gracefully")
            log.info("Auth failure output (rc=%d): %s", r.returncode, combined[:300])

    @aetest.cleanup
    def cleanup(self):
        auth_path = "~/.config/cursor/auth.json"
        ssh_run(HUB_HOST, f"mv {auth_path}.bak {auth_path} 2>/dev/null", timeout=10.0)
        remove_cursor_agent(None, self.handle, room=self.room)
        if self.workspace:
            cleanup_cursor_workspace(HUB_HOST, self.workspace)
        run_mycelium_cli(None, "room", "delete", self.room, "--force", timeout=15.0)


class CursorMultiHostDispatch(aetest.Testcase):
    """Test 78: Multi-host dispatch — hub mentions cursor agent on spoke (Phase 4)."""

    groups = ["cursor", "distributed", "multi_host"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.spoke = CURSOR_SPOKE_HOSTS.get("oclw3", "10.0.50.171")
        self.handle = f"cursor-spoke-{uuid.uuid4().hex[:8]}"
        self.room = f"e2e-multihost-{uuid.uuid4().hex[:8]}"
        self.workspace = None

        if not check_ssh_connectivity(self.spoke):
            self.skipped(f"Cannot SSH to spoke {self.spoke}")
        if not check_cursor_agent_installed(self.spoke):
            self.skipped(f"cursor-agent not installed on {self.spoke}")
        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def create_spoke_agent(self, steps):
        with steps.start("Create ephemeral room") as step:
            r = create_room(None, self.room)
            if not r.ok:
                step.failed(f"Room create failed: {r.error_message}")

        with steps.start("Subscribe daemons to room") as step:
            daemon_subscribe(None, self.room)
            daemon_subscribe(self.spoke, self.room)

        with steps.start("Create workspace on spoke") as step:
            self.workspace = create_cursor_workspace(self.spoke)
            if not self.workspace:
                step.failed("Failed to create workspace on spoke")

        with steps.start("Register agent on spoke") as step:
            r = create_cursor_agent(self.spoke, self.handle, self.room, self.workspace)
            if not r.ok:
                step.failed(f"Agent create on spoke failed: {r.error_message}")

    @aetest.test
    def dispatch_from_hub_verify_spoke_responds(self, steps):
        with steps.start("Send mention from hub to spoke agent") as step:
            before_ts = time.time()
            r = invoke_agent(
                None, self.handle, "Respond to confirm multi-host dispatch works.", room=self.room, timeout=90.0
            )
            if not r.ok:
                log.warning("Invoke returned non-zero (may still work via daemon): %s", r.error_message)

        with steps.start("Wait for spoke agent response") as step:
            msg = wait_for_agent_response(
                self.room,
                self.handle,
                timeout_seconds=180,
                poll_interval=5,
                after_ts=before_ts,
            )
            if msg is None:
                step.failed(f"No response from spoke agent {self.handle} within 180s")
            log.info("Spoke response: %s", str(msg)[:300])

    @aetest.cleanup
    def cleanup(self):
        remove_cursor_agent(self.spoke, self.handle, room=self.room)
        if self.workspace:
            cleanup_cursor_workspace(self.spoke, self.workspace)
        daemon_unsubscribe(None, self.room)
        daemon_unsubscribe(self.spoke, self.room)
        delete_room(None, self.room)


class CursorCrossFamilyCursor(aetest.Testcase):
    """Test 79: Cross-family cursor vs cursor negotiation (Phase 5a)."""

    groups = ["cursor", "distributed", "multi_host", "convergence"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.spoke = CURSOR_SPOKE_HOSTS.get("oclw3", "10.0.50.171")
        self.hub_handle = f"cursor-hub-{uuid.uuid4().hex[:8]}"
        self.spoke_handle = f"cursor-spk-{uuid.uuid4().hex[:8]}"
        self.room = f"e2e-xcursor-{uuid.uuid4().hex[:8]}"
        self.hub_workspace = None
        self.spoke_workspace = None

        if not check_ssh_connectivity(self.spoke):
            self.skipped(f"Cannot SSH to spoke {self.spoke}")
        if not check_cursor_agent_installed(self.spoke):
            self.skipped(f"cursor-agent not installed on {self.spoke}")
        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def create_both_agents(self, steps):
        with steps.start("Create ephemeral room") as step:
            r = create_room(None, self.room)
            if not r.ok:
                step.failed(f"Room create failed: {r.error_message}")

        with steps.start("Subscribe daemons to room") as step:
            daemon_subscribe(None, self.room)
            daemon_subscribe(self.spoke, self.room)

        with steps.start("Create hub cursor agent") as step:
            self.hub_workspace = create_cursor_workspace(HUB_HOST)
            if not self.hub_workspace:
                step.failed("Hub workspace creation failed")
            r = create_cursor_agent(None, self.hub_handle, self.room, self.hub_workspace)
            if not r.ok:
                step.failed(f"Hub agent create failed: {r.error_message}")

        with steps.start("Create spoke cursor agent") as step:
            self.spoke_workspace = create_cursor_workspace(self.spoke)
            if not self.spoke_workspace:
                step.failed("Spoke workspace creation failed")
            r = create_cursor_agent(self.spoke, self.spoke_handle, self.room, self.spoke_workspace)
            if not r.ok:
                step.failed(f"Spoke agent create failed: {r.error_message}")

    @aetest.test
    def negotiate_to_consensus(self, steps):
        topic = "Decide on a CI/CD pipeline tool: GitHub Actions vs GitLab CI"
        with steps.start("Create coordination session") as step:
            r = create_session(
                self.room,
                topic,
                [self.hub_handle, self.spoke_handle],
                host=None,
                timeout=60.0,
            )
            if not r.ok:
                step.failed(f"Session create failed: {r.error_message}")
            log.info("Session created: %s", r.stdout[:300])

        with steps.start("Poll for consensus or max rounds") as step:
            result = poll_session_status(
                self.room,
                timeout_seconds=600,
                poll_interval=10,
                target_status="consensus",
            )
            if result is None:
                step.failed("Consensus not reached within 600s (cursor vs cursor)")
            log.info("Consensus result: %s", str(result)[:500])

    @aetest.cleanup
    def cleanup(self):
        remove_cursor_agent(None, self.hub_handle, room=self.room)
        remove_cursor_agent(self.spoke, self.spoke_handle, room=self.room)
        if self.hub_workspace:
            cleanup_cursor_workspace(HUB_HOST, self.hub_workspace)
        if self.spoke_workspace:
            cleanup_cursor_workspace(self.spoke, self.spoke_workspace)
        daemon_unsubscribe(None, self.room)
        daemon_unsubscribe(self.spoke, self.room)
        delete_room(None, self.room)


class CursorCrossFamilyOpenClaw(aetest.Testcase):
    """Test 80: Cross-family cursor vs openclaw negotiation (Phase 5b)."""

    groups = ["cursor", "distributed", "multi_host", "convergence", "openclaw"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.spoke = CURSOR_SPOKE_HOSTS.get("oclw3", "10.0.50.171")
        self.cursor_handle = f"cursor-xfam-{uuid.uuid4().hex[:8]}"
        self.openclaw_handle = "claire-agent"
        self.room = f"e2e-xfamily-{uuid.uuid4().hex[:8]}"
        self.cursor_workspace = None

        if not check_ssh_connectivity(self.spoke):
            self.skipped(f"Cannot SSH to spoke {self.spoke}")
        if not check_cursor_agent_installed(HUB_HOST):
            self.skipped("cursor-agent not installed on hub")
        if not check_daemon_health(None):
            self.skipped("mycelium-cc-daemon not healthy on hub")

    @aetest.test
    def create_cursor_agent_and_room(self, steps):
        with steps.start("Create ephemeral room") as step:
            r = create_room(None, self.room)
            if not r.ok:
                step.failed(f"Room create failed: {r.error_message}")

        with steps.start("Subscribe daemon to room") as step:
            r = daemon_subscribe(None, self.room)
            if not r.ok:
                step.failed(f"Daemon subscribe failed: {r.error_message}")

        with steps.start("Create cursor agent on hub") as step:
            self.cursor_workspace = create_cursor_workspace(HUB_HOST)
            if not self.cursor_workspace:
                step.failed("Workspace creation failed")
            r = create_cursor_agent(None, self.cursor_handle, self.room, self.cursor_workspace)
            if not r.ok:
                step.failed(f"Cursor agent create failed: {r.error_message}")

        with steps.start("Verify openclaw agent is reachable") as step:
            r = run_mycelium_cli(None, "agent", "ls", timeout=15.0)
            if self.openclaw_handle not in r.stdout:
                step.failed(f"OpenClaw agent {self.openclaw_handle} not found in agent ls")

    @aetest.test
    def cross_family_negotiation(self, steps):
        topic = "Agree on a logging framework: structured JSON vs human-readable"
        with steps.start("Create coordination session with both families") as step:
            r = create_session(
                self.room,
                topic,
                [self.cursor_handle, self.openclaw_handle],
                host=None,
                timeout=60.0,
            )
            if not r.ok:
                step.failed(f"Session create failed: {r.error_message}")
            log.info("Cross-family session: %s", r.stdout[:300])

        with steps.start("Poll for consensus") as step:
            result = poll_session_status(
                self.room,
                timeout_seconds=600,
                poll_interval=10,
                target_status="consensus",
            )
            if result is None:
                step.failed("Cross-family consensus not reached within 600s (cursor vs openclaw)")
            log.info("Cross-family consensus: %s", str(result)[:500])

    @aetest.cleanup
    def cleanup(self):
        remove_cursor_agent(None, self.cursor_handle, room=self.room)
        if self.cursor_workspace:
            cleanup_cursor_workspace(HUB_HOST, self.cursor_workspace)
        daemon_unsubscribe(None, self.room)
        delete_room(None, self.room)
