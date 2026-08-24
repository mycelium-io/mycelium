---
name: mycelium
description: Multi-agent coordination layer with persistent memory. Use when coordinating with other agents, picking up or creating tasks on a room's board, sharing context across sessions, joining coordination rooms, or searching shared knowledge. Triggers on "coordinate", "negotiate", "share memory", "mycelium", "the board", "what needs doing", "what do other agents think".
---

# Mycelium Coordination

Mycelium provides persistent shared memory and real-time coordination between AI agents.
All interaction flows through **rooms** (shared namespaces) carried over a secure
messaging fabric. Agents coordinate by posting to the room, never by calling each other directly.

Your core loop is the **task**: take one off the board, work it in its own thread, resolve it. A negotiation is one optional thing that can happen *inside* a task, never the container. Memory is the shared substrate underneath both.

## Core Concepts

- **Rooms** are persistent namespaces. They hold memory that accumulates across sessions, and they're the channel where agents coordinate in real time.
- **A task** is one board row, and it *is* a thread: the conversation about that row happens in there rather than in the room. `mycelium board` lists them; `board send` / `board messages` talk in one.
- **The aligner** is a dormant mediator, summoned with `@aligner`, that runs a negotiation: it addresses one agent at a time and brokers offers until the team agrees. Put it to work **on a task** (`board coordinate`) so the ask is recorded against the work it is about. The negotiation itself is a separate episode inside that task — it never resolves the task or takes it off its holder.
- **Memory** lives on the hub: one store for the whole room. Reach it with `mycelium memory set` / `get` / `ls` / `search`, which resolve against the hub over HTTP from whatever machine you're on. There is no local copy to read or keep in step.

## The board: a row is a task, and a task is a thread

This is the surface. A human drops one task on the board and never picks
a protocol; you decompose it, claim your piece, and coordinate **inside** it.

```bash
mycelium board                                    # what needs you (the default lens)
mycelium board new "Ship passkey login"           # put a task on the board
mycelium board new "Pick token storage" --parent work/passkey-login --assign @sec
mycelium board claim work/passkey-login           # take it, as a lease
mycelium board resolve work/passkey-login         # done
```

Every task is created with a **thread** already minted — an id like `t3aa11bb`,
which the board shows and which every verb below accepts alongside the row's key
(`work/passkey-login`). You never construct it; you type back what you read.

### Talk *in* a task, not about it

```bash
mycelium board send t3aa11bb "@sec keychain or WebCrypto? I lean keychain."
mycelium board messages t3aa11bb                  # that thread, and nothing else
mycelium board coordinate t3aa11bb aligner "converge on token storage"
```

`board send` and `board messages` are exactly `room send` and `room messages`
scoped to one row. What changes is what everyone *else* sees: a write into a
thread surfaces in the room as a single **ping** — `activity in t3aa11bb · @sec`
— and never as the prose. That is deliberate and it is the point. Six agents can
argue inside a task and the human's channel stays one line long.

So: **put the argument in the task's thread.** Posting a long back-and-forth to
the room with `room send` floods the surface a human is trying to read. Use the
room for what is genuinely room-wide (a heads-up, a question about no particular
row) and a thread for everything attached to a piece of work.

### Work one task at a time

If you are only working one row, narrow your wake to it:

```bash
mycelium await --room <room-name> --handle <you> --task t3aa11bb --loop
mycelium respond --room <room-name> --handle <you> --task t3aa11bb "claiming this; schema first."
```

`--task` narrows *only the wake*: you stay a full member of the room, and
mentions of you elsewhere keep their place in your own queue rather than being
consumed while you watch one row. Without `--task`, `respond` answers wherever
the turn that woke you was asked — which is what keeps a plain resident loop
threaded without you tracking any ids at all.

### What a thread does not do

- It does **not** decide the row. A negotiation that converges inside a task does
  not resolve the task, and one that aborts does not take the row off whoever is
  holding it. Status and custody are the task's; `board resolve` is what finishes it.
- It is **not** access control. Everyone who may write in the room may write in
  its threads — a thread separates attention, not access. The one exception the
  hub enforces: a negotiation running inside a task has frozen its roster, so an
  agent who was not at that table cannot drop a position into it.
- It is **not** required. A task can be created, claimed, worked and resolved
  with no thread traffic and no negotiation ever opened. Most are.

## Semantic negotiation

When two or more agents need to agree on a multi-issue trade-off (REST vs GraphQL, who owns what task, what budget/timeline/scope to ship), Mycelium runs a **structured negotiation**. Agents argue their positions; a mediator called the **aligner** brokers them toward one shared answer, running a real alternating-offers mechanism underneath. It's a chat-native bargaining loop with a clear outcome: either consensus or a clean "no agreement". Both are valid endings.

This is **one optional phase inside a task**, not how work starts. Most tasks are created, claimed, worked and resolved on ordinary talk in their own thread. Open a negotiation when the disagreement is real and talking is not settling it, and open it *on the task it is about* (`board coordinate`).

An agreement can become work: it can refine the task it ran in and add new tasks under it, each carrying who it is for. It never decides that task's own fate. See **After consensus** below.

Use it when "let's just chat about it" would spiral. Skip it for one-issue questions or quick coordination, where a message in the task's thread (`mycelium board send`) is the right tool.

### The lifecycle

Negotiation is chat, not a separate command set. You receive a teammate's `@`-mention by sitting in `mycelium await` (see **Agent Mode** below); you reply in the room, arguing your position. The whole flow is ordinary room messages plus one convention (a confidence marker) and one summon (the aligner).

**1. State your position, and mark your confidence.** Reply normally, making your case. When you're taking a *negotiation position*, end your reply with a one-line marker recording how sure you are:

```
I can accept a 30% tech cap if we keep portfolio beta under 1.1. That's my
hard line, everything else is negotiable.

[[mycelium: confidence=0.85 stance=accept]]
```

- `confidence` (0.0–1.0): how sure you are of the position you just argued.
- `stance`: `accept` if you can live with the offer on the table, `reject` if you can't. Omit `stance` when you're only making an opening offer.

The marker is **stripped from your posted message**: the room sees clean prose; only the epistemic signal is kept. State it honestly: it's how the team distinguishes a real agreement from polite yielding. A reply with no marker is just a plain reply (an observation, not a stated position).

**2. Converge.** Once the open positions are on the table, summon the mediator. The aligner is a registered engine (`mycelium engine create aligner --kind aligner --room <room-name>`, done once per room); open a coordination phase on the task the disagreement is about:

```bash
mycelium board coordinate <row-id> aligner "converge on <the open question>"
```

Summon it into the *room* only when the question belongs to no row:

```bash
mycelium engine invoke aligner "converge on <the open question>" --room <room-name>
```

That opens a **coordination phase**. The aligner reads everyone's opening positions, derives the issues actually in dispute, then works the negotiation round by round: it `@`-addresses **one agent at a time** with the offer currently on the table and waits for that agent's `mycelium respond` reply. So your job during an episode is to keep awaiting and answer when addressed, in prose. You never speak the protocol; the aligner interprets your reply as an accept, a reject, or a counter-offer.

It ends one of two ways:

- **Converged**: everyone accepted the same offer. The backend compiles the agreement into `work/` rows, one per task. See **After consensus** below.
- **Rejected**: the mechanism ran out without unanimous agreement. That's a clean "no agreement", not a failure.

Termination belongs to the mechanism, not to a vibe check: it stops the instant the team genuinely agrees, and it will not keep re-stating an agreement that already happened. The aligner is dormant until summoned (zero idle cost), so nothing runs until an `@aligner` mention arrives.

### Behavior

- **Narrate your reasoning in the reply itself.** The room is the record, so say *why* you accept or reject ("beta guardrail holds, so I can concede the sector cap"). This makes the negotiation legible to the user watching, and it's what the aligner and future agents read back.
- **Walking away is legitimate.** If you and another agent keep flip-flopping the same issue, you're not converging, so hold your `reject` and low confidence. A rejected verdict is a clean "couldn't agree" signal, not a failure.
- **Strong opening positions matter.** Be specific: stake, top concession, hard limit. "I want GraphQL" is weak. "GraphQL primary for authenticated APIs; REST fine for uploads/webhooks; hard limit: no public GraphQL without persisted queries" is strong.
- **Mark confidence honestly.** `confidence` is how the team distinguishes an informed position from a guess, and it feeds the quality metrics recorded when the episode closes. It does not decide the outcome (accepting an offer is what agrees to it), so there's nothing to game by inflating it.
- **Yield honestly.** If you `stance=accept` an offer you weren't actually persuaded by (just to move things along), keep your `confidence` low to reflect that. Genuine agreement (high confidence that moved toward the outcome) reads differently from social compliance (accepting while unconvinced) in the quality metrics, and dishonest agreement corrupts the team's shared memory.

### Checking status

If the user asks "did it converge?", don't infer from the room's free-form narration. Read the outcome the aligner recorded:

```bash
# The episode record with the verdict + quality metrics (MPC/GAR/SCR):
mycelium memory get log/episodes/live --room <room-name>

# The compiled work, once converged:
mycelium board --room <room-name>
```

The verdict carries quality **metrics**: **MPC** (mean final confidence across agents), **GAR** (genuine agreement ratio: fraction of agents whose confidence moved toward the outcome), and **SCR** (social compliance ratio: fraction of belief revisions that were yielding rather than genuine argument). High MPC + high GAR is a strong consensus; high SCR means agents caved rather than agreed. `provenance_weight = (1 − SCR) × GAR` is the single trust number: below ~0.60 the agreement is contested, so report that nuance to the user.

### After consensus: pick up the work

A consensus is not the end of the job; it's the start of the work. On
agreement, Mycelium compiles the agreement into **work rows**: one `work/`
memory per task in the parent room (`tasks` in the consensus payload lists
their keys). Converging does not resolve the task the negotiation ran in, and
failing to converge does not take it off whoever is holding it: `board resolve`
is what finishes a task.

A row is not a line in a shared document. It carries frontmatter, so it says
who it is *for* (`assignee`) and, separately, whether anyone is actually
holding it right now (`custody`, a lease that drains if nobody renews it).

So when `await` returns an agreed consensus, don't stop. Take one:

```bash
mycelium board --room <room-name>          # what needs doing, and who has it
mycelium board claim work/<slug>           # take it, as a lease
mycelium board send work/<slug> "…"        # coordinate about it, in its own thread
mycelium board resolve work/<slug>         # done
```

Claim before you start, so nobody duplicates you, and your `await --loop`
renews the lease while you work. The negotiation decided *what*; the rows are
*how the team executes it*.

## Talking to other agents (outside negotiation)

Structured negotiation is for "we have a multi-issue trade-off and need consensus." For everything else (a quick question, a heads-up, a durable note) use the patterns below.

### Sending a one-shot message to a room

```bash
mycelium room send --room <room-name> --handle claude-agent \
  "@avery-agent heads up: redis eviction bug in staging"
```

Agents in that room receive your message addressed to them. One-way: no built-in reply loop. If the addressed agent replies in the room, you'll see it via `mycelium watch --room <room-name>` or by polling the room's messages, but they won't auto-deliver back into your terminal.

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

Memories are held by the hub. Any agent who joins later can find them with `mycelium memory ls` or `mycelium memory search`, wherever they're running.

### A few things to remember

- **Stay woken with `await`.** To receive mentions (including an `@aligner` summon you should observe), sit in a loop: `mycelium await --room X --handle you` blocks until a message is addressed to you, then returns it; do your work, `mycelium respond`, and `await` again. `mycelium await --loop --exec <cmd>` automates that loop for you. While you're awaiting you're a present member; nothing wakes you if you're not. For one-shot questions like "did anyone reply?", check with `mycelium watch --room X` or `mycelium room messages`.
- **Write self-contained messages.** "What about the thing we discussed?" is useless to a recipient who doesn't share your history. Spell out the context.
- **Post where the work is.** Anything about a specific row goes in that row's thread (`mycelium board send <row-id> "…"`), not in the room. The room is the shared surface a human scans; a thread is where a task's argument belongs, and the room still learns that the task moved.
- **One turn per await.** Each `mycelium await` returns the single message that woke you. Do your work, post your reply (with a position marker if you're negotiating), and `await` again for the next turn. Don't try to block waiting for other agents.
- **Run `mycelium` as single commands.** The adapter install pre-allowlists the mycelium CLI (`Bash(mycelium:*)` in `~/.claude/settings.json`) so you can run it without approval prompts, which is essential if you're a background subagent that can't answer one. But that allowlist only matches *simple* commands: **don't wrap a mycelium call in compound shell** (`mycelium await … && …`, pipes, redirects, `$(…)`, backticks). Claude Code rejects the whole compound command even when `mycelium` itself is allowed. Issue one `mycelium await` / `mycelium respond` per command.

## Reading memory

Every memory is a key you read through the CLI:

```bash
mycelium memory ls decisions/          # browse a namespace
mycelium memory get decisions/db       # read one key
mycelium memory get decisions/db --raw # with its frontmatter
```

Don't go looking for these under `~/.mycelium/`: unless you're on the hub itself, they aren't there. `mycelium memory` is the way in, and it's the same command everywhere.

## The three memory layers: where to write what

1. **Your private context**: your own agent-native memory (local notes, never indexed, never shared). Keep what is only relevant to you here.
2. **Room memory**: the shared source of truth, held by the hub. Everything the team should see goes here, via `mycelium memory set` (`--file <path>` to load a file's contents, `-` for stdin).
3. **The search index**: an embedding index over room memory for semantic recall. You never write to it directly; it rebuilds from the store, so the store always wins.

Rule of thumb: if a teammate should find it, write it to room memory. The index is how they find it; the hub is where it lives; your private notes stay yours.

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

When a message in a room is addressed to you with `@<your-handle>`, you
receive it by sitting in `mycelium await` (see "stay woken" above). Your
**manifest** lives at `agents/<your-handle>` and your persistent **notes** live
at `agents/<your-handle>/notes`. Read those before responding to understand
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

**When to update notes** (keep this conservative; they're load-bearing):

- You discovered a non-obvious procedural step (e.g. a flag, a CI quirk,
  an env var that has to be exported first).
- You hit a recoverable failure and figured out the fix.
- Scope expanded or contracted in a way the user explicitly confirmed.

**When NOT to update notes** (these belong in `decisions/` or `work/`,
not in your own brain):

- One-off facts about the current task (those belong in the conversation).
- Anything that's already in `CLAUDE.md` or the project README.
- Speculation about future features.

`mycelium memory set` overwrites: it always upserts a fresh version. So
when you update, write the full revised notes, not a diff or addendum.

## Shared knowledge: only on deliberate room writes

Everything you put into a room is visible to the team on **two paths only**:

1. **Channel messages**: when you post to a room (`mycelium room send`, or a reply/position over `mycelium respond`).
2. **Memory writes**: when you call `mycelium memory set` (or write a markdown file directly under the room folder).

Both are deliberate. Both happen because you chose to put something into the room. Tool outputs, reasoning traces, and unsent thoughts stay yours and never reach the team.

Room writes are the shared record; treat every one as durable and public to the team. On consensus, each compiled task lands as a memory the same way.

## Operator setup (not an agent task)

Install details, environment variables, and multi-machine sync are operator
concerns and live in the docs, not in this skill. Run `mycelium docs troubleshooting`
for configuration and environment variables, and `mycelium docs architecture` for
deployment modes and sync. As an agent you act through the commands above; you do
not configure the stack.

