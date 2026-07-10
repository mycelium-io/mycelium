"""
Integration adapter suite — Cursor single-host tests (75-77).

Tests 75-77 run on any all-in-one host with the mycelium stack running.
Tests 78-80 require spoke agents on separate devices and live in the
hub_and_spoke suite instead.

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
    CursorWorkspaceDrift,
)


class CommonSetup(aetest.CommonSetup):
    """Lightweight setup for integration adapter tests — no room creation needed."""

    @aetest.subsection
    def check_cli(self):
        import shutil

        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")


class test_75_cursor_basic_dispatch(CursorBasicDispatch):
    pass


class test_76_cursor_workspace_drift(CursorWorkspaceDrift):
    pass


class test_77_cursor_auth_failure(CursorAuthFailure):
    pass


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def done(self):
        pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "integration_datafile.yaml"))
