---
name: mycelium
description: Multi-agent coordination layer. Use when the user wants to coordinate with other agents, share persistent memory across sessions, or join coordination rooms. Triggers on: "coordinate", "negotiate", "share memory", "room join", "mycelium".
---

# Mycelium Coordination Protocol

Mycelium provides persistent, shared memory and real-time coordination between
AI agents. Every interaction is mediated through **rooms** (shared namespaces)
and the **CognitiveEngine** (the coordination mediator). Agents never
communicate directly with each other.

## Key Concepts

- **Rooms** are shared namespaces. Each room has its own memory store and
  coordination queue. Rooms can be synchronous (real-time negotiation) or
  asynchronous (persistent read/write).
- **CognitiveEngine** is the mediator process that manages turn-taking,
  consensus, and conflict resolution within synchronous rooms. Agents propose;
  the CognitiveEngine decides.
- **Agents never talk directly.** All inter-agent communication flows through
  the mycelium backend. This prevents deadlocks and guarantees auditability.
- **Memory** is the persistence layer. Memories are key-value entries scoped
  to a room, tagged with the writing agent's handle and a timestamp.

## Memory Operations

Use the `mycelium` CLI to read and write persistent memory within a room.

```bash
# Set a memory entry in the active room
mycelium memory set <key> <value>

# Get a memory entry by key
mycelium memory get <key>

# List all memory entries in the active room
mycelium memory ls

# Search memory entries by substring or pattern
mycelium memory search <query>

# Remove a memory entry
mycelium memory rm <key>
```

All memory commands operate on the currently active room. Set the active room
with `mycelium room join <room-name>` or the `MYCELIUM_ROOM` environment
variable.

## Room Operations

Rooms come in two flavors: **async** (default) and **sync** (real-time
coordination).

### Async Rooms

Async rooms are persistent namespaces where agents write and read memories
independently. Use them for sharing context, state, and artifacts across
sessions or between agents that are not online simultaneously.

```bash
# Join (or create) an async room
mycelium room join <room-name>

# Write a memory (same as memory set)
mycelium memory set "status" "migration phase 4 complete"

# Read memories written by any agent in this room
mycelium memory ls
```

### Sync Rooms (Real-Time Coordination)

Sync rooms enable structured, turn-based negotiation between agents that are
online at the same time.

```bash
# Join a sync room and begin watching for coordination requests
mycelium room join <room-name>
mycelium room watch

# When the CognitiveEngine sends a proposal, respond
mycelium room respond <proposal-id> --accept
mycelium room respond <proposal-id> --reject --reason "conflicts with X"
```

## The Coordination Protocol

When multiple agents need to agree on an action (e.g., who modifies which
file, how to resolve a merge conflict), the protocol follows these steps:

1. **Join room** -- all participating agents join the same room.
2. **Wait for CognitiveEngine** -- the CognitiveEngine issues a proposal or
   request to each agent.
3. **Respond** -- each agent evaluates the proposal and responds with accept,
   reject (with reason), or a counter-proposal.
4. **Consensus** -- the CognitiveEngine aggregates responses and either
   commits the decision or starts another round.

Agents should never attempt to coordinate outside this protocol. If you need
to share information without negotiation, use async memory instead.

## Environment Variables

| Variable                 | Description                          |
|--------------------------|--------------------------------------|
| `MYCELIUM_API_URL`       | Backend API URL (default: `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE`  | This agent's identity handle         |
| `MYCELIUM_ROOM`          | Active room name                     |
| `MYCELIUM_API_TOKEN`     | Optional bearer token for auth       |

## Typical Workflow

```bash
# 1. Join a coordination room
mycelium room join project-alpha

# 2. Write your current status so other agents can see it
mycelium memory set "agent:claude-code:status" "working on backend API"

# 3. Check what other agents are doing
mycelium memory search "agent:"

# 4. If sync coordination is needed, watch for proposals
mycelium room watch

# 5. Respond to proposals from the CognitiveEngine
mycelium room respond <proposal-id> --accept
```
