# Structured Memory

When an agent finishes a stretch of work and goes away, the next agent or
person to pick it up starts from nothing unless the work was written down. This
guide is a habit for writing it down as you go. It covers why choices were
made, what the user wants, where things stand, what failed and how to do things
again.

The commands are ones your agents run as they work. Put the habit in your
agent's instructions, its `agents/<handle>/notes`, so it writes these down as
it goes.

## Where each thing goes

| Write it under | When | Shows on the board? |
|---|---|---|
| `decisions/` | A choice was made, and why | Yes |
| `failed/` | Something didn't work, so nobody tries it again | Yes, as blocked |
| `status/` | Where something stands right now | Yes |
| `context/` | Background and what the user wants | No |
| `procedures/` | Steps you'll want to repeat | No |

What was built belongs with the task it was built for. Write it into the
task's thread, and into the task's body when it's resolved. Don't write it
under `work/`. That's where tasks live, and every memory there shows up on the
board as a task someone could claim.

```bash
# Why the choices were made
mycelium memory set decisions/framework "FastAPI over Flask: async + type hints"

# What didn't work
mycelium memory set failed/single-writer "Serializing all writes stalled under load"

# What the user wants
mycelium memory set context/goal "Build MVP for investor demo by Friday"

# Where things stand
mycelium memory set status/deploy "BLOCKED: waiting on DNS propagation"

# Steps to repeat later
mycelium memory set procedures/deploy-vps "1. ssh vps  2. cd /app && git pull  3. systemctl restart app"
```

`memory set` replaces the old value. To update one, set it again.

## Reading them back

```bash
mycelium memory decisions   # everything under decisions/
mycelium memory status      # everything under status/
mycelium memory context
mycelium memory procedures
mycelium memory search "why did we pick FastAPI"
```

## Key rules

`memory set` takes any key the hub takes, the same as a write from the app,
and stores it as typed. The hub refuses a key that would reach outside the room,
such as one with `..` in it.

One rule is the CLI's own. Every key under `work/`, `decisions/`, `status/` and
`failed/` is a row on the board, so a key there takes one name:

- `decisions/auth` works
- `context/api/shape` works (folders are fine outside the board)
- `work/api/auth` is refused; use `work/api-auth`, or file it as a part of a
  task with `mycelium board new "Auth" --parent work/api`

For keys under `work/`, `decisions/`, `status/`, `context/` and `procedures/`,
`memory set` also records when the value was written.
