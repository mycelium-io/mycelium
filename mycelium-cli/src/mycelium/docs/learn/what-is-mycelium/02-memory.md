# Memory, not personality

Memory persists in Mycelium. That's not to make an agent someone. It's to make
the next worker faster and less often wrong. Memory comes in three kinds:

| | What it holds | Where it lives |
|---|---|---|
| **Preferences** | How this team wants things done and the calls it has already made | `decisions/` |
| **Behaviours** | What worked, what failed and what to watch for next time | `failed/`, `context/` |
| **Procedures** | Skills a fresh worker picks up the moment it arrives | `skills/`, `procedures/` |

Each is a markdown file in the room that can be searched by meaning:

```bash
mycelium memory search "how do we store sessions"
```

A worker that arrives cold reads them and is useful at once.
