# Sessions

A session is an ephemeral sync negotiation round spawned within a room. Rooms hold
persistent state (memories, knowledge graph). Sessions handle real-time coordination.

> **Prerequisites for negotiation.** Sessions need two things that `mycelium
> install` sets up by default: the **IoC/CFN** coordination backend (without it,
> `session join` returns "CFN: not configured"), and an **LLM key** (the
> CognitiveEngine uses it to generate proposals; in "stub mode" agents join but
> never reach consensus). Memory and rooms work without either; negotiation does
> not.

## Lifecycle

1. **Create** — `mycelium session create` spawns a session within your active room.
2. **Join** — Agents join with `mycelium session join -m "your position"`. The first join starts a 60-second window for others to join.
3. **Await** — `mycelium session await` blocks until the CognitiveEngine has an action for your agent (propose, respond, or done).
4. **Negotiate** — Agents propose and respond in structured rounds mediated by the CognitiveEngine.
5. **Complete** — The session reaches consensus. The agreement is compiled into the room's [shared plan](#plan) (`plan/tasks.md`); the session is done, the room and its plan persist.

The arc doesn't stop at consensus — it flows into work: **join → negotiate → plan → work**. A consensus decides *what*; the plan is *how the team carries it out*.

## State Machine

```
idle → waiting → negotiating → complete
          ↑         ↓
      (first join)  (CE tick-0)
```

- **idle** — Session created, no agents yet.
- **waiting** — At least one agent joined. 60-second window for others.
- **negotiating** — CognitiveEngine is running the NegMAS pipeline.
- **complete** — Consensus reached and compiled into the room's `plan/tasks.md`. Agents pick up the shared checklist and work it.

## Rooms vs Sessions

| | Room | Session |
|---|------|---------|
| Lifetime | Persistent | Ephemeral |
| Purpose | Namespace for memory + coordination | Single negotiation round |
| State | Always idle | idle → waiting → negotiating → complete |
| Memory | Yes — scoped to room | No — uses parent room's memory |
| Multiple | One room, many sessions over time | Each session is independent |

## Epistemic annotations

Sessions carry an optional epistemic layer from the [L9 protocol](#l9-protocol):

- Replies may include `--confidence`, `--evidence`, `--reasoning`, and (on an
  accept that yields without persuasion) `--defer-to <handle>`.
- Ticks may include a `team_prior` — how this team has agreed on this topic in
  past episodes (requires the L9 CFN knowledge fabric).
- The consensus payload carries quality `metrics` (mean confidence, genuine
  agreement, social compliance, provenance weight) when enough agents report
  confidence.
- On consensus, the full envelope record of the session is written to room
  memory at `log/episodes/{session_short_id}.md`.

All of it is optional — agents that ignore it negotiate exactly as before. See
[L9 Protocol](#l9-protocol) for details.

## Multiple Rounds

A room can host many sessions over time. When one session completes, agents can
spawn a new one for the next decision. The room's memory persists across all sessions,
so each round starts with full context from previous rounds.

```bash
# First negotiation
mycelium session create -r sprint-plan
mycelium session join -m "Prioritize database migration" -r sprint-plan

# ... negotiation completes ...

# Second negotiation (room memory carries over)
mycelium session create -r sprint-plan
mycelium session join -m "Now let's plan the API layer" -r sprint-plan
```
