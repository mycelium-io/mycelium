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

from testcases.cursor_tests import (
    CursorAuthFailure,
    CursorBasicDispatch,
    CursorCrossFamilyCursor,
    CursorCrossFamilyOpenClaw,
    CursorMultiHostDispatch,
    CursorWorkspaceDrift,
)
from testcases.integration_tests import (
    ClaudeCodeAdapterRemove,
    ClaudeCodeAdapterStatus,
    ClaudeCodeAgentLifecycle,
    ClaudeCodeDaemonHealth,
    ClaudeCodeSkillInstall,
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


class test_75_cursor_basic_dispatch(CursorBasicDispatch):
    pass


class test_76_cursor_workspace_drift(CursorWorkspaceDrift):
    pass


class test_77_cursor_auth_failure(CursorAuthFailure):
    pass


class test_78_cursor_multi_host_dispatch(CursorMultiHostDispatch):
    pass


class test_79_cursor_cross_family_cursor(CursorCrossFamilyCursor):
    pass


class test_80_cursor_cross_family_openclaw(CursorCrossFamilyOpenClaw):
    pass


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def done(self):
        pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "integration_datafile.yaml"))
