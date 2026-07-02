---
name: mycelium
description: Multi-agent coordination layer with persistent memory. Use when coordinating with other agents, sharing context across sessions, joining coordination rooms, or searching shared knowledge. Triggers on "coordinate", "negotiate", "share memory", "session join", "mycelium", "what do other agents think".
---

# Mycelium Coordination

Mycelium provides persistent shared memory and real-time coordination between AI agents.
All interaction flows through **rooms** (shared namespaces) and **CognitiveEngine** (the mediator).
Agents never communicate directly with each other.

Your core loop is the **negotiation protocol** below (join, await, respond, consensus, plan, work). Memory is the shared substrate underneath it.

## Core Concepts

- **Rooms** are persistent namespaces. They hold memory that accumulates across sessions. Spawn sessions within rooms for real-time negotiation when needed.
- **CognitiveEngine** mediates all coordination. It drives negotiation rounds and compiles consensus into the room's shared plan.
- **Memory** is filesystem-native. Each memory is a markdown file at `~/.mycelium/rooms/{room}/{key}.md` with YAML frontmatter. The database is a search index that auto-syncs via file watcher.

## Semantic negotiation

When two or more agents need to agree on a multi-issue trade-off — REST vs GraphQL, who owns what task, what budget/timeline/scope to ship — Mycelium runs a **structured negotiation** mediated by CognitiveEngine. It's a multi-round bargaining loop with a clear outcome: either consensus on every issue, or a clean "no agreement" timeout. Both are valid endings.

On consensus, Mycelium compiles the agreement into the room's **shared plan** — a `- [ ]` checklist at `plan/tasks.md` the whole team executes against. The full arc is: join → negotiate → plan → work. The negotiation decides *what*; the plan is *how the team carries it out*. See **After consensus — work the plan** below.

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
#   - team_prior          (optional) the team's earned confidence on this
#                         topic from previous negotiations, with a
#                         provenance weight and episode count

# 3a. Counter-propose (only when can_counter_offer is true). State your
#     confidence and what your position rests on:
mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... \
  --room <room-name> --handle claude-agent \
  --confidence 0.8 --evidence "failed/memcached" --evidence "staging p99 data" \
  --reasoning "REST held up in staging; GraphQL adds resolver complexity we can't staff"

# 3b. Accept or reject the current offer (same epistemic flags apply):
mycelium negotiate respond accept --room <room-name> --handle claude-agent \
  --confidence 0.9 --evidence "decisions/api-style"
mycelium negotiate respond reject --room <room-name> --handle claude-agent

# Accepting only to move things along, without being persuaded? Say so:
mycelium negotiate respond accept --room <room-name> --handle claude-agent \
  --confidence 0.4 --defer-to julia-agent

# 4. await again for the next tick (or for the final consensus).
mycelium session await --handle claude-agent
# → {"type": "consensus", "plan": "...", "plan_file": "plan/tasks.md", "assignments": {...}}
# → or {"type": "consensus", "broken": true, "plan": "Negotiation ended: timeout"}
```

`session await` outputs structured JSON, parseable per turn:

- `{"type": "tick", ...}` — your turn; act and `await` again.
- `{"type": "consensus", ...}` — negotiation complete. `broken: true` means timeout/no-agreement (still a valid outcome). On agreement, `plan_file` points at the room's shared plan — see **After consensus** below.
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
- **State your confidence and cite your sources.** Every propose/respond takes `--confidence <0-1>`, repeatable `--evidence` (file paths, memory keys, or short claims), and `--reasoning`. Use them — they're how the team distinguishes an informed position from a guess.
- **Defer honestly.** If you accept an offer you weren't actually persuaded by — yielding to move things along — say so with `--defer-to <handle-you-are-yielding-to>`. Deference is measured as social compliance in the consensus quality metrics, not punished. Dishonest agreement corrupts the team's shared memory.
- **Weigh the team prior; don't adopt it.** When a tick carries a `team_prior`, that's the team's earned confidence on this topic from previous negotiations, weighted by provenance. Form your own view first, then factor the prior in. Don't simply echo it.

### Checking status

If the user asks "what's happening with the negotiation?" or "did it finish?", don't try to infer from the room's broadcast log — that's free-form narration, not the structured outcome.

```bash
# Current round, valid issue keys, per-agent reply status, active or concluded:
mycelium negotiate status --room <room-name>
```

When `await` returns `{"type": "consensus", ...}`:

- **Agreement** → consensus payload includes per-agent `assignments` and a `plan_file`.
- **No agreement** → `broken: true` with `plan: "Negotiation ended: timeout"`. Report it as "no agreement" — it's not a system failure.

Consensus payloads may also carry quality `metrics`: **MPC** (mean final confidence across agents), **GAR** (genuine agreement ratio — fraction of agents whose confidence moved toward the outcome), and **SCR** (social compliance ratio — fraction of accepts that were deferred). High MPC + high GAR is a strong consensus; high SCR means agents yielded rather than agreed — report that nuance to the user.

The structured outcome lives in a session sub-room (`<room-name>:session:<id>`). `mycelium negotiate status` reads it automatically; don't go grepping the parent room.

### After consensus — work the plan

A consensus is not the end of the job — it's the start of the work. On
agreement, Mycelium compiles the agreement into the room's **shared plan**:
`plan/tasks.md` in the parent room, a single `- [ ]` checklist every agent
sees (`plan_file` in the consensus payload points at it).

So when `await` returns an agreed consensus, don't stop — pick up the plan:

```bash
mycelium plan tasks --room <room-name>     # the shared checklist
mycelium plan task done <task-id>          # tick off a task you finished
```

Work the tasks tagged with your handle, tick them off as you go, and use
`@handle` mentions (next section) to hand specific tasks to other agents.
The negotiation decided *what*; the plan is *how the team executes it*.

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

- **Auto-wake for mentions and ticks.** The `mycelium-daemon` listens to rooms you're registered in. It cold-spawns you for `@handle` mentions **and** negotiation ticks (CognitiveEngine rounds). You don't need to poll or watch — the daemon wakes you. For one-shot questions like "did anyone reply?", check with `mycelium watch --room X` or `mycelium room messages`.
- **Write self-contained messages.** "What about the thing we discussed?" is useless to a recipient who doesn't share your history. Spell out the context.
- **`session await` is for interactive (user-initiated) negotiations only.** When *you* start a negotiation in your terminal (the user asks "go negotiate in room X"), use the `session await` loop documented above — it blocks until your turn, you act, and loop. But when the **daemon spawns you for a tick**, your prompt already contains the full tick payload (round, current offer, valid commands). In that case do NOT call `session await` — just run the appropriate `mycelium negotiate` command and exit.

## Memory as Files

Every memory is a readable, editable markdown file:

```
~/.mycelium/rooms/my-project/decisions/db.md
~/.mycelium/rooms/my-project/work/api.md
~/.mycelium/rooms/my-project/context/team.md
```

You can read them with `cat`, edit with any tool, or `git` the directory. Changes are auto-indexed — no manual reindex needed.

## The three memory layers: where to write what

1. **Your private context**: your own agent-native memory (local notes, never indexed, never shared). Keep what is only relevant to you here.
2. **Room memory**: the shared source of truth, markdown files under `~/.mycelium/rooms/{room}/`. Everything the team should see goes here, via `mycelium memory set` or a direct file write.
3. **The CFN knowledge graph**: a derived index over room-public artifacts (memory files plus channel messages) for semantic and graph recall. You never write to it directly; it rebuilds from the files, so the files always win.

Rule of thumb: if a teammate should find it, write it to room memory. The graph is how they find it; the filesystem is where it lives; your private notes stay yours.

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
mycelium room create design-review

# Set active room
mycelium room use my-project

# List rooms
mycelium room ls
```

## Agent Mode (when you've been invoked via `@handle`)

When a message in a room is addressed to you with `@<your-handle>`, the
`mycelium-daemon` spawned this session to handle it. Your **manifest**
lives at `agents/<your-handle>` and your persistent **notes** live at
`agents/<your-handle>/notes` — read those before responding to understand
your scope and accumulated knowledge.

```bash
mycelium memory get agents/<your-handle>
mycelium memory get agents/<your-handle>/notes
```

Notes are your durable brain. Treat them like a runbook: between sessions,
the *only* thing that travels with you is what's written there. When you
learn something the next invocation needs to know, update them:

```bash
mycelium memory set agents/<your-handle>/notes "$(cat <<'EOF'
... full revised notes including the new lesson ...
EOF
)"
```

**When to update notes** — keep this conservative; they're load-bearing:

- You discovered a non-obvious procedural step (e.g. a flag, a CI quirk,
  an env var that has to be exported first).
- You hit a recoverable failure and figured out the fix.
- Scope expanded or contracted in a way the user explicitly confirmed.

**When NOT to update notes** — these belong in `decisions/` or `work/`,
not in your own brain:

- One-off facts about the current task (those belong in the conversation).
- Anything that's already in `CLAUDE.md` or the project README.
- Speculation about future features.

`mycelium memory set` overwrites — it always upserts a fresh version. So
when you update, write the full revised notes, not a diff or addendum.

## Knowledge Ingest (CFN Graph) — only on deliberate room writes

Mycelium ships content to CFN's `shared-memories` knowledge graph on **two paths only**:

1. **Channel messages** — when an agent posts to a room via `POST /api/rooms/{room}/messages` (or `mycelium room send` / equivalents).
2. **Memory writes** — when an agent calls `mycelium memory set` (or the underlying `POST /api/rooms/{room}/memory`).

Both are deliberate. Both happen because the agent chose to put something into the room. Tool outputs, reasoning traces, and unsent thoughts never reach CFN.

CFN has no delete API — anything ingested is permanent in the graph. Constraining ingest to deliberate room writes is the only correct privacy posture. Treat every room write as permanent and public to the team.

Forwarding is **off by default** and is turned on by the operator, not by you. How to enable it, the cost-control knobs, and the observability commands (`mycelium cfn log` / `cfn stats` / `cfn ls` / `cfn query`) live in the Configuration docs: `mycelium docs troubleshooting`.

## Operator setup (not an agent task)

Install details, environment variables, multi-machine sync, and CFN ingest
configuration are operator concerns and live in the docs, not in this skill.
Run `mycelium docs troubleshooting` for configuration and environment variables,
and `mycelium docs architecture` for deployment modes and sync. As an agent you
act through the commands above; you do not configure the stack.

