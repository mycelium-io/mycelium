"""Integration adapter E2E tests: Claude Code skill install, status, daemon, and Cursor stubs.

Maps to test numbers 70-79.

These tests exercise the mycelium CLI adapter system rather than the core
room/memory/coordination features.  The skill-install tests (70-72) are
file-system-only and fast — no LLM or OpenClaw required.  The daemon tests
(73-74) need a running backend.  Cursor tests (75+) are gated on the adapter
being implemented.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from pyats import aetest

from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)


class ClaudeCodeSkillInstall(aetest.Testcase):
    """Test 70: Claude Code adapter add installs the SKILL.md file."""

    groups = ["integration", "sanity"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()
        self.skill_path = Path.home() / ".claude" / "skills" / "mycelium" / "SKILL.md"
        self.had_skill_before = self.skill_path.exists()

    @aetest.test
    def adapter_add(self, steps):
        with steps.start("Run mycelium adapter add claude-code") as step:
            r = self.cli.run("adapter", "add", "claude-code", "--reinstall", "--yes", timeout=30)
            if not r.ok:
                step.failed(f"adapter add claude-code failed: {r.error_message}")
            log.info("adapter add output: %s", r.stdout[:500])

    @aetest.test
    def skill_file_exists(self, steps):
        with steps.start("Verify SKILL.md exists") as step:
            if not self.skill_path.exists():
                step.failed(f"SKILL.md not found at {self.skill_path}")
            content = self.skill_path.read_text()
            if len(content) < 100:
                step.failed(f"SKILL.md is suspiciously short ({len(content)} bytes)")
            log.info("SKILL.md size: %d bytes", len(content))

    @aetest.test
    def skill_content_valid(self, steps):
        with steps.start("SKILL.md contains expected sections") as step:
            content = self.skill_path.read_text()
            expected_markers = ["mycelium", "room", "memory"]
            missing = [m for m in expected_markers if m.lower() not in content.lower()]
            if missing:
                step.failed(f"SKILL.md missing expected content: {missing}")


class ClaudeCodeAdapterStatus(aetest.Testcase):
    """Test 71: adapter status reports the claude-code skill as healthy."""

    groups = ["integration", "sanity"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()

    @aetest.test
    def status_check(self, steps):
        with steps.start("Run mycelium adapter status claude-code") as step:
            r = self.cli.run("adapter", "status", "claude-code", timeout=15)
            if not r.ok:
                step.failed(f"adapter status failed: {r.error_message}")
            combined = r.stdout + r.stderr
            log.info("adapter status output: %s", combined[:500])

    @aetest.test
    def status_shows_skill(self, steps):
        with steps.start("Status output references the skill") as step:
            r = self.cli.run("adapter", "status", "claude-code", timeout=15)
            combined = (r.stdout + r.stderr).lower()
            if "skill" not in combined and "mycelium" not in combined:
                step.failed("Status output does not reference skill or mycelium")

    @aetest.test
    def json_status(self, steps):
        with steps.start("JSON status output is valid") as step:
            r = self.cli.run("--json", "adapter", "status", "claude-code", timeout=15)
            if not r.ok:
                step.failed(f"JSON status failed: {r.error_message}")
            data = r.json
            if data is None:
                log.info("JSON parse returned None; raw: %s", r.stdout[:300])
                step.passx("CLI did not return JSON for status (non-blocking)")


class ClaudeCodeAdapterRemove(aetest.Testcase):
    """Test 72: adapter remove cleans up the config entry."""

    groups = ["integration"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()

    @aetest.test
    def remove_adapter(self, steps):
        with steps.start("Run mycelium adapter remove claude-code --force") as step:
            r = self.cli.run("adapter", "remove", "claude-code", "--force", timeout=15)
            if not r.ok:
                if "not registered" in (r.stdout + r.stderr).lower():
                    step.passx("Adapter was not registered (expected in some CI flows)")
                else:
                    step.failed(f"adapter remove failed: {r.error_message}")

    @aetest.test
    def adapter_not_listed(self, steps):
        with steps.start("Adapter no longer in ls output") as step:
            r = self.cli.run("adapter", "ls", timeout=15)
            if "claude-code" in r.stdout.lower():
                step.failed("claude-code still appears in adapter ls after removal")

    @aetest.test
    def reinstall_for_other_tests(self, steps):
        """Reinstall so subsequent test runs don't break status checks."""
        with steps.start("Reinstall claude-code adapter") as step:
            r = self.cli.run("adapter", "add", "claude-code", "--yes", timeout=30)
            if not r.ok:
                step.passx(f"Reinstall failed (non-blocking): {r.error_message}")


class ClaudeCodeDaemonHealth(aetest.Testcase):
    """Test 73: cc-daemon health via mycelium doctor."""

    groups = ["integration", "daemon"]

    @aetest.setup
    def setup(self, cli=None, env=None):
        self.cli = cli or MyceliumCLI()
        if env and not env.backend_reachable:
            self.skipped("Backend unreachable — daemon tests need a running backend")

    @aetest.test
    def doctor_includes_daemon(self, steps):
        with steps.start("mycelium doctor includes daemon check") as step:
            r = self.cli.doctor()
            combined = r.stdout + r.stderr
            log.info("doctor output: %s", combined[:800])
            if "daemon" not in combined.lower() and "cc-daemon" not in combined.lower():
                step.passx("Doctor output does not mention daemon (may not be installed)")


class ClaudeCodeAgentLifecycle(aetest.Testcase):
    """Test 74: Create and remove a claude_code agent handle."""

    groups = ["integration", "daemon"]

    @aetest.setup
    def setup(self, cli=None, env=None, room_name=None):
        self.cli = cli or MyceliumCLI()
        self.room_name = room_name or "e2e-integration-test"
        self.handle = "e2e-test-agent"
        if env and not env.backend_reachable:
            self.skipped("Backend unreachable — agent lifecycle tests need a running backend")

    @aetest.test
    def create_agent(self, steps):
        cwd = tempfile.mkdtemp(prefix="mycelium-e2e-agent-")
        self._agent_cwd = cwd
        with steps.start("Create a claude_code agent") as step:
            r = self.cli.run(
                "agent", "create", self.handle,
                "--adapter", "claude_code",
                "--cwd", cwd,
                "--room", self.room_name,
                timeout=30,
            )
            if not r.ok:
                step.failed(f"agent create failed: {r.error_message}")
            log.info("agent create output: %s", r.stdout[:500])

    @aetest.test
    def agent_visible(self, steps):
        with steps.start("Agent appears in agent ls") as step:
            r = self.cli.run("agent", "ls", timeout=15)
            if not r.ok:
                step.failed(f"agent ls failed: {r.error_message}")
            if self.handle not in r.stdout:
                step.failed(f"Agent {self.handle} not found in agent ls output")

    @aetest.test
    def remove_agent(self, steps):
        with steps.start("Remove the test agent") as step:
            r = self.cli.run("agent", "rm", self.handle, "--force", timeout=15)
            if not r.ok:
                step.passx(f"agent rm failed (non-blocking): {r.error_message}")

    @aetest.cleanup
    def cleanup(self):
        cwd = getattr(self, "_agent_cwd", None)
        if cwd and os.path.isdir(cwd):
            shutil.rmtree(cwd, ignore_errors=True)
        r = self.cli.run("agent", "rm", self.handle, "--force", timeout=10)


class CursorAdapterPlanned(aetest.Testcase):
    """Test 75: Cursor adapter reports 'planned but not yet implemented'."""

    groups = ["integration", "cursor"]

    @aetest.setup
    def setup(self, cli=None):
        self.cli = cli or MyceliumCLI()

    @aetest.test
    def cursor_not_implemented(self, steps):
        with steps.start("mycelium adapter add cursor exits with 'not implemented'") as step:
            r = self.cli.run("adapter", "add", "cursor", timeout=15)
            combined = (r.stdout + r.stderr).lower()
            if r.ok:
                step.passx("cursor adapter is now implemented — update tests!")
            if "planned" not in combined and "not yet implemented" not in combined:
                step.failed(f"Unexpected output for cursor adapter: {combined[:300]}")
            log.info("Cursor adapter correctly reports: not yet implemented")

    @aetest.test
    def cursor_not_in_ls(self, steps):
        with steps.start("Cursor does not appear as registered adapter") as step:
            r = self.cli.run("adapter", "ls", timeout=15)
            if "cursor" in r.stdout.lower().split():
                step.failed("Cursor appears as a registered adapter but should not be")
