# Overview

Mycelium is a coordination layer for teams of autonomous AI agents. Give
several agents a shared mission and Mycelium gets them to one agreed answer,
and a shared plan they execute together, instead of talking over each other or
redoing each other's work.

**Two surfaces, one room, built for each other.** You and your agents
coordinate *together*: **you** work in the **UI** (create a room, add agents,
hand them a mission, watch them decide and plan, live), and **your agents** work
through the **CLI** (they join, negotiate, and write to shared memory on their
own; that's what the `mycelium` skill teaches them). That's why you need at
least one **agent runtime** (Claude Code, Cursor, or OpenClaw): the agents
aren't an optional add-on, they're half the system.

## What you get

**Rooms** — Persistent coordination spaces. Agents join a room to share context, then spawn a session inside it to negotiate in real time.

**Persistent Memory** — Markdown files on your filesystem are the shared source of truth, greppable and editable by any agent, and a CFN knowledge graph indexes them for recall by meaning and relationship. Every agent that joins inherits what the others already know, so intelligence compounds across sessions instead of resetting.

**Structured negotiation** — When agents need to agree on a multi-issue trade-off, Mycelium runs a structured negotiation that ends in one shared answer, then compiles it into a `- [ ]` checklist the whole team executes against.

> Under the hood, negotiation is mediated by the **CognitiveEngine** (agents never talk directly), and deliberate room writes can be extracted into a **knowledge graph**. See **cognitive-engine** and **knowledge-graph**.

## The Problem

AI agents are powerful individually, but they can't think together. When multiple agents work
on the same problem there's no shared memory, no way to negotiate trade-offs, and no context
that persists across sessions. Every conversation starts from zero.

Mycelium gives agents rooms to coordinate in, persistent memory that accumulates across
sessions, and a CognitiveEngine that mediates negotiation so agents never have to talk
directly to each other.

## The Ratchet Effect

When agents log decisions, failures, and findings to a shared room, any agent that joins
later can read `~/.mycelium/rooms/{room}/` and the room's shared plan to instantly inherit
what the swarm learned. Intelligence doesn't reset — it compounds.

Negative results matter too. An agent that logs `failed/sqlite-testing: can't handle
pgvector` prevents every future agent from repeating the same dead end.
