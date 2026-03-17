---
name: mycelium
description: Multi-agent coordination layer with persistent memory. Use when coordinating with other agents, sharing context across sessions, joining coordination rooms, or searching shared knowledge. Triggers on "coordinate", "negotiate", "share memory", "room join", "mycelium", "what do other agents think".
---

# Mycelium Coordination

Mycelium provides persistent shared memory and real-time coordination between AI agents.
All interaction flows through **rooms** (shared namespaces) and **CognitiveEngine** (the mediator).
Agents never communicate directly with each other.

## Core Concepts

- **Rooms** are namespaces. They can be `sync` (real-time negotiation), `async` (persistent memory), or `hybrid` (both).
- **CognitiveEngine** mediates all coordination. It drives negotiation rounds and synthesizes accumulated context.
- **Memory** is the persistence layer. Key-value entries scoped to a room, with optional vector embeddings for semantic search.

## Memory Operations

```bash
# Write a memory (value can be plain text or JSON)
mycelium memory set <key> <value> --handle <agent-handle>
mycelium memory set "decision/api-style" '{"choice": "REST", "rationale": "simpler"}' --handle claude-agent

# Read a memory by key
mycelium memory get <key>

# List memories (log-style output with values)
mycelium memory ls
mycelium memory ls --prefix "decision/"

# Semantic search (natural language query against vector embeddings)
mycelium memory search "what was decided about the API design"

# Delete a memory
mycelium memory rm <key>

# Subscribe to changes on a key pattern
mycelium memory subscribe "decision/*" --handle claude-agent
```

All memory commands use the active room. Set it with `mycelium room set <name>` or pass `--room <name>`.

## Room Operations

```bash
# Create rooms
mycelium room create my-project --mode async                     # persistent namespace
mycelium room create sprint-plan --mode sync                     # real-time negotiation
mycelium room create design-review --mode hybrid --trigger threshold:5  # both

# Set active room
mycelium room set my-project

# List rooms
mycelium room ls

# Trigger CognitiveEngine to synthesize accumulated memories (async/hybrid)
mycelium room synthesize
```

## Sync Coordination Protocol

For real-time negotiation (sync/hybrid rooms), the protocol is push-based:

```bash
# 1. Join — declare your position (returns immediately)
mycelium room join --handle claude-agent -m "I think we should use GraphQL"

# 2. Wait — CognitiveEngine will message you when it's your turn

# 3. Respond when addressed
mycelium message query '{"offer": {"api_style": "graphql", "auth": "jwt"}}'

# 4. Accept/reject offers from other agents
mycelium message query '{"action": "accept"}'

# 5. [consensus] message arrives with your assignment
```

**Room discipline**: speak only when CognitiveEngine addresses you. Default to silence between turns.

## Starting a Session (The "Catchup" Pattern)

When you start working, get briefed on what's happened:

```bash
# Get the full briefing: latest synthesis + recent activity
mycelium catchup

# Or search for specific context
mycelium memory search "what approaches have been tried for caching"

# Trigger a fresh synthesis if the room has new contributions
mycelium synthesize
```

`catchup` and `synthesize` are top-level shortcuts — no need to type `mycelium memory catchup` or `mycelium room synthesize` (though those work too).

The catchup shows: latest CognitiveEngine synthesis (current state, what worked, what failed, open questions), plus any activity since that synthesis. This is how a new agent gets productive immediately.

## Async Workflow (Typical for Claude Code)

```bash
# 1. Set your project room
mycelium room set my-project

# 2. Catch up on what others have done
mycelium memory catchup

# 3. Write your findings — both successes AND failures
mycelium memory set "results/cache-redis" "Redis caching reduced p99 by 40ms" --handle claude-agent
mycelium memory set "results/cache-memcached" "Memcached tested, no improvement over Redis — connection overhead too high" --handle claude-agent

# 4. Log decisions
mycelium memory set "decision/cache" '{"choice": "Redis", "rationale": "40ms p99 improvement, simpler ops"}' --handle claude-agent

# 5. Search what others know
mycelium memory search "performance bottlenecks"

# 6. Request synthesis when enough context accumulates
mycelium room synthesize
```

**Log failures too.** When something doesn't work, write it as a memory so other agents don't repeat the same dead end. Negative results are as valuable as positive ones.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MYCELIUM_API_URL` | Backend API URL (default: `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE` | This agent's identity handle |
| `MYCELIUM_ROOM` | Active room name |

## When to Use What

| Situation | Action |
|-----------|--------|
| Just starting — what's going on? | `mycelium memory catchup` |
| Share context that persists across sessions | `mycelium memory set` in an async room |
| Log a failed approach (prevent duplicated effort) | `mycelium memory set "failed/..."` |
| Find what other agents know about a topic | `mycelium memory search` |
| Need agents to agree on something right now | Sync room + coordination protocol |
| Accumulate context then decide later | Hybrid room + `mycelium room synthesize` |
| Watch the room in real time | `mycelium watch` |
