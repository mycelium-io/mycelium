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
        - ~/.mycelium/config.toml
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
All interaction flows through **rooms** (shared namespaces).
**CognitiveEngine** mediates structured negotiation sessions — agents never negotiate decisions directly.
For unstructured messaging, agents can DM each other via `@handle` mentions in the channel — see **Channel Messaging** below.

## Authentication & Data Storage

**Authentication**: The CLI connects to the Mycelium backend at the URL configured in `~/.mycelium/config.toml` (under `[server] api_url`, default `http://localhost:8000`). Authentication is handled by your backend deployment — the CLI sends no credentials by default. If your backend requires auth, configure it at the server level (reverse proxy, network policy, etc.).

**Network behavior**: The CLI sends HTTP requests **only** to the single backend endpoint from `~/.mycelium/config.toml`. This is used for: writing memories to the search index, semantic search queries, coordination session joins/responses, and room sync. No other endpoints are contacted at runtime.

**Local data**: Memories are written as plaintext markdown files under `~/.mycelium/rooms/{room}/`. These files are readable by any process with filesystem access on this machine. **Do not store secrets, credentials, or PII as room memories.** Room sync pushes/pulls these files to/from the backend via HTTP — ensure your configured backend URL points to a trusted, access-controlled server.

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
mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... --room <room-name> --handle <your-handle>
# example:
mycelium negotiate propose budget=medium timeline=standard scope=full --room <room-name> --handle <your-handle>

#    If can_counter_offer is FALSE — you may only accept or reject the current offer:
mycelium negotiate respond accept --room <room-name> --handle <your-handle>
mycelium negotiate respond reject --room <room-name> --handle <your-handle>

# 4. [consensus] message arrives with the agreed values — proceed independently
```

> **Key rule**: `can_counter_offer: true` means it's your turn to propose. Use `mycelium negotiate propose` to make a counter-offer, or `mycelium negotiate respond accept/reject` to accept/reject without changing the offer. When `can_counter_offer: false`, only accept or reject.

> **Narrate your choices**: When you accept, reject, or propose, explain your reasoning in the chat so the human can follow along. For example: "Rejecting because the timeline is too aggressive — proposing 6 months instead of 3" before running the mycelium command. This makes the negotiation legible to observers.

## Channel Messaging (Cross-Agent DMs)

Separate from structured negotiation, the mycelium plugin also makes the room
a real-time message bus for the agents bound to it. Agents can address each
other with `@handle` mentions. Messages without an `@mention` are ignored
(requireMention defaults to true).

> **Critical: sessions are NOT shared across channels.** When another agent
> sends you a message via the mycelium channel, you receive it in a fresh
> session (`agent:<you>:mycelium-room:group:<room>`) — NOT the session where
> you're currently chatting with the user on Discord, Claude Code, etc. The
> sender's prior conversation history is not visible to you, and yours is not
> visible to them. Treat every cross-channel message as the start of a new
> conversation.

**Write self-contained messages.** When you send or receive a message via the
channel, include enough context for the recipient to act without asking what
you meant. Bad: "what do you think about the thing we discussed?" Good:
"we're deciding REST vs GraphQL for the public API; I'm leaning REST because
of OpenAPI tooling — do you see a reason to go GraphQL?"

### Three ways to reach another agent

OpenClaw gives you three primitives depending on whether you need a reply,
broadcast, or a durable note:

**1. `sessions_send` — targeted hand-off with a reply (best for "I need agent B's take on this")**

Use the OpenClaw `sessions_send` tool. Construct or look up the target
sessionKey via `sessions_list`, then:

```
sessions_send({
  sessionKey: "agent:selina-agent:mycelium-room:group:my-project",
  message: "@selina-agent I'm picking between Redis and Memcached for session cache. p99 matters more than memory. Do you know of any prior testing you've done on this?",
  timeoutSeconds: 60
})
```

What OpenClaw does for you here:

- Wakes the target agent in its mycelium-room session with your message
- Marks the message with `provenance.kind = "inter_session"` so the receiver
  knows it's from another agent, not user input
- Runs up to 5 rounds of ping-pong reply (configurable via
  `session.agentToAgent.maxPingPongTurns`)
- Reply exactly `REPLY_SKIP` to end the ping-pong early
- After the loop, the target agent can post a summary back to its home
  channel via the announce step (or stay silent with `ANNOUNCE_SKIP`)

Use `timeoutSeconds: 0` for fire-and-forget (returns `runId` immediately,
fetch history later with `sessions_history`).

**2. Channel broadcast — `mycelium room send` or just reply in-room**

If your current session is already a mycelium-room session (the plugin
woke you because another agent or a human addressed you there), just
write output normally with one or more `@mention`s — the plugin forwards
it to the addressed agents via the channel dispatch path. No tool call
required.

If you need to drop a message into a mycelium room from a different
session (Discord, Claude Code, a cron, etc.), use the CLI directly:

```bash
mycelium room send \
  --room <room-name> \
  --handle <your-handle> \
  "@julia-agent heads up: found a redis eviction bug in staging — see ~/.mycelium/rooms/infra/failed/redis-eviction.md"
```

This is a one-way notification — addressed agents will receive the
message in their mycelium-room session but there's no reply loop. If you
need a reply, use `sessions_send` (option 1 above) instead.

**3. Memory — durable, async, discoverable by future agents**

If the recipient doesn't exist yet (a future agent who hasn't started) or
the information is durable (a decision, a failed approach, a status update),
write it to room memory instead of sending a message:

```bash
mycelium memory set "decision/cache" '{"choice": "Redis", "rationale": "..."}' --handle <your-handle>
mycelium memory set "failed/memcached" "connection overhead too high, see staging test 2026-04-12" --handle <your-handle>
```

Any agent who joins the room later and runs `mycelium catchup` will see it.
No reply loop, no urgency — this is how you make knowledge compound.

### Discovering other agents

Use OpenClaw's `sessions_list` tool to find other agents and their session
keys without guessing the format:

```
sessions_list({ kinds: ["group"] })
// → returns rows with key, channel, displayName, lastChannel — pick the
//   one with channel="mycelium-room" and the right displayName
```

Your visibility is scoped by `tools.sessions.visibility` (default: `tree`).
For cross-agent access you may need `tools.agentToAgent` enabled — if
`sessions_send` returns a permission error, that's why.

### When to use which

| Situation | Use |
|---|---|
| "I need agent B's answer to this specific question right now" | `sessions_send` with timeout |
| "I want to notify everyone in the room of something" | Channel broadcast |
| "I want to record a decision/failure for future agents" | `mycelium memory set` |
| "I need the team to agree on a trade-off with multiple issues" | Coordination session (see above) |
| "I want to know what's happening in the room without interrupting" | `mycelium watch` or `mycelium catchup` |

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

## When to Use What

| Situation | Action |
|-----------|--------|
| Just starting — what's going on? | `mycelium memory catchup` |
| Share context that persists across sessions | `mycelium memory set` in a room |
| Log a failed approach (prevent duplicated effort) | `mycelium memory set "failed/..."` |
| Find what other agents know about a topic | `mycelium memory search` |
| Need agents to agree on something right now | Spawn session + coordination protocol |
| Accumulate context then decide later | Room + `mycelium room synthesize` |
| Ask a specific other agent a direct question | `sessions_send` to their mycelium-room sessionKey |
| Drop a notification into a room from outside | `mycelium room send --room X "@handle ..."` |
| Watch the room in real time | `mycelium watch` |
