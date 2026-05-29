"""
Weekly full E2E suite — runs ALL test tiers in sequence.

This is the primary suite for the weekly long-running integration test.
Includes: core, CFN, Matrix, convergence, local-real, distributed, openclaw,
and cross-channel tests.

Run standalone:
    python suites/weekly_full_suite.py --datafile data/lab_datafile.yaml

Run via job:
    pyats run job jobs/weekly_e2e_job.py --datafile data/lab_datafile.yaml
"""

import os
import sys

from pyats import aetest

# Ensure project root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.core_tests import (
    RoomLifecycle,
    MultiAgentMemory,
    MemoryReads,
    SemanticSearch,
    Synthesis,
    ConsensusNegotiation,
    SessionJoinIdempotency,
    DoctorClean,
    CfnLlmCounters,
    SharedMemoryCliE2E,
    ConsensusCliE2E,
    SyncNegotiationCliE2E,
    DemoScriptNegotiation,
    Reindex,
)
from testcases.matrix_tests import MatrixCommunication
from testcases.cfn_tests import IocCfn, IocFullPath, IocNegotiationPath
from testcases.convergence_tests import (
    ThreeAgentNegotiation,
    ArchitectureDecision,
    ResourceAllocation,
    AsymmetricStakes,
    PreexistingContext,
    FeaturePrioritization,
    ConsensusStability,
)
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
from testcases.openclaw_tests import OpenClawMyceliumSkill, OpenClawAgentExecution
from testcases.cross_channel_tests import CrossChannelMemoryIsolation
from testcases.integration_tests import (
    ClaudeCodeSkillInstall,
    ClaudeCodeAdapterStatus,
    ClaudeCodeAdapterRemove,
    ClaudeCodeDaemonHealth,
    ClaudeCodeAgentLifecycle,
    CursorAdapterPlanned,
)


# ── Thin declarations — inherit all logic from testcase modules ───────────

class CommonSetup(MyceliumCommonSetup):
    pass


# Core (01-06, 06b-d, 11-14, 22)
class test_01_room_lifecycle(RoomLifecycle):
    pass

class test_02_multi_agent_memory(MultiAgentMemory):
    pass

class test_03_memory_reads(MemoryReads):
    pass

class test_04_semantic_search(SemanticSearch):
    pass

class test_05_synthesis(Synthesis):
    pass

class test_06_consensus_negotiation(ConsensusNegotiation):
    pass

class test_06b_session_join_idempotency(SessionJoinIdempotency):
    pass

class test_06c_doctor_clean(DoctorClean):
    pass

class test_06d_cfn_llm_counters(CfnLlmCounters):
    pass

# Matrix (07)
class test_07_matrix_communication(MatrixCommunication):
    pass

# CFN (08-10)
class test_08_ioc_cfn(IocCfn):
    pass

class test_09_ioc_full_path(IocFullPath):
    pass

class test_10_ioc_negotiation_path(IocNegotiationPath):
    pass

# Core continued (11-14, 22)
class test_11_shared_memory_cli_e2e(SharedMemoryCliE2E):
    pass

class test_12_consensus_cli_e2e(ConsensusCliE2E):
    pass

class test_13_sync_negotiation_cli_e2e(SyncNegotiationCliE2E):
    pass

class test_14_demo_script_negotiation(DemoScriptNegotiation):
    pass

# Convergence (15-21)
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

class test_22_reindex(Reindex):
    pass

# Local-real (30-32)
class test_30_local_two_agent(LocalTwoAgentNegotiation):
    pass

class test_31_local_three_agent(LocalThreeAgentNegotiation):
    pass

class test_32_local_architecture(LocalArchitectureDecision):
    pass

# Distributed (40-49)
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

# OpenClaw (50-51)
class test_50_openclaw_mycelium_skill(OpenClawMyceliumSkill):
    pass

class test_51_openclaw_agent_execution(OpenClawAgentExecution):
    pass

# Cross-channel (60)
class test_60_cross_channel_memory_isolation(CrossChannelMemoryIsolation):
    pass

# Integration adapters (70-75)
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


class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "base_datafile.yaml"))
