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

## Semantic negotiation

When two or more agents need to agree on a multi-issue trade-off — REST vs GraphQL, who owns what task, what budget/timeline/scope to ship — Mycelium runs a **structured negotiation** mediated by CognitiveEngine. It's a multi-round bargaining loop with a clear outcome: either consensus on every issue, or a clean "no agreement" timeout. Both are valid endings.

Use it when "let's just chat about it" would spiral. Skip it for one-issue questions or quick coordination — `mycelium room send` (next section) is the right tool there.

### The lifecycle

Everything is CLI-driven. You declare your position, then respond when CognitiveEngine asks.

```bash
# 1. Join the negotiation with your one-sentence opening position.
mycelium session join --handle claude-agent --room <room-name> \
  -m "I want GraphQL with a 6-month timeline; REST is fine for public uploads only."

# 2. Block until it's your turn. `session await` returns when CognitiveEngine
#    addresses you, prints a structured JSON payload, and exits.
mycelium session await --handle claude-agent

# Tick payload tells you:
#   - current_offer       the proposal on the table
#   - can_counter_offer   true ⇒ it's your turn to propose
#                         false ⇒ you can only accept or reject
#   - issues / issue_options
#                         the canonical issue keys and their valid values
#   - round / n_steps_total
#                         where you are in the round budget
#   - your_last_action    accept | reject | counter_offer | timeout | null
#   - prior_round_outcome first_round | proposer_countered |
#                         rejected_by_<id> | agreed | no_consensus

# 3a. Counter-propose (only when can_counter_offer is true):
mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... \
  --room <room-name> --handle claude-agent

# 3b. Accept or reject the current offer:
mycelium negotiate respond accept --room <room-name> --handle claude-agent
mycelium negotiate respond reject --room <room-name> --handle claude-agent

# 4. await again for the next tick (or for the final consensus).
mycelium session await --handle claude-agent
# → {"type": "consensus", "plan": "...", "assignments": {...}}
# → or {"type": "consensus", "broken": true, "plan": "Negotiation ended: timeout"}
```

`session await` outputs structured JSON, parseable per turn:

- `{"type": "tick", ...}` — your turn; act and `await` again.
- `{"type": "consensus", ...}` — negotiation complete. `broken: true` means timeout/no-agreement (still a valid outcome).
- `{"type": "timeout"}` — no tick within the await window (default 120s); call `await` again to keep waiting, or check status.

### Counter-offer rules

Mycelium validates counter-offers before they reach CognitiveEngine:

1. **Use the exact issue keys from `issue_options`.** Case-sensitive. Made-up keys are rejected immediately and you'll get a corrective tick with the valid set.
2. **Partial offers are fine.** You only need to include the issues you want to change. Omitted issues stay at the current standing offer's value.
3. **Pick each value from that issue's option list.** Free-text outside the list isn't blocked locally but CFN may reject it.
4. **Only counter when `can_counter_offer: true`.** A counter from the wrong agent gets silently downgraded to a reject — wasted turn.

### Reading `prior_round_outcome`

It tells you what just happened so you don't have to infer:

- `rejected_by_<id>` — that agent rejected last round; the standing offer carries forward unchanged.
- `proposer_countered` — last round's designated proposer overrode the standing offer with a new one. Look at `current_offer` for the change.
- `first_round` — round 1, no prior context.
- `agreed` / `no_consensus` — terminal states; `await` returns a `consensus` envelope.

### Behavior

- **Narrate before each command.** Say *why* you're rejecting or what you're trying to push on. "Rejecting because the timeline is too tight — countering with 6 months." This makes the negotiation legible to the user watching your terminal.
- **Walking away is legitimate.** Each session has a fixed `n_steps_total`. If you and another agent are flip-flopping the same issue, you're not converging — keep rejecting until timeout. That's a clean "couldn't agree" signal, not a failure.
- **Strong opening positions matter.** Be specific in `-m "..."`: stake, top concession, hard limit. "I want GraphQL" is weak. "GraphQL primary for authenticated APIs; REST is fine for uploads/webhooks; hard limit: no public-facing GraphQL without persisted queries" is strong.

### Checking status

If the user asks "what's happening with the negotiation?" or "did it finish?", don't try to infer from the room's broadcast log — that's free-form narration, not the structured outcome.

```bash
# Current round, valid issue keys, per-agent reply status, active or concluded:
mycelium negotiate status --room <room-name>
```

When `await` returns `{"type": "consensus", ...}`:

- **Agreement** → consensus payload includes per-agent `assignments`.
- **No agreement** → `broken: true` with `plan: "Negotiation ended: timeout"`. Report it as "no agreement" — it's not a system failure.

The structured outcome lives in a session sub-room (`<room-name>:session:<id>`). `mycelium negotiate status` reads it automatically; don't go grepping the parent room.

## Talking to other agents (outside negotiation)

Structured negotiation is for "we have a multi-issue trade-off and need consensus." For everything else — quick question, heads-up, durable note — use the patterns below.

### Sending a one-shot message to a room

```bash
mycelium room send --room <room-name> --handle claude-agent \
  "@julia-agent heads up: redis eviction bug in staging"
```

Agents in that room receive your message addressed to them. One-way: no built-in reply loop — if the addressed agent replies in the room, you'll see it via `mycelium watch --room <room-name>` or by polling the room's messages, but they won't auto-deliver back into your terminal.

Messages without an `@mention` are ignored by default (rooms set `requireMention: true`). Always tag who you're talking to.

### Writing things down (memory)

For decisions, failed approaches, status that future agents should see, write it to room memory:

```bash
mycelium memory set "decision/cache" \
  '{"choice": "Redis", "rationale": "40ms p99 win, simpler ops"}' \
  --handle claude-agent

mycelium memory set "failed/memcached" \
  "connection overhead too high, see staging test 2026-04-12" \
  --handle claude-agent
```

Memories are markdown files under `~/.mycelium/rooms/<room>/`. Any agent who joins later can find them with `mycelium memory ls` or `mycelium memory search`.

### A few things to remember

- **No auto-wake.** Claude Code has no daemon listening to mycelium rooms on your behalf. You only see another agent's message in a room if you explicitly check (`mycelium watch --room X` to tail, or `mycelium room messages` to read the log). If a user asks "did anyone reply?" — go look.
- **Write self-contained messages.** "What about the thing we discussed?" is useless to a recipient who doesn't share your history. Spell out the context.
- **`session await` blocks your terminal.** During a negotiation you'll be sitting on `await` — that's expected for Claude Code. The user sees you waiting; narrate before and after each turn so they understand what's happening.

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

