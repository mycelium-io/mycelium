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

Mycelium defines five recommended key prefixes for agent notebooks:

| Category       | Prefix         | Purpose                           |
|---------------|---------------|-----------------------------------|
| **work**       | `work/`        | What the agent built or changed   |
| **decisions**  | `decisions/`   | Why choices were made             |
| **context**    | `context/`     | User preferences and background   |
| **status**     | `status/`      | Current state of ongoing work     |
| **procedures** | `procedures/`  | Reusable how-to steps             |

When `memory set` sees a key with one of these prefixes, it validates the
slug format automatically (lowercase alphanumeric, hyphens, dots, underscores)
and auto-timestamps the content. Keys without a category prefix pass through
freely.

### Examples

```bash
mycelium memory set work/cron-setup "Created crontab: */5 * * * * curl ..."
mycelium memory set status/cron "ACTIVE — last run succeeded"
mycelium memory set decisions/polling-interval "5min: site rate-limits at 1req/min"
mycelium memory set context/user-goal "Monitor ticket availability for NYC pop-up"
mycelium memory set procedures/url-monitor "1. crontab -e  2. Add */5 * * * * curl -s URL | grep PATTERN  3. Verify with crontab -l"
mycelium memory set custom/anything "Freeform — no category validation"
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

Async rooms can synthesize accumulated memories into LLM-generated
summaries. Synthesis groups memories by structured categories when available.

```bash
mycelium room synthesize    # Trigger synthesis
mycelium catchup            # Read the latest synthesis + recent activity
```

## Related Commands

```
mycelium memory set       # Write a memory (validates category keys automatically)
mycelium memory get       # Read a memory by key
mycelium memory ls        # List memories (supports prefix filter)
mycelium memory search    # Semantic search
mycelium memory rm        # Delete a memory
mycelium memory status    # View status/* memories as table
mycelium memory work      # View work/* memories as table
mycelium memory decisions # View decisions/* memories as table
mycelium memory context    # View context/* memories as table
mycelium memory procedures # View procedures/* memories as table
mycelium memory subscribe  # Watch for key pattern changes
mycelium memory catchup   # Room briefing (synthesis + recent activity)
```
