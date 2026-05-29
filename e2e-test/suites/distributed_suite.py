"""
Distributed suite — real agents on oclw3/4/5 via Matrix + Mycelium.

Covers tests 30-32 (local-real) and 40-49 (cross-device).
"""

import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.distributed_tests import (
    LocalTwoAgentNegotiation,
    LocalThreeAgentNegotiation,
    LocalArchitectureDecision,
    DistributedTwoAgent,
    DistributedThreeAgent,
    DistributedArchitecture,
    DistributedResourceAllocation,
    DistributedAsymmetricStakes,
    DistributedPreexistingContext,
    DistributedFeaturePrioritization,
    DistributedCrossDeviceOnly,
    DistributedBackendResolvedCfnIds,
    SkillCrossChannelReturnTrip,
)


class CommonSetup(MyceliumCommonSetup):
    pass

class test_30_local_two_agent(LocalTwoAgentNegotiation):
    pass

class test_31_local_three_agent(LocalThreeAgentNegotiation):
    pass

class test_32_local_architecture(LocalArchitectureDecision):
    pass

class test_40_distributed_two_agent(DistributedTwoAgent):
    pass

class test_41_distributed_three_agent(DistributedThreeAgent):
    pass

class test_42_distributed_architecture(DistributedArchitecture):
    pass

class test_43_distributed_resource_allocation(DistributedResourceAllocation):
    pass

class test_44_distributed_asymmetric_stakes(DistributedAsymmetricStakes):
    pass

class test_45_distributed_preexisting_context(DistributedPreexistingContext):
    pass

class test_46_distributed_feature_prioritization(DistributedFeaturePrioritization):
    pass

class test_47_distributed_cross_device_only(DistributedCrossDeviceOnly):
    pass

class test_48_backend_resolved_cfn_ids(DistributedBackendResolvedCfnIds):
    pass

class test_49_skill_cross_channel_return_trip(SkillCrossChannelReturnTrip):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "lab_datafile.yaml"))
