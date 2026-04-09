---
name: e2e
description: Run end-to-end smoke tests for the Mycelium stack. Verifies install, memory, search, coordination, and OpenClaw integration. Use when validating a release, after a deploy, or when something feels broken.
argument-hint: "[--full | --quick | --openclaw]"
---

# End-to-End Testing

Run structured smoke tests against the live Mycelium stack. Tests are cumulative — each phase depends on the previous one passing.

## Arguments

- `--quick` — Stack health + memory CRUD + search only (< 1 min)
- `--full` — Quick + CLI negotiation to consensus (~ 3 min)
- `--openclaw` — Full + OpenClaw agent wake/respond test (~ 5 min, requires gateway running)
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
docker inspect ioc-cognition-fabric-node-svc --format '{{.State.Health.Status}}'
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

Test the full coordination pipeline: session create → join → tick → respond → consensus.

```bash
# Create session
mycelium session create -r e2e-test-room
# Expect: session ID, CFN enabled (if IoC)

# Two agents join
mycelium session join --handle agent-alpha -m "Prioritize performance" -r e2e-test-room
mycelium session join --handle agent-beta -m "Prioritize developer experience" -r e2e-test-room

# Wait for join timer (~30s) + CFN start
sleep 40

# Check state
curl -s http://localhost:8000/rooms/e2e-test-room | python3 -c "import sys,json; [print(f'{r[\"name\"]}: {r[\"coordination_state\"]}') for r in json.load(sys.stdin)] if isinstance(json.load(open('/dev/stdin')), list) else None" 2>/dev/null
# Or check session room directly from session create output

# Await first tick
mycelium session await --handle agent-alpha -r e2e-test-room
# Expect: JSON with type=tick, round>=1, action=respond, issue_options present

# Accept loop — repeat until consensus is returned
# Use `mycelium message respond accept` (NOT `mycelium session respond` — that doesn't exist)
# Both agents must accept each round before CFN advances
mycelium message respond accept --room e2e-test-room --handle agent-alpha
mycelium message respond accept --room e2e-test-room --handle agent-beta
mycelium session await --handle agent-alpha -r e2e-test-room
# Repeat above 3 lines until type=consensus

# To propose a counter-offer instead of accepting:
#   mycelium message propose ISSUE=VALUE ISSUE=VALUE --room e2e-test-room --handle agent-alpha

# Verify consensus
# Expect: type=consensus, assignments dict populated, broken=false
```

**Fail criteria**:
- No ticks after 60s → CFN not configured or join timer didn't fire
- Ticks arrive but state never reaches complete → check `_expand_slim` and CFN `/decide` logs
- `broken: true` in consensus → CFN returned error status

## Phase 4: Multi-Session (same room)

Verify a second negotiation can run in a room after the first completes.

```bash
# Session 2 in the same room
mycelium session create -r e2e-test-room
# Expect: new session ID (different from session 1)

# New agents join
mycelium session join --handle agent-gamma -m "Ship fast" -r e2e-test-room
mycelium session join --handle agent-delta -m "Ship safe" -r e2e-test-room

# Drive to consensus (same accept loop as Phase 3)
# Expect: consensus reached without stale participant errors
```

**Fail criteria**:
- `session create` returns the old completed session → `_spawn_session_room` not filtering completed state
- CFN start fails → stale Session rows not cleaned up (check `_finish_cfn`)

## Phase 5: OpenClaw Integration

Test that OpenClaw agents get woken by coordination ticks and respond autonomously.

**Prerequisites**: OpenClaw gateway running, mycelium adapter installed, agents configured with sandbox=off.

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
curl -s "http://localhost:8000/rooms/e2e-openclaw-test:session:*/messages?limit=50"
# Expect: coordination_tick messages AND direct messages from agents (accept/reject/counter_offer)

# Poll for consensus (up to 5 min for complex negotiations)
# Expect: coordination_state=complete eventually
```

**Fail criteria**:
- `wake dispatched` but no `wake completed` → openclaw CLI not on PATH or agent auth broken
- `wake completed` but no agent messages in session → agent ran but didn't execute mycelium command (check agent model/skill)
- `Plugin runtime subagent methods are only available during a gateway request` → old plugin installed, needs `mycelium adapter add openclaw --reinstall`
- SSE errors with `Failed to parse URL` → `getApiUrl()` returning empty, check `~/.mycelium/config.toml`

## Phase 5.5: Knowledge Extraction Hook (PENDING — not yet tested)

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
curl -s -X DELETE http://localhost:8000/rooms/e2e-test-room
curl -s -X DELETE http://localhost:8000/rooms/e2e-openclaw-test
# Also clean up any session sub-rooms
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| Backend returns 500 on memory write | Embedding model not loaded | `docker logs mycelium-backend \| grep embed` |
| Search returns empty | Embeddings are null (wrote with --no-embed) | Reindex: `mycelium memory reindex` |
| Ticks never arrive | CFN not configured on room | `curl rooms/{room}` → check mas_id/workspace_id |
| Ticks arrive but agents don't respond | OpenClaw plugin using old subagent.run() | Reinstall adapter |
| Consensus has empty assignments | CFN response envelope not normalized | Check `_normalize_cfn_decide_response` |
| Second session reuses completed room | Session cleanup bug | Check `_spawn_session_room` state filter |
| Backend hangs after a few rounds | `_expand_slim` DB session leak | Check for idle-in-transaction in `pg_stat_activity` |
