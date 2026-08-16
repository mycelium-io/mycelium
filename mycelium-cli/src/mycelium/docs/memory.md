# Memory

Room memory lives on the hub: one store every agent reads and writes through the
CLI, chat, or the UI. An embedding index over that store lets agents recall by
meaning, but it is never an independent source of writes. Whatever stays private
to one agent stays in that agent's own local files, never indexed.

## Three layers, one source of truth

Mycelium memory has three layers, and only the middle one is "the memory":

1. **Your private context** is yours alone: agent-native files like `SOUL.md`
   or per-agent notes that never leave your machine and are never indexed or
   shared. Anything only you need lives here.
2. **Room memory** is the shared source of truth, held by the hub. Every agent
   in the room reads and writes it with `mycelium memory` — from any machine,
   with no local copy to keep in step. If the team should know it, write it here.
3. **The search index** is a derived view that you never write to directly. The
   hub embeds each room memory so agents can recall by meaning. It rebuilds from
   the store, so the store always wins.

Rule of thumb: if a teammate should find it, put it in room memory. The index is
how they find it; the hub is where it lives; your private notes stay yours.

## One store, many clients

Any machine that is not the hub is a **thin client**. It keeps no copy of room
memory: `memory get`, `ls`, `search`, and the category views (`memory decisions`,
`status`, `work`, …) all resolve against the hub over HTTP, and `memory set`
writes straight to it.

That has two consequences worth knowing:

- **No drift, no sync ritual.** A read reflects what the hub has right now, so
  two machines never disagree about what a key says.
- **Reads need the hub.** If the hub is down or `server.api_url` points
  somewhere wrong, memory commands say so plainly rather than quietly serving
  something stale.

```bash
mycelium config get server.api_url   # which hub this machine reads from
mycelium status                      # is it up?
```

Every write to room memory is embedded (384-dim, local, no API key, no external
service) and indexed for semantic search.

## Namespace Conventions

Keys use `/` as a separator. The structure is a convention rather than a rule,
but it makes `memory ls <prefix>/` very useful.

```bash
# Decisions your team made
mycelium memory set "decisions/storage" "Rooms are folders; memory is markdown files"

# Things that failed (so nobody repeats them)
mycelium memory set "failed/single-writer" "Serializing all writes stalled under load"

# Per-agent status (handle is just attribution)
mycelium memory set "status/prometheus" "Wiring up the aligner" --handle prometheus-agent

# Browse a namespace
mycelium memory ls decisions/
mycelium memory ls failed/
```

> **Always upserts.** Calling `memory set` on an existing key overwrites it.
> The version number increments automatically so you can track changes.

## How the hub stores it

The hub keeps each memory as a markdown file with YAML frontmatter at
`~/.mycelium/rooms/{room}/{key}.md`, plus a JSONL embedding index beside it.
That is internal storage, not a surface you work in — clients see it through
`mycelium memory`, which is the same on the hub and on every spoke.

To see the stored form of a memory from anywhere:

```bash
mycelium memory get decisions/storage --raw
```

> **Operating the hub.** On the hub itself the files are ordinary files, so an
> operator can inspect, back up, or bulk-edit them. Edits made outside the CLI
> bypass the index; run `mycelium memory reindex` afterwards to resync. The
> index also rebuilds when the backend starts and follows on-disk changes while
> it runs.

## Semantic Search

Search finds memories by meaning: cosine similarity on all-MiniLM-L6-v2
embeddings (384 dimensions, runs locally, no external service).

```bash
mycelium memory search "what storage decisions were made"
mycelium memory search "what failed and why"
mycelium memory search "what is the current status"
```
