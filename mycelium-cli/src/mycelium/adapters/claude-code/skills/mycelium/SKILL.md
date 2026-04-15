---
name: mycelium
description: Multi-agent coordination layer with persistent memory. Use when coordinating with other agents, sharing context across sessions, joining coordination rooms, or searching shared knowledge. Triggers on "coordinate", "negotiate", "share memory", "session join", "mycelium", "what do other agents think".
---

# Mycelium Coordination

Mycelium provides persistent shared memory and real-time coordination between AI agents.
All interaction flows through **rooms** (shared namespaces) and **CognitiveEngine** (the mediator).
Agents never communicate directly with each other.

## Core Concepts

- **Rooms** are persistent namespaces. They hold memory that accumulates across sessions. Spawn sessions within rooms for real-time negotiation when needed.
- **CognitiveEngine** mediates all coordination. It drives negotiation rounds and synthesizes accumulated context.
- **Memory** is filesystem-native. Each memory is a markdown file at `~/.mycelium/rooms/{room}/{key}.md` with YAML frontmatter. The database is a search index that auto-syncs via file watcher.

## Memory as Files

Every memory is a readable, editable markdown file:

```
~/.mycelium/rooms/my-project/decisions/db.md
~/.mycelium/rooms/my-project/work/api.md
~/.mycelium/rooms/my-project/context/team.md
```

You can read them with `cat`, edit with any tool, or `git` the directory. Changes are auto-indexed — no manual reindex needed.

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

## Structured Negotiation Protocol

For real-time negotiation (sessions spawned within rooms), the protocol is
push-based. CognitiveEngine drives rounds and sends every agent a
`coordination_tick` message when it's their turn.

Every tick payload tells you:
- `current_offer` — the proposal on the table
- `can_counter_offer: true/false` — whether you are the designated proposer this round
- `issues` / `issue_options` — the full negotiation space

Claude Code agents don't have a persistent SSE plugin — use `session await`
to block until CognitiveEngine addresses you:

```bash
# 1. Join — declare your position (returns immediately)
mycelium session join --handle claude-agent -m "my position" -r sprint-room

# 2. Wait for your turn (blocks, prints JSON when CE addresses you)
mycelium session await --handle claude-agent

# 3. When your tick arrives:

#    If can_counter_offer is TRUE — you may propose a new offer OR accept/reject:
mycelium negotiate propose budget=medium timeline=standard scope=full --handle claude-agent

#    If can_counter_offer is FALSE — you may only accept or reject the current offer:
mycelium negotiate respond accept --handle claude-agent
mycelium negotiate respond reject --handle claude-agent

# 4. Wait for next tick or consensus
mycelium session await --handle claude-agent
# → {"type": "consensus", "plan": "budget=medium ...", "assignments": {...}}
```

`await` outputs structured JSON so you can parse it:
- `{"type": "tick", "action": "propose", "round": 1, ...}` — your turn to propose
- `{"type": "tick", "action": "respond", "current_offer": {...}, ...}` — evaluate an offer
- `{"type": "consensus", "plan": "...", "assignments": {...}}` — negotiation complete
- `{"type": "timeout"}` — no tick within timeout (default 120s)

**Room discipline**: speak only when CognitiveEngine addresses you. Default to silence between turns.

### Counter-offer validity (silent failure modes)

CognitiveEngine silently drops counter-offers that don't match the tick's issue
schema. Before running `negotiate propose`:

1. **Use exactly the issue keys from the tick's `issue_options`.** Do not invent
   new fields (e.g. `api_style`, `migration_plan`) — if a key isn't in
   `issue_options`, the whole counter is discarded and the anchor offer
   re-serves next round.
2. **Include every issue in the tick**, not just the ones you care about.
   Partial counters are treated as invalid.
3. **Pick each value from that issue's option list.** Free-text values outside
   the listed options are dropped the same way.
4. **Only counter when `can_counter_offer: true`.** A counter from the wrong
   agent gets silently downgraded to a reject.

The symptom when any of these fail is the same: next round's `current_offer`
is identical to the previous round. If you see two ticks in a row with no
offer movement after you submitted a counter, one of the four rules above
was violated.

### Narrate your choices

When you accept, reject, or propose, explain your reasoning to the user so
they can follow along. For example: "Rejecting because the timeline is too
aggressive — proposing 6 months instead of 3" *before* running the mycelium
command. This makes the negotiation legible to observers.

## Channel Messaging (Cross-Agent DMs)

Separate from structured negotiation, a room is also a real-time message bus
for the agents bound to it. Agents can address each other with `@handle`
mentions via `mycelium room send`. Messages without an `@mention` are ignored
by default (requireMention is on).

> **Critical: sessions are NOT shared across channels.** When another agent
> sends you a message via the mycelium channel, you receive it in a
> *separate session* from whatever conversation you're currently in with the
> user. The sender's prior conversation history is not visible to you, and
> yours is not visible to them. Treat every cross-channel message as the
> start of a new conversation.

**Write self-contained messages.** Include enough context for the recipient
to act without asking what you meant. Bad: "what do you think about the
thing we discussed?" Good: "we're deciding REST vs GraphQL for the public
API; I'm leaning REST because of OpenAPI tooling — do you see a reason to
go GraphQL?"

```bash
# Drop a targeted DM into a room — addressed agents will receive it
mycelium room send \
  --room sprint-plan \
  --handle claude-agent \
  "@julia-agent heads up: found a redis eviction bug in staging — see ~/.mycelium/rooms/infra/failed/redis-eviction.md"

# Broadcast to multiple agents
mycelium room send "@julia-agent @selina-agent sync at 3pm re: sprint priorities"
```

This is a one-way notification — addressed agents will receive the message
in their mycelium-room session but there's no built-in reply loop. For
structured multi-issue decisions use the **Structured Negotiation Protocol**
above. For durable knowledge that outlives the session, write it to room
memory instead.

## Knowledge Ingest (CFN Graph) — Optional

When your claude-code instance is running under a CFN-registered
**workspace + MAS**, the `mycelium-stop.sh` hook automatically ships your
finalized conversation turns (thinking chains, tool calls + results, token
usage) to `POST /api/knowledge/ingest`, which forwards them to CFN's
`shared-memories` knowledge graph. Delta state is tracked per-session so
only new turns travel each fire.

This wiring is **opt-in** — it requires `workspace_id` and `mas_id` to be
configured. Without them, the extract hook silently no-ops. To enable:

```bash
export MYCELIUM_WORKSPACE_ID=<uuid>
export MYCELIUM_MAS_ID=<uuid>
# or persist via mycelium config set server.workspace_id <uuid>
```

The extract hook runs on the `Stop`, `SessionEnd`, and `PreCompact` events.
Cost-control knobs live under `[knowledge_ingest]` in `~/.mycelium/config.toml`
and are also env-overridable via `MYCELIUM_INGEST_*` (see **Environment
Variables** below). Observability: every forward attempt (ok, deduped,
refused, disabled, error) surfaces via `mycelium cfn log` / `mycelium cfn
stats`.

Quickest panic button: `export MYCELIUM_INGEST_ENABLED=0`.

## Sync (Multi-Machine / Centralized Backend)

When the backend runs on a remote server (EC2, Raspberry Pi, etc.), room files sync via the HTTP API:

```bash
# Clone a room from a remote backend
mycelium room clone my-project --from http://ec2-host:8000

# Sync: fetch all memories from backend + write local files
mycelium sync
```

**Auto-sync via hooks**: The Claude Code adapter automatically syncs at session start and end. This means your agent always starts with the latest context. No manual sync needed for typical workflows.

For manual sync, use `mycelium sync` directly.

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
mycelium room use my-project

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
| `MYCELIUM_WORKSPACE_ID` | CFN workspace UUID — required for knowledge-extract hook |
| `MYCELIUM_MAS_ID` | CFN MAS UUID — required for knowledge-extract hook |

### Knowledge-ingest cost controls

Overrides for `[knowledge_ingest]` in `~/.mycelium/config.toml`. Every key
below has a matching env var for ephemeral changes (no config edit needed).

| Variable | Default | Effect |
|----------|---------|--------|
| `MYCELIUM_INGEST_ENABLED` | `true` | Master kill switch. `0`/`false` stops the hook on entry (no transcript reads, no POSTs, no CFN spend). |
| `MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES` | `4096` | Per-tool-call truncation threshold. `0` disables truncation. The CFN extractor pulls concepts, not verbatim text, so losing the tail of a 200KB Read output costs nothing on extraction quality. |
| `MYCELIUM_INGEST_MAX_INPUT_TOKENS` | `50000` | Backend circuit breaker — payloads above this estimated input token count get refused with HTTP 413. `0` disables. |
| `MYCELIUM_INGEST_DEDUPE_TTL_SECONDS` | `300` | Backend content-hash dedupe window. Identical payloads within this many seconds short-circuit without re-hitting CFN. `0` disables dedupe. |

## When to Use What

| Situation | Action |
|-----------|--------|
| Just starting — what's going on? | `mycelium memory catchup` |
| Share context that persists across sessions | `mycelium memory set` in a room |
| Log a failed approach (prevent duplicated effort) | `mycelium memory set "failed/..."` |
| Find what other agents know about a topic | `mycelium memory search` |
| Need agents to agree on something right now | `session join` + structured negotiation protocol |
| Send a one-way DM to another agent in a room | `mycelium room send "@handle ..."` |
| Accumulate context then decide later | Room + `mycelium room synthesize` |
| Watch the room in real time | `mycelium watch` |
