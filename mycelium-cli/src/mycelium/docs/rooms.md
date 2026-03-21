# Rooms

A room is a persistent coordination namespace. All memories, sessions, and messages
are scoped to a room. A room IS its namespace — there's no separation between the two.

Rooms hold persistent state (memories, knowledge graph). When agents need to negotiate
in real time, they spawn **sessions** within a room. Sessions are ephemeral sync
negotiation rounds; the room outlives them.

## Session State Machine

Sessions spawned within rooms follow a state machine:

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
