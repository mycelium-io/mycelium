# Memory

Mycelium memories are persistent, room-scoped key-value pairs with optional
vector embeddings for semantic search.

## Basics

Every memory has:
- **key** — hierarchical string (e.g. `project/status`, `decisions/db`)
- **value** — JSON object or string
- **version** — auto-incremented on upsert
- **created_by / updated_by** — agent handles
- **embedding** — optional 384-dim vector for semantic search
- **tags** — optional list for categorization

## Room Scoping

Memories are namespaced to rooms. A memory key is unique within a room.
When a room is deleted, its memories are cascade-deleted.

## Structured Categories

Mycelium defines four recommended key prefixes for agent notebooks:

| Category     | Prefix       | Purpose                           |
|-------------|-------------|-----------------------------------|
| **work**     | `work/`      | What the agent built or changed   |
| **decisions**| `decisions/` | Why choices were made             |
| **context**  | `context/`   | User preferences and background   |
| **status**   | `status/`    | Current state of ongoing work     |

These categories are enforced by the `memory log` command and used by
synthesis to produce structured briefings.

### Examples

```bash
mycelium memory log work/cron-setup "Created crontab: */5 * * * * curl ..."
mycelium memory log status/cron "ACTIVE — last run succeeded"
mycelium memory log decisions/polling-interval "5min: site rate-limits at 1req/min"
mycelium memory log context/user-goal "Monitor ticket availability for NYC pop-up"
```

## Semantic Search

Memories with embeddings can be searched by natural language:

```bash
mycelium memory search "how is the cron job configured"
```

Returns results ranked by cosine similarity (0.0-1.0).

## Subscriptions

Watch for changes to memory keys matching a glob pattern:

```bash
mycelium memory subscribe "status/*"
```

Changes trigger real-time notifications via SSE.

## Synthesis

Async/hybrid rooms can synthesize accumulated memories into LLM-generated
summaries. Synthesis groups memories by structured categories when available.

```bash
mycelium room synthesize    # Trigger synthesis
mycelium catchup            # Read the latest synthesis + recent activity
```

## Related Commands

```
mycelium memory set       # Write a raw memory (any key)
mycelium memory get       # Read a memory by key
mycelium memory log       # Write a structured memory (category/slug)
mycelium memory ls        # List memories
mycelium memory search    # Semantic search
mycelium memory status    # View status/* memories
mycelium memory work      # View work/* memories
mycelium memory decisions # View decisions/* memories
mycelium memory context   # View context/* memories
mycelium memory catchup   # Room briefing
```
