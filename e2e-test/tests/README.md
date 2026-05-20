# Mycelium E2E Test Suite

End-to-end integration tests for Mycelium, covering the full stack from CLI commands through the backend, IOC/CFN coordination, and Matrix-based multi-agent communication.

## Running Tests

```bash
# Run all tests
cd /home/ubuntu/tests
uv run pytest test_mycelium_e2e.py -v

# Run specific test levels
uv run pytest -m "not slow"           # Fast tests only
uv run pytest -m "not llm"            # Skip LLM-dependent tests
uv run pytest -m convergence          # Multi-agent convergence tests
uv run pytest -m matrix_e2e           # Matrix E2E tests (local agents)
uv run pytest -m distributed          # Distributed tests (oclw3/4/5)

# Run a specific test
uv run pytest test_mycelium_e2e.py::test_15_three_agent_negotiation -v
```

## Test Levels

Tests operate at different integration levels:

| Level | Description | Example |
|-------|-------------|---------|
| **CLI** | Uses `mycelium` CLI commands | `mycelium room create`, `mycelium memory store` |
| **HTTP API** | Direct HTTP calls to Mycelium backend | `curl http://localhost:8000/rooms` |
| **IOC/CFN API** | HTTP calls to CFN management/service planes | Workspace, MAS, negotiation APIs |
| **Matrix API** | HTTP calls to Synapse homeserver | Room resolution, message sending |
| **Matrix E2E** | Full flow via OpenClaw agents on local machine | Agent receives Matrix message → Mycelium hooks → coordination |
| **Distributed** | Full flow with agents on separate machines | oclw3, oclw4, oclw5 coordination |

---

## Test Cases

### Section 0: Environment Detection

| Test | Level | Description |
|------|-------|-------------|
| `test_00_environment_detected` | HTTP API | Probes backend, CFN, and Matrix availability. Sets context flags for conditional test execution. |

### Section 1-5: Core Memory & Synthesis

| Test | Level | Description |
|------|-------|-------------|
| `test_01_room_lifecycle` | CLI | Creates, uses, and lists rooms via `mycelium room` commands. |
| `test_02_multi_agent_memory` | CLI | Four agents store memories across categories (decisions, status, work, context). Verifies cross-agent visibility. |
| `test_03_memory_reads` | CLI | Gets single memories, lists all, filters by handle/category using `mycelium memory` commands. |
| `test_04_semantic_search` | CLI | Semantic search for "database decisions" and "what failed" using embeddings. |
| `test_05_synthesis` | CLI + LLM | Generates AI synthesis of room state via `mycelium synthesize`. Requires LLM. |

### Section 6-7: Negotiation & Matrix

| Test | Level | Description |
|------|-------|-------------|
| `test_06_consensus_negotiation` | CLI | Two agents with differing requirements join session, state positions, verify session tracking. |
| `test_06b_session_join_idempotency` | CLI | Regression: mycelium PR #286 — duplicate `session join` calls are idempotent (no phantom participant rows, fixes #280 / #284). |
| `test_06c_doctor_clean` | CLI | Runs `mycelium --json doctor` and asserts no `error`-level checks (catches drift in `.env`/`config.toml` alignment and migration state). |
| `test_06d_cfn_llm_counters` | CLI + IOC | Regression: `ioc-cognition-fabric-node-svc` ≥ 0.1.5 emits per-call token usage via the litellm success callback and the `cfn_llm.by_pipeline.*` / `cfn_llm.by_room.*` counter dimensions populate end-to-end. |
| `test_07_matrix_communication` | Matrix API | Resolves `#agents:local` room, sends/receives messages via Matrix, tests agent-to-agent communication. |

### Section 8-10: IOC/CFN Integration

| Test | Level | Description |
|------|-------|-------------|
| `test_08_ioc_cfn` | HTTP API | Tests knowledge graph store/query via CFN-compatible API (`/shared-memories`). |
| `test_09_ioc_full_path` | IOC/CFN API | Verifies CFN management plane registration, workspace assignment, MAS existence. |
| `test_10_ioc_negotiation_path` | IOC/CFN API + LLM | Full CFN negotiation: node-svc registration → LLM options generation → coordination_tick fanout. |

### Section 11-14: CLI E2E Workflows

| Test | Level | Description |
|------|-------|-------------|
| `test_11_shared_memory_cli_e2e` | CLI | Agent stores decision → another agent reads it → semantic search finds it → persists after reindex. |
| `test_12_consensus_cli_e2e` | CLI | Two agents join room with positions → session tracks both → catchup shows negotiation state. |
| `test_13_sync_negotiation_cli_e2e` | CLI + IOC | Creates room via IOC path → session → polls for `coordination_tick` → agents respond accept → consensus reached. |
| `test_14_demo_script_negotiation` | CLI + IOC | Follows `docs/demo-script.md`: `mycelium watch` → `session await` → `message respond` → substantive consensus. |

### Section 15-21: Convergence Scenarios (Simulated)

These tests simulate multi-agent negotiations using CLI commands (no actual OpenClaw agents). They verify the coordination engine handles various negotiation patterns.

| Test | Level | Scenario |
|------|-------|----------|
| `test_15_three_agent_negotiation` | CLI + IOC | **Release planning**: speed vs quality vs cost priorities. Tests 3-way negotiation. |
| `test_16_architecture_decision` | CLI + IOC | **Database selection**: PostgreSQL vs MongoDB advocacy. Technical trade-offs. |
| `test_17_resource_allocation` | CLI + IOC | **Sprint capacity**: features vs bug fixes allocation. Multi-issue negotiation. |
| `test_18_asymmetric_stakes` | CLI + IOC | **Deployment timing**: hard deadline vs flexible. Tests preference intensity. |
| `test_19_preexisting_context` | CLI + IOC | **Feature planning**: negotiation with prior architectural decisions in memory. |
| `test_20_feature_prioritization` | CLI + IOC | **Quarterly roadmap**: sales vs engineering priorities. Logrolling potential. |
| `test_21_consensus_stability` | CLI + IOC | **Persistence check**: consensus persists, new agents can see it via catchup. |

### Section 22-23: Maintenance

| Test | Level | Description |
|------|-------|-------------|
| `test_22_reindex` | CLI | Re-indexes room memories via `mycelium memory reindex`. |

### Section 30-32: Matrix E2E (Local Agents)

True end-to-end tests using OpenClaw agents running on the local machine (oclw4). Test observer sends trigger messages to `#agents:local`, agents respond and coordinate through Mycelium.

| Test | Level | Description |
|------|-------|-------------|
| `test_30_matrix_two_agent_negotiation` | Matrix E2E | Two local agents negotiate sprint planning via Matrix + Mycelium hooks. |
| `test_31_matrix_three_agent_negotiation` | Matrix E2E | Three local agents negotiate release planning. |
| `test_32_matrix_architecture_decision` | Matrix E2E | Technical architecture decision with local agents. |

### Section 40-49: Distributed E2E (Multi-Machine)

True distributed tests with OpenClaw agents on separate physical machines:
- **oclw4** (10.0.50.125): `agent-alpha` - local machine, runs IOC backend
- **oclw3** (10.0.50.171): `claire-agent` - remote machine
- **oclw5** (10.0.50.142): `oclw5-agent` - remote machine

| Test | Level | Agents | Description |
|------|-------|--------|-------------|
| `test_40_distributed_two_agent` | Distributed | alpha + claire | Two agents on different devices negotiate sprint capacity. |
| `test_41_distributed_three_agent` | Distributed | alpha + claire + oclw5 | Three agents across three machines negotiate release planning. |
| `test_42_distributed_architecture` | Distributed | alpha + oclw5 | Database architecture decision across devices. |
| `test_43_distributed_resource_allocation` | Distributed | alpha + claire + oclw5 | Q3 budget allocation negotiation (engineering/product/infra). |
| `test_44_distributed_asymmetric_stakes` | Distributed | alpha + claire | Language selection where one agent has critical ML pipeline dependency. |
| `test_45_distributed_preexisting_context` | Distributed | alpha + oclw5 | Mobile platform priority with reference to prior Q1 decisions. |
| `test_46_distributed_feature_prioritization` | Distributed | alpha + claire + oclw5 | Feature backlog prioritization with ranked list output. |
| `test_47_distributed_cross_device_only` | Distributed | claire + oclw5 | Only remote agents (no oclw4 agent) coordinate through central IOC backend. |
| `test_48_distributed_backend_resolved_cfn_ids` | Distributed + IOC | leaf-node ingest | Regression for mycelium #139 — leaf nodes ingest knowledge sending only `room_name`; backend resolves `workspace_id` + `mas_id` from the room or falls back to system settings. |
| `test_49_skill_cross_channel_return_trip` | Cross-channel | alpha + claire + oclw5 | Faithful SKILL.md reproduction (PR #221): 3 agents on 3 devices receive individual DMs, coordinate via a dynamic mycelium room, and replies return through their origin channels. |

### Section 50-51: OpenClaw Skill Verification

Tests that verify the mycelium skill is properly configured and functional in OpenClaw agents:

| Test | Level | Description |
|------|-------|-------------|
| `test_50_openclaw_mycelium_skill` | CLI | Verifies the mycelium skill is listed, the binary is accessible, and requirements are met. |
| `test_51_openclaw_agent_mycelium_execution` | CLI | Verifies agents can execute mycelium commands (allowlist, env, PATH, backend connectivity). |

These tests verify functional behavior rather than relying on OpenClaw's "needs setup" status (which has known false-positive bugs with tilde-path expansion).

### Section 60: Cross-Channel Memory Isolation

| Test | Level | Description |
|------|-------|-------------|
| `test_60_cross_channel_memory_isolation` | Cross-channel | Proves cross-channel memory is isolated by default and demonstrates the supported bridging pattern (mycelium room + shared memory namespace). |

---

## Test Markers

| Marker | Description |
|--------|-------------|
| `@pytest.mark.slow` | Test takes >10 seconds (LLM calls, consensus waiting) |
| `@pytest.mark.llm` | Requires LLM access (Claude via LiteLLM) |
| `@pytest.mark.matrix` | Requires Matrix homeserver |
| `@pytest.mark.cfn` | Requires IOC/CFN services |
| `@pytest.mark.convergence` | Multi-agent convergence scenario |
| `@pytest.mark.matrix_e2e` | Full Matrix E2E with local OpenClaw agents |
| `@pytest.mark.distributed` | Distributed E2E across oclw3/4/5 |
| `@pytest.mark.openclaw` | Tests OpenClaw skill configuration and agent execution |
| `@pytest.mark.cross_channel` | Cross-channel scenarios (return-trip dispatch, memory isolation) |

---

## Log Files

Test runs generate detailed logs in `~/.mycelium/e2e-logs/`:

```
e2e_run_20260410_161307.log
```

Logs include:
- All CLI command outputs
- HTTP request/response details
- Pass/fail status for each check
- Timing information
- Agent response content (truncated)

---

## Prerequisites

### Local Tests (0-32)
- Mycelium backend running (`docker compose up -d`)
- Matrix Synapse running
- IOC/CFN services running
- OpenClaw gateway running (for tests 30-32)

### Distributed Tests (40-49, 60)
- All local prerequisites
- OpenClaw agents running on oclw3 and oclw5
- Network connectivity between machines
- Valid Matrix access tokens for all agents

### Skill Verification Tests (50-51)
- OpenClaw gateway running with the mycelium skill installed (`mycelium adapter add openclaw`)

---

## Troubleshooting

### "Agents not responding"
1. Check agent status: `systemctl --user status openclaw-gateway.service`
2. Verify Matrix tokens are valid
3. Check agent can reach Matrix: `curl http://10.0.50.125:8008/_matrix/client/versions`

### "Coordination blocked"
- CFN services not running or not reachable
- Check `ctx.coordination_blocked_reason` in test output

### "LLM unavailable"
- `ANTHROPIC_AUTH_TOKEN` not set or invalid
- LiteLLM not configured

### Remote agent issues
```bash
# Check oclw3
ssh -i ~/.ssh/ioc.pem ubuntu@10.0.50.171 "systemctl --user status openclaw-gateway"

# Check oclw5
ssh -i ~/.ssh/ioc.pem ubuntu@10.0.50.142 "systemctl --user status openclaw-gateway"
```
