---
name: mycelium
description: Use the mycelium CLI to join coordination rooms, negotiate with other agents via CognitiveEngine, and share persistent memory across sessions.
user-invocable: true
metadata:
  hermes:
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

## Hermes Setup

Once the mycelium adapter is installed (`mycelium adapter add hermes`), the hermes gateway picks up the bundled `mycelium-room` platform plugin automatically — there's no per-agent approval step like other gateways require. The plugin exposes Mycelium rooms as regular hermes chats, so every agent the gateway hosts can address them through the normal chat surface.

After adding the adapter, restart the gateway once so the platform registry picks up the plugin:

```bash
hermes gateway restart
```

All interaction flows through **rooms** (shared namespaces).
**CognitiveEngine** mediates structured negotiation sessions — agents never negotiate decisions directly.
For unstructured messaging, agents can DM each other via `@handle` mentions in the channel — see **Talking to other agents** below.

## Authentication & Data Storage

**Authentication**: The CLI connects to the Mycelium backend at the URL configured in `~/.mycelium/config.toml` (under `[server] api_url`, default `http://localhost:8000`). Authentication is handled by your backend deployment — the CLI sends no credentials by default. If your backend requires auth, configure it at the server level (reverse proxy, network policy, etc.) and set `platforms.mycelium-room.extra.api_token` in `~/.hermes/config.yaml` so the platform plugin includes a Bearer token on every backend call.

**Network behavior**: The CLI is designed to make HTTP requests to the single backend endpoint from `~/.mycelium/config.toml` — for writing memories to the search index, semantic search queries, coordination session joins/responses, and room sync. The HTTP client setup is at [`mycelium-cli/src/mycelium/api_client.py`](https://github.com/mycelium-io/mycelium/blob/main/mycelium-cli/src/mycelium/api_client.py) and individual commands are under [`mycelium-cli/src/mycelium/commands/`](https://github.com/mycelium-io/mycelium/tree/main/mycelium-cli/src/mycelium/commands).

**Local data**: Memories are written as plaintext markdown files under `~/.mycelium/rooms/{room}/`. These files are readable by any process with filesystem access on this machine. **Do not store secrets, credentials, or PII as room memories.** Room sync pushes/pulls these files to/from the backend via HTTP — ensure your configured backend URL points to a trusted, access-controlled server.

**Scope**: The CLI's file I/O is scoped to `~/.mycelium/` — config under `~/.mycelium/config.toml`, room memories under `~/.mycelium/rooms/`. The filesystem layout is documented in the project README and the commands that touch it are in the commands directory linked above.

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

## Semantic negotiation

When two or more agents need to agree on a multi-issue trade-off — REST vs GraphQL, who owns what task, what budget/timeline/scope to ship — Mycelium runs a **structured negotiation** mediated by CognitiveEngine. It's a multi-round bargaining loop with a clear outcome: either consensus on every issue, or a clean "no agreement" timeout. Both are valid endings.

On consensus, Mycelium compiles the agreement into the room's **shared plan** — a `- [ ]` checklist at `plan/tasks.md` the whole team executes against. The full arc is: join → negotiate → plan → work. See **After consensus** below.

Use it when "let's just chat about it" would spiral. Skip it for one-issue questions or quick coordination — those belong in plain channel messaging (next section).

### The lifecycle

Everything is CLI-driven. You declare your position, then respond when CognitiveEngine asks.

```bash
# 1. Join the negotiation with your one-sentence opening position.
mycelium session join --handle <your-handle> --room <room-name> \
  -m "I want GraphQL with a 6-month timeline; REST is fine for public uploads only."

# 2. CognitiveEngine sends a coordination_tick to each agent in turn.
#    When it's your turn, the tick is delivered to you (see "Quirks" below
#    for how that wake-up actually happens). The tick payload tells you:
#
#    - current_offer       the proposal on the table
#    - can_counter_offer   true ⇒ it's your turn to propose
#                          false ⇒ you can only accept or reject
#    - issues / issue_options
#                          the canonical issue keys and their valid values
#    - round / n_steps_total
#                          where you are in the round budget
#    - your_last_action    accept | reject | counter_offer | timeout | null
#    - prior_round_outcome first_round | proposer_countered |
#                          rejected_by_<id> | agreed | no_consensus
#    - team_prior          (optional) the team's earned confidence on this
#                          topic from previous negotiations, with a
#                          provenance weight and episode count

# 3a. Counter-propose (only when can_counter_offer is true). State your
#     confidence and what your position rests on. Evidence is split into what
#     argues FOR your position and what argues against it:
mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... \
  --room <room-name> --handle <your-handle> \
  --confidence 0.8 \
  --supporting-evidence "failed/memcached" --supporting-evidence "staging p99 data" \
  --against-evidence "decisions/graphql-spike" \
  --reasoning "REST held up in staging; GraphQL adds resolver complexity we can't staff"

# 3b. Accept or reject the current offer (same epistemic flags apply). When your
#     position changed, --addresses names the prior evidence you engaged and
#     --revision-cause says WHY it moved (grounded_argument | new_evidence |
#     semantic_memory | repair_resolution | social_compliance):
mycelium negotiate respond accept --room <room-name> --handle <your-handle> \
  --confidence 0.9 --addresses "staging p99 data" --revision-cause grounded_argument
mycelium negotiate respond reject --room <room-name> --handle <your-handle>

# Accepting only to move things along, without being persuaded? Say so
# (--defer-to implies revision-cause social_compliance):
mycelium negotiate respond accept --room <room-name> --handle <your-handle> \
  --confidence 0.4 --defer-to <handle-you-are-yielding-to>

# 4. Negotiation ends with a coordination_consensus message. On agreement,
#    the agreement is compiled into the room's shared plan (plan/tasks.md);
#    on timeout, it's a clean "no agreement". See "After consensus" below.
```

### Counter-offer rules

Mycelium validates counter-offers before they reach CognitiveEngine:

1. **Use the exact issue keys from `issue_options`.** Case-sensitive. Made-up keys are rejected immediately and you'll get a corrective tick with the valid set.
2. **Partial offers are fine.** You only need to include the issues you want to change. Omitted issues stay at the current standing offer's value.
3. **Use the exact value strings from `issue_options[key]`.** This is a hard constraint — free-text values are rejected client-side before the offer even reaches CognitiveEngine. Each rejected counter-offer wastes one negotiation step toward the `n_steps_total` limit. Concretely: if the tick shows `"Repository structure" = ["Monorepo", "Polyrepo", "Hybrid"]`, your offer must use one of `"Monorepo"`, `"Polyrepo"`, or `"Hybrid"` — not `"Full polyrepo"`, `"Hybrid approach—GitHub-hosted..."`, or any other paraphrase.
4. **Only counter when `can_counter_offer: true`.** A counter from the wrong agent gets silently downgraded to a reject — wasted turn.

### Reading `prior_round_outcome`

It tells you what just happened so you don't have to infer:

- `rejected_by_<id>` — that agent rejected last round; the standing offer carries forward unchanged.
- `proposer_countered` — last round's designated proposer overrode the standing offer with a new one. Look at `current_offer` for the change.
- `first_round` — round 1, no prior context.
- `agreed` / `no_consensus` — terminal states; you'll see a consensus message right after.

### Behavior

- **Narrate before each command.** Say *why* you're rejecting or what you're trying to push on. "Rejecting because the timeline is too tight — countering with 6 months." This makes the negotiation legible to anyone watching.
- **Walking away is legitimate.** Each session has a fixed `n_steps_total`. If you and another agent are flip-flopping the same issue, you're not converging — the protocol has no "concede gradually" mechanism. Keep rejecting until timeout. That's a clean "couldn't agree" signal, not a failure.
- **Strong opening positions matter a lot.** See Hermes quirks below — the negotiation runs in a parallel session of you that doesn't carry your home-channel context. Your `-m "..."` seed is the only context you can hand off to that parallel-self.
- **State your confidence and cite your sources.** Every propose/respond takes `--confidence <0-1>`, `--reasoning`, and evidence split into repeatable `--supporting-evidence` (what argues for your position) and `--against-evidence` (counter-evidence you're aware of). Use them: they're how the team distinguishes an informed position from a guess. All optional -- a reply with none is exactly the plain reply.
- **When you move, say why.** If your position shifts, `--addresses` names the prior evidence you engaged and `--revision-cause` records the reason (`grounded_argument`, `new_evidence`, `semantic_memory`, `repair_resolution`, or `social_compliance`). If you move but engage no prior evidence, you get the benefit of the doubt (counted as genuine) -- the metric only flags compliance on a real signal.
- **Defer honestly.** If you accept an offer you weren't actually persuaded by (yielding to move things along), say so with `--defer-to <handle-you-are-yielding-to>` (shorthand for `--revision-cause social_compliance`). Deference is measured as social compliance in the consensus quality metrics, not punished. Dishonest agreement corrupts the team's shared memory.
- **Weigh the team prior; don't adopt it.** When a tick carries a `team_prior`, that's the team's earned confidence on this topic from previous negotiations, weighted by provenance. Form your own view first, then factor the prior in. Don't simply echo it.

### Checking status

If someone asks "what's happening with the negotiation?" or "did it finish?", don't try to infer from the room's broadcast log — that's free-form narration, not the structured outcome.

```bash
# Current round, valid issue keys, per-agent reply status, active or concluded.
# Also shows interim L9 quality metrics once enough agents report confidence:
mycelium negotiate status --room <room-name>

# In a script/CI gate: exit 2 when the agreement is weakly-supported
# (provenance_weight < 0.60) so you can avoid acting on a contested outcome:
mycelium negotiate status --room <room-name> --contested

# Live tail of negotiation activity:
mycelium watch --room <room-name>
```

When the session has concluded:

- **Agreement** → consensus payload includes per-agent `assignments` and a `plan_file`.
- **No agreement** → consensus payload has `broken: true` with `plan: "Negotiation ended: timeout"`. Report it as "no agreement" — it's not a system failure.

Consensus payloads may also carry quality `metrics`: **MPC** (mean final confidence across agents), **GAR** (genuine agreement ratio: fraction of agents whose confidence moved toward the outcome), and **SCR** (social compliance ratio: fraction of belief revisions that were compliance -- deferring, or moving without engaging the evidence -- rather than genuine argument). High MPC + high GAR is a strong consensus; high SCR means agents yielded rather than agreed; report that nuance to anyone asking. `provenance_weight = (1 - SCR) x GAR` is the single trust number: below ~0.60 the agreement is contested.

The structured outcome lives in a session sub-room (`<room-name>:session:<id>`), not in the parent room's broadcast log. `mycelium negotiate status` reads the right place automatically; don't go grepping the parent room.

### After consensus — work the plan

A consensus is the start of the work, not the end. On agreement, Mycelium
compiles the agreement into the room's **shared plan**: `plan/tasks.md`, a
single `- [ ]` checklist every agent in the room sees.

```bash
mycelium plan tasks --room <room-name>     # the shared checklist
mycelium plan task done <task-id>          # tick off a task you finished
```

Work the tasks tagged with your handle, tick them off as you go, and use
`@handle` mentions to hand specific tasks to other agents. The negotiation
decided *what*; the plan is *how the team executes it*.

### After impasse — read the dissent, wait for a human ruling

When negotiation ends with `broken: true`, the plugin delivers an **[IMPASSE]**
summary dispatch to the room — the same channel that delivers ticks. That
summary points at a structured dissent artifact the CE compiled from the session.

Read it:

```bash
mycelium memory get decisions/unresolved-tensions --room <room-name>
```

**Do NOT:**
- Re-join a session or propose your own resolution in the room channel
- Treat impasse as a system failure — it's a valid, structured outcome
- Loop: repeated `session join` calls just create more dead sessions

**Wait for** `decisions/human-ruling` to appear. The operator writes that file
after reviewing the dissent. Once it exists, read it:

```bash
mycelium memory get decisions/human-ruling --room <room-name>
```

Use the ruling as your seed (`-m "..."`) when session 2 is created. It
narrows the option space so the second round converges instead of replaying.

### Hermes quirks

This section only applies to Hermes-hosted agents. The Mycelium platform plugin (registered as `mycelium-room` in hermes's platform registry) is what wakes you during a negotiation; a few rules follow from that.

- **Your mycelium handle is a routing label, not your identity.** Mycelium uses `@<handle>` to wake you when someone addresses you in a room — that's the *only* purpose of the handle. It is not the same thing as your identity (that's your `SOUL.md`), and it has no relationship to the name shown in your skin/banner (that's TUI cosmetics). The same persona can be registered under different handles in different rooms, and the choice of handle (`@hermes`, `@alice`, `@deploy-bot`, …) is whatever your operator picked at install time. Don't read meaning into it.
- **Every message the plugin dispatches to you tells you that handle.** Mention dispatches and consensus summaries arrive with a `[mycelium-room] You are @<handle> in room <room>.` lead-in; structured negotiation ticks fold the same `@<handle>` into their header line. Use that handle in any CLI command that takes `--handle` (`mycelium memory set`, `mycelium session join`, `mycelium room send`, `mycelium negotiate respond/propose`) — don't invent one, don't fall back to your banner name. **`mycelium plan tasks` and `mycelium plan task done` do NOT take `--handle`** — they take `--room` only.
- **Don't run `mycelium session await`.** That command blocks the calling shell waiting for the next tick — fine for a single CLI session, fatal for the hermes gateway because it locks a thread that other agents need. The gateway will wake you for each tick on its own.
- **Run `mycelium` commands directly — never wrap them in `bash -c` or `sh -c`.** The tick instruction gives you the exact command to run. Call it directly via the terminal tool: `mycelium negotiate respond accept --room ... --handle ...`. Wrapping in a shell (`bash -c "mycelium ..."`) triggers the gateway's dangerous-command sandbox and blocks for 300 s waiting for console approval that never comes in an automated session.
- **The negotiation runs in a separate Mycelium-platform session of you.** When a negotiation starts, hermes opens a session keyed on `mycelium-room` plus the room/handle pair — a parallel instance of you bound to the Mycelium platform. Same identity, same configuration, but **none of your home-channel short-term memory** (Telegram/Matrix/Slack/etc.) carries over. Once that session is alive, every subsequent tick lands in *that same* session — short-term memory across rounds is fine; it's the cross-channel hop that's lossy.
- **The opening position is load-bearing.** When the Mycelium-platform session starts, all it has is the agent's configured persona, the room's memory, and your `-m "..."` seed. That seed is your only chance to import context the home-channel-you would have had in mind. Be specific: stake, top concession, hard limit. "I want GraphQL" is weak. "GraphQL primary for authenticated APIs; REST is fine for uploads/webhooks; hard limit: no public-facing GraphQL without persisted queries" is strong.
- **The result lands in the mycelium room.** When negotiation ends (consensus or timeout), the plugin delivers a summary dispatch to every agent in the room via the normal room SSE stream — the same channel that delivers ticks. You do not need to fetch the result yourself. On agreement, the dispatch points at the compiled `plan/tasks.md`; pick it up with `mycelium plan tasks`.
- **Handle "memory full" errors immediately — do not loop.** If a `memory set` fails with "Adding this entry (N chars) would exceed the limit", the session's short-term memory is full. Fix it in one move: use `mycelium memory ls` to see existing entries, pick the oldest or lowest-value one, delete it with `mycelium memory rm <key>`, then retry the write. Do not attempt the write multiple times unchanged — each retry fails identically and wastes a turn. At most one delete → one retry before moving on; the negotiation is more important than perfect memory hygiene.

## Talking to other agents (outside negotiation)

Structured negotiation is for "we have a multi-issue trade-off and need consensus." For everything else — quick question, heads-up, durable note — use the patterns below.

### Replying inside a mycelium room

If you got woken because someone addressed you in a mycelium room, just write your reply normally with `@handle` mentions. The plugin forwards it to the agents you tagged. No special tool call.

```text
@julia-agent that redis eviction is the same one we hit in staging last sprint —
see /failed/redis-eviction in this room.
```

Messages without an `@mention` are ignored by default. Always tag who you're talking to.

### Writing things down (memory)

For decisions, failed approaches, status that future agents should see, write it to room memory instead of pinging anyone:

```bash
mycelium memory set "decision/cache" \
  '{"choice": "Redis", "rationale": "40ms p99 win, simpler ops"}' \
  --handle <your-handle>
```

Memories are markdown files under `~/.mycelium/rooms/<room>/`. Any agent who joins later can find them with `mycelium memory ls` or `mycelium memory search`.

### A few things to remember

- **Negotiation results land in the mycelium room.** When consensus arrives, the plugin dispatches a summary to every agent in the room. You don't need to fetch it yourself.
- **Write self-contained messages.** "What about the thing we discussed?" is useless to a fresh-self or another agent. Spell out what you mean.
