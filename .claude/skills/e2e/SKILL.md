---
name: e2e
description: Run end-to-end smoke tests for the Mycelium stack. Verifies install, memory, search, and aligner-mediated coordination to consensus. Use when validating a release, after a deploy, or when something feels broken.
argument-hint: "[--full | --quick]"
---

# End-to-End Testing

Run structured smoke tests against the live Mycelium stack. Tests are cumulative — each phase depends on the previous one passing.

## Arguments

- `--quick` — Stack health + memory CRUD + search only (< 1 min)
- `--full` — Quick + aligner-mediated negotiation to consensus (~ 3 min)
- No argument — defaults to `--full`

## Phase 1: Stack Health

Verify all services are running and healthy.

```bash
# 1. Backend health
curl -sf http://localhost:8000/health | python3 -m json.tool
# Expect: status=ok, database.status=ok, embedding.status=ok, llm.status=ok

# 2. Container status
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "mycelium|ioc"
# Expect: all containers healthy

# 3. CFN mgmt plane (if IoC enabled)
curl -sf http://localhost:9000/health
# Expect: {"status":"healthy"}

# 4. CFN node (if IoC enabled)
docker inspect ioc-cfn-svc --format '{{.State.Health.Status}}'
# Expect: healthy
```

**Fail criteria**: Any service unhealthy → stop and diagnose. Do not proceed.

## Phase 2: Memory CRUD + Search

Test the core memory pipeline: write, read, list, search, delete.

```bash
# Setup
mycelium room create e2e-test-room --trigger threshold:10
mycelium room use e2e-test-room

# Write memories (with embeddings)
mycelium memory set decisions/test-db "Chose Postgres for reliability" -H e2e-agent
mycelium memory set decisions/test-cache "Redis for session caching" -H e2e-agent
mycelium memory set failed/test-sqlite "SQLite can't handle concurrent writes" -H e2e-agent
mycelium memory set status/test-deploy "Staging deploy in progress" -H e2e-agent

# Read back
mycelium memory get decisions/test-db
# Expect: content matches what was written

# List
mycelium memory ls
# Expect: 4 memories listed

# List by prefix
mycelium memory ls decisions/
# Expect: 2 decisions shown in table

# Semantic search
mycelium memory search "what database did we pick"
# Expect: decisions/test-db appears with high similarity

mycelium memory search "what failed"
# Expect: failed/test-sqlite appears

# Delete
mycelium memory rm decisions/test-cache --force
mycelium memory ls
# Expect: 3 memories (test-cache gone)

# Filesystem verification
ls ~/.mycelium/rooms/e2e-test-room/decisions/
# Expect: test-db.md exists, test-cache.md gone
cat ~/.mycelium/rooms/e2e-test-room/decisions/test-db.md
# Expect: YAML frontmatter + content
```

**Fail criteria**: Any write/read/search fails → embedding or DB issue.

## Phase 3: CLI Negotiation

Test the full coordination pipeline: post positions → summon the aligner → await → respond → consensus → plan.

Coordination is the resident-runtime protocol: each participant is a live caller
that loops `await` → reason → `respond`. The **aligner** (a backend engine) runs
a real NEGMAS negotiation, `@`-addressing one agent at a time, and owns
termination — it stops the instant the agents agree, then compiles the consensus
into `plan/tasks.md`. There is no daemon and no cold-spawn: an `@`-mention to a
non-resident handle just waits on the durable transcript cursor until someone
awaits. For this smoke test, the operator plays each agent's turn by hand.

```bash
# Register the aligner once in the room
mycelium engine create aligner --kind aligner --room e2e-test-room

# Each participant posts an opening position
mycelium respond --room e2e-test-room --handle agent-alpha "Prioritize performance"
mycelium respond --room e2e-test-room --handle agent-beta  "Prioritize developer experience"

# Summon the aligner to converge
mycelium engine invoke aligner "converge on the priority tradeoff" -r e2e-test-room

# Loop each agent: await the aligner's address, then reply. Repeat until the
# plan lands. (In production the runtime does this via `mycelium await --loop
# --exec <cmd>`; here we drive it by hand.)
mycelium await   --room e2e-test-room --handle agent-alpha --json   # read the prompt
mycelium respond --room e2e-test-room --handle agent-alpha "I can accept perf caps if DX tooling ships too"
mycelium await   --room e2e-test-room --handle agent-beta  --json
mycelium respond --room e2e-test-room --handle agent-beta  "works if we keep the fast path"

# On agreement the aligner records the episode and compiles the plan BEFORE the
# consensus is announced (so the plan exists when `await` returns).
mycelium plan tasks --room e2e-test-room
# Expect: a shared - [ ] checklist with @handle owners
```

**Fail criteria**:
- `await` never returns after the summon → aligner not registered, or LLM unavailable (`mycelium status` → llm)
- Aligner loops to a step cap instead of stopping on agreement → NEGMAS termination regression (it must stop at unanimity, never run out the cap)
- No `plan/tasks.md` after convergence → plan compiler outage; check backend logs (fail-soft should still emit the raw `issue=value` agreement)
- An unreadable reply produces phantom convergence → interpretation regression (an unreadable proposer must hold its own last line, never the standing offer)

## Phase 4: Second episode (same room)

Verify a second negotiation can run in a room after the first converges. A room
is persistent; each summon opens a fresh, independent [episode](#episodes).

```bash
# Post fresh positions and summon again — same room, new episode
mycelium respond --room e2e-test-room --handle agent-gamma "Ship fast"
mycelium respond --room e2e-test-room --handle agent-delta "Ship safe"
mycelium engine invoke aligner "converge on the ship-speed tradeoff" -r e2e-test-room

# Drive the await → respond loop for both agents as in Phase 3, then:
mycelium plan tasks --room e2e-test-room
# Expect: convergence with a distinct episode id and no stale-participant errors
```

**Fail criteria**:
- Second summon reuses the first episode's transcript slice → episode isolation regression
- Aligner sees the prior episode's positions → episode scoping leaked across summons

## Phase 5: OpenClaw Integration (DEPRECATED)

> **Deprecated — does not run against current Mycelium.** OpenClaw rode the
> removed SSE/coordination-tick model (`mycelium session create`/`session join`/
> `negotiate respond`, daemon wake-on-tick), none of which exists after the SLIM
> migration and the daemon removal. The current coordination path is
> aligner-mediated await/respond (Phase 3), and the supported adapters are
> `claude_code` (proven) and `cursor` (untested), each run as a resident runtime.
> This phase is retained only as historical reference; skip it.

Test that OpenClaw agents get woken by coordination ticks and respond autonomously.

**Prerequisites**: OpenClaw gateway running, mycelium adapter installed, agents able to exec mycelium CLI. Two ways to achieve this per agent in `openclaw.json`:
- Option A (simpler): `"sandbox": {"mode": "off"}`
- Option B (preserves container isolation): `"tools": {"exec": {"host": "gateway"}}` — routes exec to the gateway host where mycelium is installed while keeping sandbox isolation for read/write/edit.

```bash
# Verify gateway + plugin
openclaw gateway status  # should show loaded
grep "mycelium.*Ready" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1

# Create room + session
mycelium room create e2e-openclaw-test
mycelium session create -r e2e-openclaw-test

# Launch both agents
openclaw agent --agent julia-agent --session-id e2e-oc-1 \
  -m "Run: mycelium session join --handle julia-agent --room e2e-openclaw-test -m 'Position A'" \
  --timeout 60 &

openclaw agent --agent selina-agent --session-id e2e-oc-2 \
  -m "Run: mycelium session join --handle selina-agent --room e2e-openclaw-test -m 'Position B'" \
  --timeout 60 &

# Wait for joins + negotiation start
sleep 50

# Check gateway logs for wake events
grep "mycelium.*wake dispatched\|mycelium.*wake completed" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -10
# Expect: wake dispatched + wake completed for both agents

# Check session messages for agent responses
mycelium room messages "e2e-openclaw-test:session:<short_id>" --limit 50
# Expect: coordination_tick messages AND direct messages from agents (accept/reject/counter_offer)

# Poll for consensus (up to 5 min for complex negotiations)
# Expect: coordination_state=complete eventually
```

**Fail criteria**:
- `wake dispatched` but no `wake completed` → openclaw CLI not on PATH or agent auth broken
- `wake completed` but no agent messages in session → agent ran but didn't execute mycelium command (check agent model/skill)
- `Plugin runtime subagent methods are only available during a gateway request` → old plugin installed, needs `mycelium adapter add openclaw --reinstall`
- SSE errors with `Failed to parse URL` → `getApiUrl()` returning empty, check `~/.mycelium/config.toml`

## Phase 5.5: Knowledge Extraction Hook (DEPRECATED — OpenClaw path)

> **Deprecated** for the same reason as Phase 5: this rides the OpenClaw hook +
> the old ingest endpoint. Retained as historical reference; skip it.


Test that the `mycelium-knowledge-extract` OpenClaw hook correctly ships conversation turns to the backend and that the backend's two-stage LLM extraction writes memories into the room.

**Prerequisites**: OpenClaw running with the `mycelium-knowledge-extract` hook installed, an agent session that has completed at least one turn, `~/.mycelium/config.toml` with valid `workspace_id` and `mas_id`.

```bash
# 1. Verify hook is installed
ls ~/.openclaw/hooks/mycelium-knowledge-extract/handler.js

# 2. Check hook state dir (delta tracking)
ls ~/.openclaw/mycelium-extract-state/

# 3. Manually fire the endpoint with a minimal synthetic payload
curl -sf -X POST http://localhost:8001/api/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "<WORKSPACE_ID from ~/.mycelium/.env>",
    "mas_id": "<MAS_ID from room>",
    "agent_id": "e2e-agent",
    "records": [{
      "schema": "openclaw-conversation-v1",
      "extractedAt": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
      "session": {"agentId": "e2e-agent", "sessionId": "e2e-test-1", "channel": "default", "cwd": "/tmp"},
      "stats": {"totalEntries": 2, "turns": 1, "toolCallCount": 0, "thinkingTurnCount": 0, "totalCost": 0},
      "turns": [{
        "index": 0,
        "timestamp": null,
        "model": "claude-sonnet-4-6",
        "stopReason": "end_turn",
        "usage": null,
        "userMessage": "What is the best way to cache database queries?",
        "thinking": null,
        "toolCalls": [],
        "response": "Use Redis with a TTL — set keys per query hash, expire after 5 minutes."
      }]
    }]
  }' | python3 -m json.tool
# Expect: 200 with extraction results

# 4. Verify memories appeared in the room (LLM extraction writes to room namespace)
mycelium memory ls
# Expect: new entries from knowledge extraction (key pattern TBD — check what ingestion_svc writes)

# 5. End-to-end via real OpenClaw agent
# Run an agent session in a room, wait for hook to fire on command:new
# Check ~/.openclaw/mycelium-knowledge-extract.log for fallback entries (means ingest failed)
# Check room memory for extracted knowledge
```

**Fail criteria**:
- 503 from `/api/knowledge/ingest` → LLM auth failure (check `LLM_MODEL` and key in `.env`)
- 200 but no memories written → `IngestionService.ingest` extraction returned empty results; check backend logs
- Hook fires but logs fallback entries → `getIngestTarget()` can't resolve `apiUrl`/`workspaceId`/`masId`; check `~/.mycelium/config.toml`
- Hook never fires → check OpenClaw hook registration (`openclaw hooks list`)

**TODO**: Determine what memory keys `IngestionService` writes and add assertions above.

---

## Cleanup

```bash
# Delete test rooms
curl -s -X DELETE http://localhost:8000/api/rooms/e2e-test-room
curl -s -X DELETE http://localhost:8000/api/rooms/e2e-openclaw-test
# Also clean up any session sub-rooms
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| Backend returns 500 on memory write | Embedding model not loaded | `docker logs mycelium-backend \| grep embed` |
| Search returns empty | Embeddings are null (wrote with --no-embed) | Reindex: `mycelium memory reindex` |
| `await` never returns after a summon | aligner not registered or LLM down | `mycelium engine ls -r <room>`; `mycelium status` → llm |
| Aligner never stops (runs to the cap) | NEGMAS termination regression | it must stop at unanimity, never run out the step cap |
| No `plan/tasks.md` after convergence | plan compiler outage | backend logs; fail-soft emits the raw `issue=value` agreement |
| Phantom convergence on an unreadable reply | interpretation regression | proposer must hold its own last line, never the standing offer |
