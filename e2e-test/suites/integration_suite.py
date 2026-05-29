"""
Integration adapter suite — Claude Code skill/daemon + Cursor stubs.

Tests 70-75: adapter install, status, remove, daemon health, agent lifecycle.
The skill-install tests (70-72, 75) are file-system-only and fast.
Daemon/agent tests (73-74) need a running backend.

Run standalone:
    python suites/integration_suite.py --datafile data/integration_datafile.yaml

Run via job:
    pyats run job jobs/integration_job.py
"""

import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.integration_tests import (
    ClaudeCodeSkillInstall,
    ClaudeCodeAdapterStatus,
    ClaudeCodeAdapterRemove,
    ClaudeCodeDaemonHealth,
    ClaudeCodeAgentLifecycle,
    CursorAdapterPlanned,
)


class CommonSetup(aetest.CommonSetup):
    """Lightweight setup for integration adapter tests — no room creation needed."""

    @aetest.subsection
    def check_cli(self):
        import shutil
        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")


class test_70_claude_code_skill_install(ClaudeCodeSkillInstall):
    pass

class test_71_claude_code_adapter_status(ClaudeCodeAdapterStatus):
    pass

class test_72_claude_code_adapter_remove(ClaudeCodeAdapterRemove):
    pass

class test_73_claude_code_daemon_health(ClaudeCodeDaemonHealth):
    pass

class test_74_claude_code_agent_lifecycle(ClaudeCodeAgentLifecycle):
    pass

class test_75_cursor_adapter_planned(CursorAdapterPlanned):
    pass


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def done(self):
        pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "integration_datafile.yaml"))
