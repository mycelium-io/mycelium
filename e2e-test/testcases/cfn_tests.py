"""CFN / IOC integration tests.

Maps to original tests 08, 09, 10.

Key design lessons from early IOC/CFN E2E runs:
- CFN node-svc is single-worker uvicorn → use 180s timeouts to absorb
  queueing behind concurrent negotiations.
- Leaf nodes only send room_name; backend resolves workspace/mas IDs.
- /cfn/knowledge/query has no room_name param today, so we extract the
  resolved mas_id from the ingest response's cfn_message (the graph name
  contains it: "graph_<mas-id-with-underscores>").
- Query with a semantic intent ("Find information about weather conditions"),
  not a random marker — CFN uses semantic search.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from pyats import aetest

from libs.mycelium_cli import CLIResult

log = logging.getLogger(__name__)


def _parse_session_room(result: CLIResult) -> str | None:
    """Extract session_room from ``mycelium --json session create`` output."""
    data = result.json
    if isinstance(data, dict):
        return data.get("session_room") or data.get("display_name")
    return None


_INGEST_TIMEOUT = 180
_QUERY_TIMEOUT = 180


def _extract_mas_id_from_response(resp: dict | None) -> str | None:
    """Extract mas_id from a successful ingest response's cfn_message.

    CFN returns something like:
      "Successfully saved 3 nodes ... to graph 'graph_806811e1_7300_...'"
    We parse the UUID out and convert underscores back to hyphens.
    """
    if not isinstance(resp, dict):
        return None
    cfn_msg = resp.get("cfn_message", "")
    match = re.search(r"graph_([a-f0-9_]+)", cfn_msg)
    if match:
        return match.group(1).replace("_", "-")
    return None


def _check_cfn_message(resp: dict | None) -> str | None:
    """Return an error string if cfn_message signals failure, else None."""
    if not isinstance(resp, dict):
        return None
    cfn_msg = resp.get("cfn_message", "")
    if cfn_msg and ("error" in cfn_msg.lower() or "fail" in cfn_msg.lower()):
        return f"CFN error: {cfn_msg}"
    return None


class IocCfn(aetest.Testcase):
    """Test 08: Knowledge graph ingest/query via backend CFN API.

    Ported from bundle.py test_ioc_cfn — exercises the leaf-node contract
    where clients only supply room_name and the backend resolves IDs.
    """

    groups = ["cfn"]

    @aetest.setup
    def check_cfn(self, env):
        if env.skip_cfn_tests:
            self.skipped("CFN management plane not reachable")

    @aetest.test
    def knowledge_ingest_and_query(self, steps, api, room_name, cfn_node_svc, env, mas_id=None):
        marker = f"e2e-test-{uuid.uuid4().hex[:8]}"
        resolved_mas_id = None

        with steps.start("Ingest knowledge (room_name only)") as step:
            st, resp = api.ingest_knowledge(
                {
                    "room_name": room_name,
                    "agent_id": "e2e-test-agent",
                    "records": [
                        {"response": f"E2E test knowledge marker: {marker}. The weather is sunny in the city."}
                    ],
                },
                timeout=_INGEST_TIMEOUT,
            )
            if st not in (200, 201, 202):
                log.error("Knowledge ingest body: %s", resp)
                step.failed(f"Knowledge ingest returned status={st}: {resp}")

            cfn_err = _check_cfn_message(resp)
            if cfn_err:
                step.failed(cfn_err)

            resolved_mas_id = _extract_mas_id_from_response(resp)
            if resolved_mas_id:
                log.info("Resolved mas_id from ingest response: %s", resolved_mas_id)

        with steps.start("Ingest knowledge (alt room)") as step:
            alt_room = f"{marker}-alt"
            st, _ = api.create_room(alt_room, description="alt-room for per-room MAS test")
            if st not in (200, 201):
                step.failed(f"Alt room creation failed: status={st}")
            st, resp = api.ingest_knowledge(
                {
                    "room_name": alt_room,
                    "agent_id": "e2e-test-agent-alt",
                    "records": [{"response": f"E2E alt-room test: {marker}. Temperature is warm today."}],
                },
                timeout=_INGEST_TIMEOUT,
            )
            if st not in (200, 201, 202):
                log.error("Alt-room ingest body: %s", resp)
                step.failed(f"Alt-room ingest returned status={st}: {resp}")
            cfn_err = _check_cfn_message(resp)
            if cfn_err:
                step.failed(cfn_err)

        with steps.start("Query knowledge") as step:
            query_mas = resolved_mas_id or mas_id
            st, resp = api.query_knowledge(
                "Find information about weather conditions",
                mas_id=query_mas,
                timeout=_QUERY_TIMEOUT,
            )
            if st != 200:
                step.failed(f"Knowledge query returned status={st}: {resp}")
            log.info("Knowledge query response: %s", resp)

        with steps.start("Fetch knowledge graph") as step:
            # The old /cfn/knowledge/list endpoint was removed in 2.0.0.
            # Use the Go CFN's knowledge-graph endpoint instead.
            ws_id = env.cfn_primary_workspace_id
            graph_mas = resolved_mas_id or mas_id
            if cfn_node_svc is None or not ws_id:
                step.skipped("cfn_node_svc or workspace_id not available")
            st, resp = cfn_node_svc.get_knowledge_graph(ws_id, graph_mas)
            if st == 404:
                # Graph not yet built (no distillation run) — acceptable.
                log.info("Knowledge graph not yet built for MAS %s (404) — ingest+query verified", graph_mas)
            elif st == 200:
                nodes = resp.get("nodes") or resp.get("data", {}).get("nodes", []) if isinstance(resp, dict) else []
                log.info("Knowledge graph: %d node(s) for MAS %s", len(nodes), graph_mas)
            else:
                step.failed(f"Knowledge graph returned status={st}: {resp}")

    @aetest.cleanup
    def cleanup_alt_room(self, api, room_name):
        """Remove the alt room created during the test."""
        st, data = api.list_rooms()
        if st != 200:
            return
        rooms = data if isinstance(data, list) else data.get("rooms", []) if isinstance(data, dict) else []
        for room in rooms:
            name = room.get("name", "")
            if name.endswith("-alt") and name.startswith("e2e-test-"):
                api.delete_room(name)


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
    """Test 10: Full CFN semantic negotiation path.

    Aligned with bundle.py ``test_sync_negotiation_cli_e2e``:
    two agents join, wait for coordination_tick on the session sub-room,
    then drive negotiate respond accept, and poll for coordination_consensus.
    """

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
    def full_cfn_negotiation(self, steps, api, cli, cfn_node_svc, env, room_name):
        test_room = f"{room_name}-cfn-neg"

        with steps.start("Create room, session, and join two agents") as step:
            st, _ = api.create_room(test_room, description="CFN negotiation path test")
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")
            r = cli.session_create(test_room)
            if not r.ok:
                step.failed(f"session create failed: {r.error_message}")
            session_room = _parse_session_room(r)
            r = cli.session_join(
                test_room,
                "agent-alpha",
                position="Microservices primary; independent deploy cycles; hard limit: no shared database between services",
            )
            if not r.ok:
                step.failed(f"agent-alpha join failed: {r.error_message}")
            r = cli.session_join(
                test_room,
                "agent-beta",
                position="Monolith primary; single deploy artifact; hard limit: sub-100ms internal latency",
            )
            if not r.ok:
                step.failed(f"agent-beta join failed: {r.error_message}")

        with steps.start("Resolve session room") as step:
            if not session_room:
                for _ in range(20):
                    session_room = api.find_session_room(test_room)
                    if session_room:
                        break
                    time.sleep(0.5)
            if not session_room:
                step.failed("Could not find session child room")
            log.info("Session room: %s", session_room)

        with steps.start("Wait for coordination_tick (240s)") as step:
            tick_seen = False
            for _ in range(48):
                _, msgs = api.get_room_messages(session_room)
                if any(m.get("message_type") == "coordination_tick" for m in msgs):
                    tick_seen = True
                    break
                time.sleep(5)
            if not tick_seen:
                step.failed("No coordination_tick within 240s — check backend/CFN/LLM logs")

        with steps.start("Agents accept negotiation") as step:
            r = cli.negotiate_respond(session_room, "agent-alpha", "accept")
            if not r.ok:
                log.warning("agent-alpha accept: %s", r.error_message)
            time.sleep(2)
            r = cli.negotiate_respond(session_room, "agent-beta", "accept")
            if not r.ok:
                log.warning("agent-beta accept: %s", r.error_message)

        with steps.start("Wait for coordination_consensus (240s)") as step:
            consensus_seen = False
            for _ in range(48):
                _, msgs = api.get_room_messages(session_room)
                for m in msgs:
                    if m.get("message_type") == "coordination_consensus":
                        consensus_seen = True
                        break
                if consensus_seen:
                    break
                time.sleep(5)
            if not consensus_seen:
                step.failed("No coordination_consensus within 240s after accepts")
            log.info("CFN negotiation path: consensus reached in %s", session_room)

    @aetest.cleanup
    def cleanup(self, api, room_name):
        api.delete_room(f"{room_name}-cfn-neg")
