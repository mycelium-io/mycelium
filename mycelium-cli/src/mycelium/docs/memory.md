# Memory

Memory is a namespaced key-value store backed by AgensGraph + pgvector. Every write
is embedded (384-dim, local, no API key) and indexed for semantic search.

## Namespace Conventions

Keys use `/` as a separator. This is a convention, not enforced structure —
but it makes `memory ls <prefix>/` very useful.

```bash
# Decisions your team made
mycelium memory set "decisions/db" "AgensGraph — SQL + graph + vector in one"

# Things that failed (so nobody repeats them)
mycelium memory set "failed/sqlite" "Can't handle pgvector or JSONB"

# Agent-scoped status
mycelium memory set "status/prometheus" "Working on CFN integration" --handle prometheus-agent

# Browse a namespace
mycelium memory ls decisions/
mycelium memory ls failed/
```

> **Always upserts.** Calling `memory set` on an existing key overwrites it.
> The version number increments automatically so you can track changes.

## Semantic Search

Search finds memories by meaning — cosine similarity on all-MiniLM-L6-v2 embeddings
(384 dimensions, runs locally).

```bash
mycelium memory search "what database decisions were made"
mycelium memory search "what failed and why"
mycelium memory search "what is the current status"
```

## Catchup

When a new agent joins a room that's been active, it can instantly get briefed on
everything the swarm learned:

```bash
# New agent arrives, gets the full context
mycelium catchup
```

CognitiveEngine synthesizes the room's memory into a structured briefing:
decisions made, work in progress, blockers, and what failed.
