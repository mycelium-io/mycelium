"""CFN / IOC integration tests.

Maps to original tests 08, 09, 10.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.cfn_api import CfnMgmtAPI, CfnNodeSvcAPI
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


class IocCfn(aetest.Testcase):
    """Test 08: Knowledge graph ingest/query via backend CFN API."""

    groups = ["cfn"]

    @aetest.setup
    def check_cfn(self, env):
        if env.skip_cfn_tests:
            self.skipped("CFN management plane not reachable")

    @aetest.test
    def knowledge_ingest_and_query(self, steps, api, room_name, mas_id=None):
        marker = f"e2e-test-{uuid.uuid4().hex[:8]}"

        with steps.start("Ingest knowledge") as step:
            st, resp = api.ingest_knowledge({
                "room_name": room_name,
                "agent_id": "e2e-test-agent",
                "records": [
                    {"response": f"E2E knowledge {marker}: The capital of France is Paris."}
                ],
            })
            if st not in (200, 201, 202):
                log.error("Knowledge ingest body: %s", resp)
                step.failed(f"Knowledge ingest returned status={st}: {resp}")

        with steps.start("Query knowledge") as step:
            time.sleep(3)
            st, resp = api.query_knowledge(
                "What is the capital of France?", mas_id=mas_id,
            )
            if st != 200:
                step.failed(f"Knowledge query returned status={st}: {resp}")
            log.info("Knowledge query response: %s", resp)

        with steps.start("List knowledge") as step:
            st, resp = api.list_knowledge()
            if st != 200:
                step.failed(f"Knowledge list returned status={st}: {resp}")


class IocFullPath(aetest.Testcase):
    """Test 09: CFN mgmt plane full path — workspaces, MAS, memory provider."""

    groups = ["cfn"]

    @aetest.setup
    def check_cfn(self, env):
        if env.skip_cfn_tests:
            self.skipped("CFN management plane not reachable")

    @aetest.test
    def verify_workspaces(self, steps, cfn_mgmt, env):
        with steps.start("List workspaces") as step:
            st, data = cfn_mgmt.list_workspaces()
            if st != 200:
                step.failed(f"Workspaces returned status={st}")
            workspace_id = env.cfn_primary_workspace_id
            if not workspace_id:
                step.failed("No primary workspace found")

        with steps.start("List memory providers") as step:
            st, data = cfn_mgmt.list_memory_providers()
            if st != 200:
                step.failed(f"Memory providers returned status={st}")

        with steps.start("List MAS for primary workspace") as step:
            st, data = cfn_mgmt.list_mas(env.cfn_primary_workspace_id)
            if st != 200:
                step.failed(f"MAS list returned status={st}")

        with steps.start("List CFN nodes") as step:
            st, data = cfn_mgmt.list_cfn_nodes()
            if st != 200:
                step.failed(f"CFN nodes returned status={st}")


class IocNegotiationPath(aetest.Testcase):
    """Test 10: Full CFN semantic negotiation via node-svc."""

    groups = ["cfn", "llm", "slow"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_cfn_tests:
            self.skipped("CFN not reachable")
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def full_cfn_negotiation(self, steps, api, cfn_node_svc, env, room_name, timeouts=None):
        t = timeouts or {}
        timeout = t.get("negotiation_wait", 600)
        test_room = f"{room_name}-cfn-neg"

        with steps.start("Create room and spawn session") as step:
            st, _ = api.create_room(test_room, description="CFN negotiation path test")
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")
            st, _ = api.spawn_session(test_room, {
                "handle": "cfn-agent-a",
                "position": "Prefer microservices architecture",
            })
            if st not in (200, 201):
                step.failed(f"Session spawn failed: status={st}")

        with steps.start("Wait for negotiation outcome") as step:
            result = api.wait_for_consensus(test_room, timeout=timeout)
            state = result.get("coordination_state") if isinstance(result, dict) else None
            log.info("CFN negotiation path: state=%s", state)

    @aetest.cleanup
    def cleanup(self, api, room_name):
        api.delete_room(f"{room_name}-cfn-neg")
