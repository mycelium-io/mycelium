# Overview

A coordination layer for multi-agent systems — shared rooms, persistent memory,
and semantic negotiation so agents can think together.

**Rooms** — Namespaced coordination spaces. Agents join rooms to share context or negotiate in real time.

**Persistent Memory** — Namespaced key-value store with semantic vector search. Intelligence compounds across sessions.

**CognitiveEngine** — Mediates all agent interaction. Drives structured negotiation — agents never talk directly.

**Knowledge Graph** — LLM extraction turns conversations into concepts and relationships in an openCypher graph.

## The Problem

AI agents are powerful individually, but they can't think together. When multiple agents work
on the same problem there's no shared memory, no way to negotiate trade-offs, and no context
that persists across sessions. Every conversation starts from zero.

Mycelium gives agents rooms to coordinate in, persistent memory that accumulates across
sessions, and a CognitiveEngine that mediates negotiation so agents never have to talk
directly to each other.

## The Ratchet Effect

When agents log decisions, failures, and findings to a shared room, any agent that joins
later can run `mycelium catchup` and instantly know everything the swarm learned.
Intelligence doesn't reset — it compounds.

Negative results matter too. An agent that logs `failed/sqlite-testing: can't handle
pgvector` prevents every future agent from repeating the same dead end.
