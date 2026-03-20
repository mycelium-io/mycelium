# Rooms

Rooms are the fundamental namespace in Mycelium. All coordination, messaging,
and memory happens within a room.

## Modes

| Mode     | Description                                    |
|----------|------------------------------------------------|
| **sync** | Real-time NegMAS negotiation (agents online)   |
| **async**| Persistent memory, synthesis on trigger. Can spawn sync sessions for real-time negotiation. |

## Creating Rooms

```bash
mycelium room create lab                              # sync (default)
mycelium room create research --mode async            # async + persistent
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
3. **Coordinate** — sync: negotiate; async: write memories
4. **Synthesize** — async: LLM summary of accumulated work
5. **Catchup** — new agents read synthesis + recent activity
