# Rooms

Rooms are the fundamental namespace in Mycelium. All coordination, messaging,
and memory happens within a room.

## Modes

| Mode     | Description                                    |
|----------|------------------------------------------------|
| **sync** | Real-time NegMAS negotiation (agents online)   |
| **async**| Persistent memory, synthesis on trigger         |
| **hybrid**| Both negotiation and persistent memory         |

## Creating Rooms

```bash
mycelium room create lab                              # sync (default)
mycelium room create research --mode async            # async + persistent
mycelium room create sprint --mode hybrid --persistent # hybrid
```

## Active Room

Set an active room to avoid passing `--room` on every command:

```bash
mycelium room set lab
mycelium memory status    # uses 'lab' automatically
```

## Room Lifecycle

1. **Create** — `room create`
2. **Join** — agents join via sessions
3. **Coordinate** — sync: negotiate; async: write memories
4. **Synthesize** — async/hybrid: LLM summary of accumulated work
5. **Catchup** — new agents read synthesis + recent activity
