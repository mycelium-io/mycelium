# Memory Service: Leaning In

*Late-night notes, 2026-03-18*

## The Real Problem

An agent helps a user build something over a long session — a cron job, a config,
a deployment script. The session ends. The user comes back the next day and says
"let's fix that thing we were working on." The agent has no idea what they're
talking about.

This is the pain. Not coordination between agents. Not negotiation protocols.
The pain is **continuity** — the feeling that your agent is your partner, not a
stranger you have to re-brief every morning.

## What We Already Have

Mycelium's memory system is surprisingly close to solving this:

- **Room-scoped persistent memories** with hierarchical keys (`project/status`,
  `decisions/arch`)
- **Semantic vector search** (384-dim embeddings, pgvector cosine similarity)
- **Versioning** — every memory tracks version, created_by, updated_by
- **Async synthesis** — LLM-powered summaries of accumulated memories
- **Catchup** — agents joining a room get briefed on current state
- **Subscriptions** — glob-pattern watches on memory changes
- **Real-time notifications** — Postgres NOTIFY piped through SSE

The primitives are all there. What's missing is the **workflow** that makes this
feel like continuity rather than a database.

## Idea: Memory as the Agent's Notebook

What if every agent session automatically had a place to write down what it did?
Not a log dump — a structured, searchable, synthesizable record.

### Memory Types (by convention, not schema)

Use key prefixes to create semantic layers:

```
work/              What the agent built or changed
  work/cron-setup     "Created crontab entry: */5 * * * * curl ..."
  work/monitoring     "Set up URL monitor for shop.example.com/queue"

decisions/         Why choices were made
  decisions/polling-interval  "Chose 5min interval because site rate-limits at 1req/min"
  decisions/notification      "User wants SMS via Twilio, not email"

context/           User preferences and background
  context/goal        "Get tickets to NYC pop-up shop before they sell out"
  context/constraints "Non-technical user, prefers simple explanations"

status/            Current state of ongoing work
  status/cron         "ACTIVE — last fired 2026-03-17T22:00Z, next at 22:05Z"
  status/result       "FAILED — 403 error, likely IP blocked"
```

No schema changes needed. This is just a convention on top of the existing
hierarchical key system.

### The Catchup Flow Gets Better

`mycelium memory catchup` already exists. But with structured keys, the
synthesis prompt can produce much better briefings:

> **What's set up:** A cron job polling shop.example.com/queue every 5 minutes.
> **Current status:** Last run failed with 403 (possible IP block).
> **Why it was built:** User wants to grab tickets to a NYC pop-up.
> **Open issue:** Need to rotate IPs or add proxy support.

That's the briefing an agent needs to pick up where it left off. The user says
"fix that cron thing" and the agent actually knows what they mean.

### CLI Commands (Implemented)

```bash
# memory set validates category keys automatically — no separate command needed
mycelium memory set work/cron-setup "Created crontab: */5 * * * * curl ..."
mycelium memory set status/cron "ACTIVE"
mycelium memory set custom/anything "Freeform — no category validation"

# What happened since I was last here?
mycelium memory catchup              # synthesis + recent activity

# What's the current state of everything?
mycelium memory status               # filters to status/* keys, shows table

# What did we decide and why?
mycelium memory decisions            # filters to decisions/* keys
```

### Synthesis Improvements

The existing synthesis service (`async_coordination.py`) already calls an LLM to
summarize accumulated memories. Two tweaks:

1. **Structure-aware synthesis** — group memories by prefix when building the
   LLM prompt. `work/*` memories inform "What's Built", `status/*` inform
   "Current State", etc.

2. **Delta synthesis** — instead of re-synthesizing everything, synthesize only
   what changed since last synthesis. The version tracking already supports this.

## How This Connects to Negotiation

This doesn't replace the semantic negotiation work. It strengthens it.

Right now, negotiation rooms (sync mode) are ephemeral — agents negotiate, reach
consensus, and the room's value is in the outcome. But with better memory
conventions, negotiation outcomes can be automatically persisted:

```
decisions/negotiation-2026-03-18   "Agents agreed on API schema v2"
context/negotiation-participants   ["agent-a", "agent-b", "agent-c"]
status/negotiation                 "COMPLETE — consensus reached"
```

The negotiation protocol produces the decisions. The memory layer preserves them.
Next time an agent asks "what did we agree on?", it's right there.

## What to Build Next

Roughly in priority order:

1. ~~**Memory conventions doc**~~ Done — CLI bundled docs + demo script updated.

2. ~~**Better catchup synthesis**~~ Done — synthesis groups by category prefix.

3. ~~**`mycelium memory status`**~~ Done — plus `work`, `decisions`, `context`.

4. ~~**Separate `log` command**~~ Killed — validation folded into `set`. One verb.
   Agents already know `set`/`get` from every KV store they've ever seen.

5. **Session-scoped auto-persist** — When a CLI session ends (`mycelium room leave`),
   optionally prompt for a summary memory. "What did you accomplish this session?"
   Store it under `work/session-{timestamp}`.

None of these require schema migrations. They're all conventions and CLI sugar
on top of what already exists.

## The Pitch

Mycelium isn't just how agents talk to each other. It's how agents remember.
The coordination layer (sync rooms, negotiation) handles the present. The memory
layer (async rooms, synthesis) handles the past and the future.

An agent that can negotiate AND remember is qualitatively different from one that
can only do one or the other. That's the product.
