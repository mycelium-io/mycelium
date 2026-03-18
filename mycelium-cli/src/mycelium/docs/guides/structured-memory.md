# Structured Memory Guide

This guide shows how to use Mycelium's structured memory conventions to give
agents continuity across sessions.

## The Problem

An agent helps build something over a long session. The session ends. When the
user (or another agent) comes back, there's no memory of what happened. The
new session starts from scratch.

## The Solution: Category Conventions

Instead of writing memories with arbitrary keys, use structured prefixes:

```
work/       — What was built or changed
decisions/  — Why choices were made
context/    — User preferences and background
status/     — Current state of ongoing work
```

The `memory log` command validates these categories and auto-timestamps content.

## Workflow

### 1. Set up a persistent room

```bash
mycelium room create project-x --mode async --persistent
mycelium room set project-x
```

### 2. Log structured memories as you work

```bash
# Record what you built
mycelium memory log work/api-server "Set up FastAPI with auth endpoints"
mycelium memory log work/database "Created PostgreSQL schema, 3 tables"

# Record why you made choices
mycelium memory log decisions/framework "FastAPI over Flask: async + type hints"
mycelium memory log decisions/auth "JWT tokens, 1hr expiry, refresh via cookie"

# Record user context
mycelium memory log context/goal "Build MVP for investor demo by Friday"
mycelium memory log context/constraints "Must run on single $20/mo VPS"

# Track current state
mycelium memory log status/api "PASSING — all 12 endpoints tested"
mycelium memory log status/deploy "BLOCKED — waiting on DNS propagation"
```

### 3. Check status at a glance

```bash
mycelium memory status    # Table of all status/* memories
mycelium memory work      # What's been built
mycelium memory decisions # Why things are the way they are
```

### 4. Catch up after a break

```bash
mycelium catchup
```

If synthesis has run, you'll get a structured briefing:

```
project-x  async room  12 memories  2 contributors

Latest Synthesis
  _synthesis/20260318T030000Z  2026-03-18 03:00

  ## What's Built
  API server with 12 endpoints, PostgreSQL with 3 tables...

  ## Current Status
  API passing all tests. Deploy blocked on DNS...

  ## Key Decisions
  FastAPI for async + types. JWT auth with 1hr expiry...
```

### 5. Update status as things change

```bash
# --update/-u flag allows overwriting
mycelium memory log status/deploy "ACTIVE — deployed to vps.example.com" -u
```

## Type Safety

The `memory log` command validates keys against the `MemoryLogEntry` type
(defined in `mycelium.sstp`). This is the same pattern used for negotiation
payloads (`ProposeReply`, `RespondReply`) — Pydantic validation before the
API call, so malformed keys fail fast on the client side.

Valid slugs: lowercase alphanumeric, hyphens, dots, underscores.
- `work/api-server` — valid
- `status/v2.deploy` — valid
- `decisions/Why We Chose X` — invalid (uppercase, spaces)

## Synthesis Awareness

When you trigger synthesis (`mycelium room synthesize`), the engine groups
memories by category prefix. This produces structured output:

- **What's Built** — from `work/*` memories
- **Current Status** — from `status/*` memories
- **Key Decisions** — from `decisions/*` memories
- **Context** — from `context/*` memories

Memories without a known category prefix are grouped under "Other".

## Combining with Raw Memory

The `memory log` command is for structured, convention-following writes. The
existing `memory set` command still works for arbitrary keys:

```bash
mycelium memory set "custom/anything" "freeform value"
```

Both coexist — `memory log` is the typed path, `memory set` is the raw path.
