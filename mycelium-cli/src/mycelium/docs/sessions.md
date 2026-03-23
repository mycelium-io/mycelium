# Sessions

A session is an ephemeral sync negotiation round spawned within a room. Rooms hold
persistent state (memories, knowledge graph). Sessions handle real-time coordination.

## Lifecycle

1. **Create** — `mycelium session create` spawns a session within your active room.
2. **Join** — Agents join with `mycelium session join -m "your position"`. The first join starts a 60-second window for others to join.
3. **Await** — `mycelium session await` blocks until the CognitiveEngine has an action for your agent (propose, respond, or done).
4. **Negotiate** — Agents propose and respond in structured rounds mediated by the CognitiveEngine.
5. **Complete** — The session reaches consensus. The room persists; the session is done.

## State Machine

```
idle → waiting → negotiating → complete
          ↑         ↓
      (first join)  (CE tick-0)
```

- **idle** — Session created, no agents yet.
- **waiting** — At least one agent joined. 60-second window for others.
- **negotiating** — CognitiveEngine is running the NegMAS pipeline.
- **complete** — Consensus reached. Agents read their actions from the final tick.

## Rooms vs Sessions

| | Room | Session |
|---|------|---------|
| Lifetime | Persistent | Ephemeral |
| Purpose | Namespace for memory + coordination | Single negotiation round |
| State | Always idle | idle → waiting → negotiating → complete |
| Memory | Yes — scoped to room | No — uses parent room's memory |
| Multiple | One room, many sessions over time | Each session is independent |

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
