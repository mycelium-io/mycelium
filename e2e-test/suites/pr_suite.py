"""PR suite — Tier A: stack health, memory, protocol. No LLM."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pyats import aetest

from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.tier_a_stack import BackendHealth as _BackendHealth
from testcases.tier_a_stack import RoomLifecycle as _RoomLifecycle
from testcases.tier_a_stack import CLIBasics as _CLIBasics
from testcases.tier_a_memory import MemoryCRUD as _MemoryCRUD
from testcases.tier_a_memory import BriefingContract as _BriefingContract
from testcases.tier_a_memory import MemorySearch as _MemorySearch
from testcases.tier_a_protocol import SessionAPIShape as _SessionAPIShape
from testcases.tier_a_protocol import RespondWithoutAwait as _RespondWithoutAwait
from testcases.tier_a_protocol import RoomDeleteIdempotent as _RoomDeleteIdempotent
from testcases.tier_a_protocol import AgentContextEndpointShape as _AgentContextEndpointShape


class CommonSetup(MyceliumCommonSetup):
    pass


# Tier A — Stack health
class BackendHealth(_BackendHealth):
    pass


class RoomLifecycle(_RoomLifecycle):
    pass


class CLIBasics(_CLIBasics):
    pass


# Tier A — Memory
class MemoryCRUD(_MemoryCRUD):
    pass


class BriefingContract(_BriefingContract):
    pass


class MemorySearch(_MemorySearch):
    pass


# Tier A — Protocol
class SessionAPIShape(_SessionAPIShape):
    pass


class RespondWithoutAwait(_RespondWithoutAwait):
    pass


class RoomDeleteIdempotent(_RoomDeleteIdempotent):
    pass


class AgentContextEndpointShape(_AgentContextEndpointShape):
    pass


class CommonCleanup(MyceliumCommonCleanup):
    pass
