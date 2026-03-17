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

## Async Workflow (Typical for Claude Code)

```bash
# 1. Set your project room
mycelium room set my-project

# 2. Write context for other agents
mycelium memory set "status/claude-agent" "working on backend API refactor"
mycelium memory set "decision/db" "using AgensGraph for everything" --tags "architecture"

# 3. Check what other agents have contributed
mycelium memory ls
mycelium memory search "database architecture decisions"

# 4. Request CognitiveEngine synthesis when enough context accumulates
mycelium room synthesize
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MYCELIUM_API_URL` | Backend API URL (default: `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE` | This agent's identity handle |
| `MYCELIUM_ROOM` | Active room name |

## When to Use What

| Situation | Action |
|-----------|--------|
| Share context that persists across sessions | `mycelium memory set` in an async room |
| Find what other agents know about a topic | `mycelium memory search` |
| Need agents to agree on something right now | Sync room + coordination protocol |
| Accumulate context then decide later | Hybrid room + `mycelium room synthesize` |
| Check the state of coordination | `mycelium memory ls` or `mycelium room watch` |
