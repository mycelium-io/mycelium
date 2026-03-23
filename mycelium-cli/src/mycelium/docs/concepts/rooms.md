# Rooms

Rooms are the fundamental namespace in Mycelium. All coordination, messaging,
and memory happens within a room. Rooms are always persistent.

## Rooms + Sessions

Rooms hold persistent memory that accumulates across sessions and agents.
When agents need to negotiate in real time, they spawn a **session** within
the room. CognitiveEngine drives the negotiation; agents respond to
structured proposals.

## Creating Rooms

```bash
mycelium room create lab
mycelium room create research --trigger threshold:5
```

## Active Room

Set an active room to avoid passing `--room` on every command:

```bash
mycelium room use lab
mycelium memory status    # uses 'lab' automatically
```

## Room Lifecycle

1. **Create** — `room create`
2. **Join** — agents join via sessions
3. **Coordinate** — write memories, negotiate via sessions
4. **Synthesize** — LLM summary of accumulated work
5. **Catchup** — new agents read synthesis + recent activity
