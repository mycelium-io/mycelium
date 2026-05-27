"""
Convergence suite — multi-agent simulated negotiation scenarios.

Covers tests 15-21.
"""

import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.convergence_tests import (
    ThreeAgentNegotiation,
    ArchitectureDecision,
    ResourceAllocation,
    AsymmetricStakes,
    PreexistingContext,
    FeaturePrioritization,
    ConsensusStability,
)


class CommonSetup(MyceliumCommonSetup):
    pass

class test_15_three_agent_negotiation(ThreeAgentNegotiation):
    pass

class test_16_architecture_decision(ArchitectureDecision):
    pass

class test_17_resource_allocation(ResourceAllocation):
    pass

class test_18_asymmetric_stakes(AsymmetricStakes):
    pass

class test_19_preexisting_context(PreexistingContext):
    pass

class test_20_feature_prioritization(FeaturePrioritization):
    pass

class test_21_consensus_stability(ConsensusStability):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "base_datafile.yaml"))
