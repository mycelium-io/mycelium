"""
Sanity suite — quick smoke test covering core functionality only.

Runs: environment probe, room lifecycle, memory CRUD, search, doctor.
Does NOT run: LLM-dependent, convergence, distributed, or slow tests.

Run standalone:
    python suites/sanity_suite.py --datafile data/local_datafile.yaml

Run via job:
    pyats run job jobs/sanity_job.py
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
    DoctorClean,
    SharedMemoryCliE2E,
    Reindex,
)
from testcases.integration_tests import (
    ClaudeCodeSkillInstall,
    ClaudeCodeAdapterStatus,
    CursorAdapterPlanned,
)


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

class test_06c_doctor_clean(DoctorClean):
    pass

class test_11_shared_memory_cli_e2e(SharedMemoryCliE2E):
    pass

class test_22_reindex(Reindex):
    pass

class test_70_claude_code_skill_install(ClaudeCodeSkillInstall):
    pass

class test_71_claude_code_adapter_status(ClaudeCodeAdapterStatus):
    pass

class test_75_cursor_adapter_planned(CursorAdapterPlanned):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass


if __name__ == "__main__":
    aetest.main(datafile=os.path.join(_ROOT, "data", "local_datafile.yaml"))
