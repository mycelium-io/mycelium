"""
Cursor adapter suite — dispatch, drift, auth, multi-host, cross-family negotiation.

Covers tests 75-80.

Run standalone:
    python suites/cursor_suite.py --datafile data/base_datafile.yaml
"""

import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.cursor_tests import (
    CursorBasicDispatch,
    CursorWorkspaceDrift,
    CursorAuthFailure,
    CursorMultiHostDispatch,
    CursorCrossFamilyCursor,
    CursorCrossFamilyOpenClaw,
)


class CommonSetup(MyceliumCommonSetup):
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

class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "base_datafile.yaml"))
