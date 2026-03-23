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
work/        — What was built or changed
decisions/   — Why choices were made
context/     — User preferences and background
status/      — Current state of ongoing work
procedures/  — Reusable how-to steps (do this again later)
```

`memory set` validates these automatically — when the key starts with a known
category prefix, it checks the slug format and auto-timestamps the content.

## Workflow

### 1. Set up a room

```bash
mycelium room create project-x
mycelium room use project-x
```

### 2. Write structured memories as you work

```bash
# Record what you built
mycelium memory set work/api-server "Set up FastAPI with auth endpoints"
mycelium memory set work/database "Created PostgreSQL schema, 3 tables"

# Record why you made choices
mycelium memory set decisions/framework "FastAPI over Flask: async + type hints"
mycelium memory set decisions/auth "JWT tokens, 1hr expiry, refresh via cookie"

# Record user context
mycelium memory set context/goal "Build MVP for investor demo by Friday"
mycelium memory set context/constraints "Must run on single $20/mo VPS"

# Track current state
mycelium memory set status/api "PASSING — all 12 endpoints tested"
mycelium memory set status/deploy "BLOCKED — waiting on DNS propagation"

# Save reusable procedures
mycelium memory set procedures/deploy-vps "1. ssh vps  2. cd /app && git pull  3. systemctl restart app  4. curl healthcheck"
mycelium memory set procedures/db-migrate "1. uv run alembic upgrade head  2. Verify with psql -c 'SELECT version()'"
```

### 3. Check status at a glance

```bash
mycelium memory status     # Table of all status/* memories
mycelium memory work       # What's been built
mycelium memory decisions  # Why things are the way they are
mycelium memory procedures # How to do things again
```

### 4. Catch up after a break

```bash
mycelium catchup
```

If synthesis has run, you'll get a structured briefing:

```
project-x  12 memories  2 contributors

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
# memory set always upserts — just set the new value
mycelium memory set status/deploy "ACTIVE — deployed to vps.example.com"
```

## Type Safety

`memory set` validates category keys against the `MemoryLogEntry` type
(defined in `mycelium.sstp`). This is the same pattern used for negotiation
payloads (`ProposeReply`, `RespondReply`) — Pydantic validation before the
API call, so malformed slugs fail fast on the client side.

Valid slugs: lowercase alphanumeric, hyphens, dots, underscores.
- `work/api-server` — valid
- `status/v2.deploy` — valid
- `decisions/Why We Chose X` — invalid (uppercase, spaces)

Keys without a known category prefix skip validation entirely:
- `custom/anything` — passes through, no slug check
- `research/pgvector-perf` — passes through

## Synthesis Awareness

When you trigger synthesis (`mycelium room synthesize`), the engine groups
memories by category prefix. This produces structured output:

- **What's Built** — from `work/*` memories
- **Current Status** — from `status/*` memories
- **Key Decisions** — from `decisions/*` memories
- **Context** — from `context/*` memories
- **Reusable Procedures** — from `procedures/*` memories

Memories without a known category prefix are grouped under "Other".
