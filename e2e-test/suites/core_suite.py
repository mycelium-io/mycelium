"""
Core suite — rooms, memory, CLI, sessions, search, synthesis, CFN basics.

Covers tests 01-14 and 22.

Run standalone:
    python suites/core_suite.py --datafile data/base_datafile.yaml
"""

import os
import sys

from pyats import aetest

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


class CommonSetup(MyceliumCommonSetup):
    pass

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

class test_07_matrix_communication(MatrixCommunication):
    pass

class test_08_ioc_cfn(IocCfn):
    pass

class test_09_ioc_full_path(IocFullPath):
    pass

class test_10_ioc_negotiation_path(IocNegotiationPath):
    pass

class test_11_shared_memory_cli_e2e(SharedMemoryCliE2E):
    pass

class test_12_consensus_cli_e2e(ConsensusCliE2E):
    pass

class test_13_sync_negotiation_cli_e2e(SyncNegotiationCliE2E):
    pass

class test_14_demo_script_negotiation(DemoScriptNegotiation):
    pass

class test_22_reindex(Reindex):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "base_datafile.yaml"))
