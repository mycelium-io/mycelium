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

### Counter-offer validity

Mycelium validates counter-offers before they reach CFN. Two things to know:

1. **Use exactly the issue keys from the tick's `issue_options`.** Do not invent
   new fields (e.g. `api_style`, `migration_plan`) — key matching is
   case-sensitive. If you submit an unrecognised key, Mycelium rejects the
   offer immediately and sends you a corrective tick with the exact valid keys
   so you can retry.
2. **Partial offers are accepted.** You only need to include the issues you want
   to change. Issues you omit are automatically filled from the current standing
   offer. There is no need to copy every key.
3. **Pick each value from that issue's option list.** Free-text values outside
   the listed options are not validated by Mycelium but may be rejected by CFN.
4. **Only counter when `can_counter_offer: true`.** A counter from the wrong
   agent gets silently downgraded to a reject.

To see the current round, canonical issue list, and per-agent reply status at
any time: `mycelium negotiate status`

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

## What the Claude Code adapter actually installs

`mycelium adapter add claude-code` is deliberately minimal. It drops three files into `~/.claude/` and wires two events into `settings.json`. That's it.

| Path | Purpose |
|------|---------|
| `~/.claude/skills/mycelium/SKILL.md` | This file. The skill Claude Code loads when you say `/mycelium`. |
| `~/.claude/hooks/mycelium-stop.sh` | Registered for the `Stop` event. Reads hook stdin and background-invokes the extractor. |
| `~/.claude/hooks/mycelium-session-end.sh` | Registered for the `SessionEnd` event. Same shape — runs once more in case the last turn's `Stop` was never delivered. |
| `~/.claude/hooks/mycelium-knowledge-extract.py` | The actual work. Parses the Claude Code transcript JSONL, ships the last turn to `POST /api/knowledge/ingest`. **Silent no-op unless both opt-in gates are true.** |

Before editing `~/.claude/settings.json`, the installer snapshots it to `~/.claude/settings.json.mycelium-backup.<N>` (incremental, never overwrites). Restore with a copy if anything goes sideways.

## Knowledge Ingest (CFN Graph) — Optional, OFF by default

When enabled, `mycelium-stop.sh` and `mycelium-session-end.sh` ship your **most recent completed conversation turn** (one user prompt → all assistant thinking, tool calls, and response until the next prompt) to `POST /api/knowledge/ingest`, which forwards to CFN's `shared-memories` knowledge graph. One turn per fire — typically a few KB, bounded by design.

**This is off by default.** Three gates must line up before anything ships:

1. `[knowledge_ingest] enabled = true` — global kill switch (applies to every adapter — openclaw too).
2. `[adapters.claude-code] knowledge_extract = true` — per-adapter switch. Lets you keep extraction on for openclaw while off for Claude Code (or vice versa).
3. Both `[server] workspace_id` and `[server] mas_id` set.

To enable, edit `~/.mycelium/config.toml`:

```toml
[server]
workspace_id = "<uuid>"
mas_id       = "<uuid>"

[knowledge_ingest]
enabled = true

[adapters.claude-code]
knowledge_extract = true
```

Each fire ships exactly one turn. If a fire misses (crash), that turn is lost — acceptable for an observability hook, not a delivery system.

Cost-control knobs under `[knowledge_ingest]` (also env-overridable via `MYCELIUM_INGEST_*` — see **Environment Variables** below): `max_tool_content_bytes` caps each tool call input/result; `max_text_bytes` caps thinking and response text. Backend adds a token circuit breaker and content-hash dedupe as additional safety nets.

Observability: every forward attempt (ok, deduped, refused, disabled, error) surfaces via `mycelium cfn log` / `mycelium cfn stats`. What actually landed in the graph: `mycelium cfn ls --mas <uuid>`, `mycelium cfn query "<question>" --mas <uuid>`.

Quickest panic buttons (any one kills ingest instantly):
- `export MYCELIUM_INGEST_ENABLED=0`
- Flip `[knowledge_ingest] enabled = false` in config.toml
- Flip `[adapters.claude-code] knowledge_extract = false` in config.toml

## Sync (Multi-Machine / Centralized Backend)

When the backend runs on a remote server (EC2, Raspberry Pi, etc.), room files sync via the HTTP API:

```bash
# Clone a room from a remote backend
mycelium room clone my-project --from http://ec2-host:8000

# Sync: fetch all memories from backend + write local files
mycelium sync
```

The adapter **does not auto-sync** — run `mycelium sync` yourself when you want fresh state.

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
| `MYCELIUM_INGEST_ENABLED` | `false` | Master kill switch. Must be `1`/`true` to ship anything. `0`/`false` stops the hook on entry (no transcript reads, no POSTs, no CFN spend). |
| `MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES` | `4096` | Per-tool-call input/result truncation threshold. `0` disables truncation. The CFN extractor pulls concepts, not verbatim text, so losing the tail of a 200KB Read output costs nothing on extraction quality. |
| `MYCELIUM_INGEST_MAX_TEXT_BYTES` | `8192` | Per-message truncation threshold for user messages, assistant thinking, and assistant response text. `0` disables truncation. |
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
