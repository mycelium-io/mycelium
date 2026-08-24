"""Canary suite — Tier C: live agent multi-episode. Informational only."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pyats import aetest

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.tier_c_live_episode import EpisodeOne as _EpisodeOne
from testcases.tier_c_live_episode import EpisodeTwo as _EpisodeTwo


class CommonSetup(MyceliumCommonSetup):
    pass


class EpisodeOne(_EpisodeOne):
    pass


class EpisodeTwo(_EpisodeTwo):
    pass


class CommonCleanup(MyceliumCommonCleanup):
    pass
