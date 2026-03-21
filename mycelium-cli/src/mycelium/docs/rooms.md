# Rooms

A room is a coordination namespace. All memories, sessions, and messages are scoped
to a room. A room IS its namespace — there's no separation between the two.

| Mode | When to use | How it works |
|------|-------------|--------------|
| `async` (persistent) | Agents contribute across sessions, no need to be online together | Persistent namespace; CognitiveEngine synthesizes when a trigger fires (e.g. `threshold:5`) |
| `sync` (real-time) | Agents are online together and need to reach agreement now | 60s join window → NegMAS negotiation pipeline → structured consensus |
| `hybrid` (both) | Accumulate shared context first, then escalate to live negotiation | Write memories freely, then trigger a sync round when ready to decide |

## Room State Machine

Sync rooms follow a state machine:

```
idle → waiting → negotiating → complete
          ↑         ↓
      (join window fires)
```

Once `complete`, the room holds the consensus output. Agents read their
assigned actions from the final tick returned by `room await`.

## Triggers

Async rooms synthesize when a trigger fires:

| Trigger | Fires when |
|---------|------------|
| `threshold:N` | N memories have been written to the room |
| `manual` | You call `mycelium synthesize` explicitly |
