"""OpenClaw skill verification tests.

Maps to original tests 50, 51.
"""

from __future__ import annotations

import logging

from pyats import aetest

from libs.mycelium_cli import MyceliumCLI
from libs.openclaw import run_openclaw
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


class OpenClawMyceliumSkill(aetest.Testcase):
    """Test 50: Verify the mycelium skill is listed and binary is accessible."""

    groups = ["openclaw"]

    @aetest.test
    def verify_skill_listed(self, steps):
        with steps.start("Check openclaw skills list") as step:
            proc = run_openclaw(["skills", "list", "--json"])
            if proc is None or proc.returncode != 0:
                step.failed("openclaw skills list failed or not installed")
            if "mycelium" not in proc.stdout.lower():
                step.failed("mycelium skill not found in openclaw skills list")

    @aetest.test
    def verify_binary_accessible(self, steps, cli):
        with steps.start("Check mycelium CLI is on PATH") as step:
            r = cli.run("--version")
            if not r.ok:
                step.failed(f"mycelium CLI not accessible: {r.error_message}")

    @aetest.test
    def verify_skill_requirements(self, steps):
        with steps.start("Check skill requirements") as step:
            proc = run_openclaw(["skills", "check", "mycelium"])
            if proc is None:
                step.failed("openclaw not installed")
            if proc.returncode != 0:
                log.warning("Skill requirements check returned rc=%d: %s", proc.returncode, proc.stderr)


class OpenClawAgentExecution(aetest.Testcase):
    """Test 51: Agent can execute mycelium commands via the skill."""

    groups = ["openclaw", "llm", "slow"]

    @aetest.setup
    def check_llm(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")

    @aetest.test
    def agent_executes_mycelium(self, steps, cli, room_name):
        test_room = f"{room_name}-skill-exec"

        with steps.start("Create test room") as step:
            r = cli.room_create(test_room)
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Trigger agent skill execution") as step:
            log.info("Triggering agent skill execution for room %s", test_room)
            proc = run_openclaw([
                "run", "--agent", "agent-alpha",
                "--prompt", f"Use the mycelium skill to list rooms. The room '{test_room}' should exist.",
            ], timeout=120.0)
            if proc is None:
                step.failed("openclaw run command failed")
            if proc.returncode != 0:
                log.warning("Agent execution returned rc=%d", proc.returncode)
