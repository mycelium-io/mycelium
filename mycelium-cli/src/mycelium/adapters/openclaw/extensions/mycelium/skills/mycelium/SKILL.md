---
name: mycelium
description: Use the mycelium CLI to join coordination rooms, negotiate with other agents via CognitiveEngine, and share persistent memory across sessions.
user-invocable: true
metadata:
  openclaw:
    homepage: https://github.com/mycelium-io/mycelium
    emoji: "🌿"
    requires:
      bins:
        - mycelium
      config:
        - ~/.mycelium/rooms/
        - ~/.mycelium/config.toml
      env:
        - MYCELIUM_API_URL
    install:
      - kind: brew
        formula: mycelium-io/tap/mycelium
        bins: [mycelium]
---

# Mycelium Coordination

Mycelium provides persistent shared memory and real-time coordination between AI agents.

## Install

> **Third-party tap**: `mycelium-io/tap` is not an official Homebrew tap. Before installing, review the tap repo and release artifacts at https://github.com/mycelium-io/homebrew-tap to confirm you trust the source.

```bash
brew install mycelium-io/tap/mycelium
```

Source: https://github.com/mycelium-io/mycelium

## OpenClaw Setup

After installing the mycelium adapter (`mycelium adapter add openclaw`), you must allowlist the mycelium binary so agents can execute mycelium commands without manual approval.

For specific agents (recommended):

```bash
openclaw approvals allowlist add --agent "agent-alpha" "~/.local/bin/mycelium"
openclaw approvals allowlist add --agent "agent-beta" "~/.local/bin/mycelium"
```

Or for all agents (convenient but less restrictive):

```bash
openclaw approvals allowlist add --agent "*" "~/.local/bin/mycelium"
```

Then restart the gateway:

```bash
openclaw gateway restart
```

Without this step, agents will prompt for approval every time they try to run a mycelium command (e.g., `mycelium session join`).
All interaction flows through **rooms** (shared namespaces) and **CognitiveEngine** (the mediator).
Agents never communicate directly with each other.

## Authentication & Data Storage

**Authentication**: The CLI connects to `MYCELIUM_API_URL` (declared in `requires.env` above, default: `http://localhost:8000`). Authentication is handled by your backend deployment — the CLI sends no credentials by default. If your backend requires auth, configure it at the server level (reverse proxy, network policy, etc.).

**Network behavior**: The CLI sends HTTP requests **only** to the single endpoint at `MYCELIUM_API_URL`. This is used for: writing memories to the search index, semantic search queries, coordination session joins/responses, and room sync. No other endpoints are contacted at runtime.

**Local data**: Memories are written as plaintext markdown files under `~/.mycelium/rooms/{room}/` (declared in `requires.config` above). These files are readable by any process with filesystem access on this machine. **Do not store secrets, credentials, or PII as room memories.** Room sync pushes/pulls these files to/from the backend via HTTP — ensure `MYCELIUM_API_URL` points to a trusted, access-controlled server.

**Scope limits**: This skill only reads and writes files under `~/.mycelium/`. It does not access files outside this directory, does not read environment variables beyond those declared above, and does not modify system configuration or other skills.

## Core Concepts

- **Rooms** are persistent namespaces. They hold memory that accumulates across sessions. Spawn sessions within rooms for real-time negotiation when needed.
- **CognitiveEngine** mediates all coordination. It drives negotiation rounds and synthesizes accumulated context.
- **Memory** is filesystem-native. Each memory is a markdown file at `~/.mycelium/rooms/{room}/{key}.md`. The database is a search index that auto-syncs.

## Memory as Files

Every memory is a readable, editable markdown file:

```
~/.mycelium/rooms/my-project/decisions/db.md
~/.mycelium/rooms/my-project/work/api.md
~/.mycelium/rooms/my-project/context/team.md
```

You can read them with your native file tools, edit them directly, or `git` the directory. Changes are auto-indexed by the file watcher — no manual reindex needed.

The filesystem is the source of truth. The database is just a search index. This means:
- `cat`, `grep`, `sed`, pipes — the full unix toolchain works on room memory
- Direct file writes from any tool participate in the room automatically
- `git push` / `git pull` shares a room across machines or agents
- Run `mycelium memory reindex` if you write files outside the watcher's view

## Memory Operations

```bash
# Write a memory (value can be plain text or JSON)
mycelium memory set <key> <value> --handle <agent-handle>
mycelium memory set "decision/api-style" '{"choice": "REST", "rationale": "simpler"}' --handle my-agent

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
mycelium memory subscribe "decision/*" --handle my-agent
```

All memory commands use the active room. Set it with `mycelium room use <name>` or pass `--room <name>`.

## Room Operations

```bash
# Create rooms
mycelium room create my-project
mycelium room create sprint-plan
mycelium room create design-review --trigger threshold:5   # with synthesis trigger

# Set active room
mycelium room use my-project

# List rooms
mycelium room ls

# Trigger CognitiveEngine to synthesize accumulated memories
mycelium room synthesize
```

## Coordination Protocol (OpenClaw)

> **Do NOT use `session await`** — that command is for synchronous single-threaded agents that must poll for their turn.
> OpenClaw agents are woken by the gateway when CognitiveEngine addresses them.
> Using `session await` will block the gateway thread and prevent other agents from responding.

The coordination protocol is **non-blocking and push-based**. Every command returns immediately.
CognitiveEngine will send you a message when it is your turn.

Every round CognitiveEngine sends every agent a `coordination_tick` with `action: respond`.
The tick payload tells you:
- `current_offer` — the proposal on the table
- `can_counter_offer: true/false` — whether you are the designated proposer this round
- `issues` / `issue_options` — the full negotiation space

```bash
# 1. Join — declare your position (returns immediately)
mycelium session join --handle <your-handle> --room <room-name> -m "I want GraphQL with a 6-month timeline"

# 2. Do nothing — CognitiveEngine will wake you when it's your turn

# 3. When your tick arrives:

#    If can_counter_offer is TRUE — you may propose a new offer OR accept/reject:
mycelium message propose ISSUE=VALUE ISSUE=VALUE ... --room <room-name> --handle <your-handle>
# example:
mycelium message propose budget=medium timeline=standard scope=full --room <room-name> --handle <your-handle>

#    If can_counter_offer is FALSE — you may only accept or reject the current offer:
mycelium message respond accept --room <room-name> --handle <your-handle>
mycelium message respond reject --room <room-name> --handle <your-handle>

# 4. [consensus] message arrives with the agreed values — proceed independently
```

> **Key rule**: `can_counter_offer: true` means it's your turn to propose. Use `mycelium message propose` to make a counter-offer, or `mycelium message respond accept/reject` to accept/reject without changing the offer. When `can_counter_offer: false`, only accept or reject.

> **Narrate your choices**: When you accept, reject, or propose, explain your reasoning in the chat so the human can follow along. For example: "Rejecting because the timeline is too aggressive — proposing 6 months instead of 3" before running the mycelium command. This makes the negotiation legible to observers.

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

## Async Workflow

```bash
# 1. Set your project room
mycelium room use my-project

# 2. Catch up on what others have done
mycelium memory catchup

# 3. Write your findings — both successes AND failures
mycelium memory set "results/cache-redis" "Redis caching reduced p99 by 40ms" --handle my-agent
mycelium memory set "results/cache-memcached" "Memcached tested, no improvement over Redis — connection overhead too high" --handle my-agent

# 4. Log decisions
mycelium memory set "decision/cache" '{"choice": "Redis", "rationale": "40ms p99 improvement, simpler ops"}' --handle my-agent

# 5. Search what others know
mycelium memory search "performance bottlenecks"

# 6. Request synthesis when enough context accumulates
mycelium room synthesize
```

**Log failures too.** When something doesn't work, write it as a memory so other agents don't repeat the same dead end. Negative results are as valuable as positive ones.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MYCELIUM_API_URL` | Yes (declared in metadata) | Backend API URL (default: `http://localhost:8000`). All network traffic goes to this single endpoint. |
| `MYCELIUM_AGENT_HANDLE` | No | Override this agent's identity handle (default: derived from OpenClaw agent ID) |
| `MYCELIUM_ROOM` | No | Override active room name (default: read from `~/.mycelium/config.toml`) |

## When to Use What

| Situation | Action |
|-----------|--------|
| Just starting — what's going on? | `mycelium memory catchup` |
| Share context that persists across sessions | `mycelium memory set` in a room |
| Log a failed approach (prevent duplicated effort) | `mycelium memory set "failed/..."` |
| Find what other agents know about a topic | `mycelium memory search` |
| Need agents to agree on something right now | Spawn session + coordination protocol |
| Accumulate context then decide later | Room + `mycelium room synthesize` |
| Watch the room in real time | `mycelium watch` |
