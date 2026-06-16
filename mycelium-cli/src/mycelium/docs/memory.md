# Memory

Room memory is markdown files on your filesystem: the shared source of truth,
greppable and editable by any agent. The CFN knowledge graph is a derived index
over those files, for recall by meaning and relationship, never an independent
source of writes. Whatever stays private to one agent stays in that agent's own
local memory, never indexed.

## Three layers, one source of truth

Mycelium memory has three layers, and only the middle one is "the memory":

1. **Your private context** is yours alone: agent-native files like `SOUL.md`
   or per-agent notes that never leave your machine and are never indexed or
   shared. Anything only you need lives here.
2. **Room memory** is the shared source of truth: markdown files under
   `~/.mycelium/rooms/{room}/` that every agent in the room can read, `grep`,
   edit, and `git`-track. If the team should know it, write it here.
3. **The CFN knowledge graph** is a derived view, not a place you write to.
   Mycelium indexes the room's public artifacts (memory files plus channel
   messages) into it so agents can recall by meaning and by relationship. It
   rebuilds from the files, so the files always win.

Rule of thumb: if a teammate should find it, put it in room memory. The graph
is how they find it; the filesystem is where it lives; your private notes stay
yours.

Every write to room memory is embedded (384-dim, local, no API key) and indexed
for semantic search.

## Namespace Conventions

Keys use `/` as a separator. This is a convention, not enforced structure —
but it makes `memory ls <prefix>/` very useful.

```bash
# Decisions your team made
mycelium memory set "decisions/db" "AgensGraph — SQL + graph + vector in one"

# Things that failed (so nobody repeats them)
mycelium memory set "failed/sqlite" "Can't handle pgvector or JSONB"

# Per-agent status (handle is just attribution)
mycelium memory set "status/prometheus" "Working on CFN integration" --handle prometheus-agent

# Browse a namespace
mycelium memory ls decisions/
mycelium memory ls failed/
```

> **Always upserts.** Calling `memory set` on an existing key overwrites it.
> The version number increments automatically so you can track changes.

## Filesystem-Native Storage

Every memory is a markdown file at `~/.mycelium/rooms/{room}/{key}.md` with YAML
frontmatter. You can read, edit, or version-control these files directly.

```bash
# View the raw file
cat ~/.mycelium/rooms/design-review/decisions/database.md

# Edit with any tool
vim ~/.mycelium/rooms/design-review/decisions/database.md

# Git-track a room's memory
cd ~/.mycelium/rooms/design-review && git init
```

The pgvector search index auto-syncs when:
- You use `mycelium memory set` (immediate dual-write)
- The backend starts up (incremental scan of changed files)
- Files change on disk while the backend is running (file watcher)

For bulk edits, you can also trigger a manual reindex:
```bash
mycelium memory reindex
```

## Semantic Search

Search finds memories by meaning — cosine similarity on all-MiniLM-L6-v2 embeddings
(384 dimensions, runs locally).

```bash
mycelium memory search "what database decisions were made"
mycelium memory search "what failed and why"
mycelium memory search "what is the current status"
```
