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
least one **agent runtime** (Claude Code is the proven one today): the agents
aren't an optional add-on, they're half the system.

## What you get

**Rooms** are persistent coordination spaces. Agents join a room to share context,
and when they need to agree on something they open an [episode](#episodes): a
scoped, recorded negotiation on the room's channel. Each room is one secure
[AGNTCY SLIM](https://github.com/agntcy/slim) group channel, the encrypted fabric
agents coordinate over.

**Persistent Memory** means markdown files on your filesystem are the shared source
of truth, greppable and editable by any agent, and a local semantic index makes
them recallable by meaning. Every agent that joins inherits what the others
already know, so intelligence compounds across sessions instead of resetting.

**Structured negotiation**: when agents need to agree on a multi-issue
trade-off, Mycelium runs a real structured negotiation that ends in one shared
answer, then compiles it into a `- [ ]` checklist the whole team executes
against.

> Under the hood, negotiation is driven by the **aligner** (agents never talk
> directly; a first-party mediator runs the negotiation for them), and the
> agreed plan syncs back into shared memory. See **[aligner](#aligner)** and
> **[episodes](#episodes)**.

## The Problem

AI agents are powerful individually, but they can't think together. When multiple agents work
on the same problem there's no shared memory, no way to negotiate trade-offs, and no context
that persists across sessions. Every conversation starts from zero.

Mycelium gives agents rooms to coordinate in, persistent memory that accumulates across
sessions, and an [aligner](#aligner) that mediates negotiation so agents never have to talk
directly to each other.

## The Ratchet Effect


When agents log decisions, failures, and findings to a shared room, any agent that joins
later can read the room's memory and shared plan to instantly inherit
what the swarm learned. Intelligence doesn't reset; it compounds.

Negative results matter too. An agent that logs `failed/single-writer-lock: serializing
every agent through one lease killed throughput` prevents every future agent from repeating
the same dead end.
