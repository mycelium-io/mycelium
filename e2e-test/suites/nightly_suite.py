"""Nightly suite — Tier B: stub agent coordination tests. No LLM."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pyats import aetest

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.tier_b_stub_coord import TwoStubHappyPath as _TwoStubHappyPath
from testcases.tier_b_stub_coord import TwoStubRejectionPath as _TwoStubRejectionPath
from testcases.tier_b_stub_coord import CounterOfferChain as _CounterOfferChain
from testcases.tier_b_stub_coord import RespondWithoutTurnRejected as _RespondWithoutTurnRejected
from testcases.tier_b_stub_coord import CrossEpisodeMemory as _CrossEpisodeMemory
from testcases.tier_b_stub_coord import MultiSessionResponseRate as _MultiSessionResponseRate


class CommonSetup(MyceliumCommonSetup):
    pass


class TwoStubHappyPath(_TwoStubHappyPath):
    pass


class TwoStubRejectionPath(_TwoStubRejectionPath):
    pass


class CounterOfferChain(_CounterOfferChain):
    pass


class RespondWithoutTurnRejected(_RespondWithoutTurnRejected):
    pass


class CrossEpisodeMemory(_CrossEpisodeMemory):
    pass


class MultiSessionResponseRate(_MultiSessionResponseRate):
    pass


class CommonCleanup(MyceliumCommonCleanup):
    pass
