"""Targeted suite for pyATS gap-fix verification (010, 013)."""

import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.cfn_tests import IocNegotiationPath
from testcases.common_setup_cleanup import MyceliumCommonCleanup, MyceliumCommonSetup
from testcases.core_tests import SyncNegotiationCliE2E


class CommonSetup(MyceliumCommonSetup):
    pass


class test_10_ioc_negotiation_path(IocNegotiationPath):
    pass


class test_13_sync_negotiation_cli_e2e(SyncNegotiationCliE2E):
    pass


class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "lab_datafile.yaml"))
