# Structured Memory Guide

When an agent finishes a stretch of work and goes away, the next agent (or
person) to pick it up starts from nothing unless the work was written down.
This guide shows a simple set of key prefixes that makes that easy: what was
built, why, what the user wants, where things stand, and how to do things
again.

## The prefixes

```
work/        What was built or changed
decisions/   Why choices were made
context/     User preferences and background
status/      Current state of ongoing work
procedures/  Steps you'll want to repeat later
```

When a key starts with one of these, `memory set` checks the rest of the key
and adds a timestamp to the content.

`work/`, `decisions/` and `status/` are also [board](#board) namespaces, so
memories there show up on the room's board too.

## Using them

### 1. Pick a room

```bash
mycelium room create project-x
mycelium room use project-x
```

### 2. Write things down as you go

```bash
# What you built
mycelium memory set work/api-server "Set up FastAPI with auth endpoints"
mycelium memory set work/database "Created PostgreSQL schema, 3 tables"

# Why you made the choices you did
mycelium memory set decisions/framework "FastAPI over Flask: async + type hints"
mycelium memory set decisions/auth "JWT tokens, 1hr expiry, refresh via cookie"

# What the user wants
mycelium memory set context/goal "Build MVP for investor demo by Friday"
mycelium memory set context/constraints "Must run on single $20/mo VPS"

# Where things stand
mycelium memory set status/api "PASSING: all 12 endpoints tested"
mycelium memory set status/deploy "BLOCKED: waiting on DNS propagation"

# Steps to repeat later
mycelium memory set procedures/deploy-vps "1. ssh vps  2. cd /app && git pull  3. systemctl restart app  4. curl healthcheck"
mycelium memory set procedures/db-migrate "1. uv run alembic upgrade head  2. Verify with psql -c 'SELECT version()'"
```

### 3. Read them back

```bash
mycelium memory status      # everything under status/
mycelium memory work        # what's been built
mycelium memory decisions   # why things are the way they are
mycelium memory context     # background and preferences
mycelium memory procedures  # how to do things again
```

### 4. Update as things change

`memory set` replaces the old value, so just set the new one:

```bash
mycelium memory set status/deploy "ACTIVE: deployed to vps.example.com"
```

## Key rules

After the prefix, a key can use lowercase letters, numbers, hyphens, dots and
underscores, and must start with a letter or number. Uppercase letters are
lowercased for you. A key that breaks these rules is rejected before anything
is sent to the hub.

- `work/api-server` works
- `status/v2.deploy` works
- `decisions/Why We Chose X` is rejected (spaces)

Keys with any other prefix aren't checked:

- `custom/anything`
- `research/index-perf`
