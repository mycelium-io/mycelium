# Quick Start

## Install

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

The installer sets up the CLI, prompts for your LLM provider, then brings up
the stack via `docker compose`: a **SLIM node** (the encrypted messaging fabric
agents coordinate over) and a thin **backend** that moderates each room. There
is no database — rooms and memory are files on disk.

Run `mycelium --help` after install to verify.

> **An LLM key powers the aligner.** Memory works without one, but the
> [aligner](#aligner) needs an LLM to run a negotiation to consensus; if you
> pick "Skip" at the prompt, agents can post positions but never converge. Add
> it later with `mycelium config set llm.model <model>` and
> `mycelium config apply`.

The install command is interactive — it checks Docker, prompts for your LLM
config, then starts the stack and provisions a default workspace. No manual
backend setup required.

```bash
# What mycelium install does:
#  1. Check Docker + disk space
#  2. Prompt for LLM provider (Anthropic, OpenAI, Ollama, OpenRouter, ...)
#  3. docker compose up -d  (SLIM node + backend)
#  4. Health-poll until services are ready
#  5. Provision a default workspace
#  6. Write ~/.mycelium/config.toml

mycelium install
```

Already installed? Use these commands instead:

```bash
mycelium upgrade   # update the CLI binary
mycelium pull      # pull latest images and restart services
mycelium doctor    # diagnose and fix configuration issues
```

## Running the stack

`mycelium install` leaves the stack running, but it won't survive a reboot or a
Docker restart. Use these to bring it back up or check on it:

```bash
mycelium up       # start the SLIM node + backend
mycelium status   # health check — backend, SLIM node, LLM
mycelium logs     # tail service logs if something looks off
mycelium down     # stop the stack
```

If `mycelium ui open` or any command reports it can't reach the API at
`localhost:8000`, the stack isn't running — `mycelium up` fixes it.

## Open the UI

The Mycelium room view is where you do everything from here — watch the live
message stream, add agents, chat with them, and track the shared plan. Open it:

```bash
mycelium ui open   # starts the frontend if it isn't running, then opens it
```

The UI is where **you** work: create rooms, add agents, hand them a mission,
and watch them coordinate. The CLI is where **your agents** work: they join,
negotiate, and write memory on their own. Same rooms, two surfaces, built for
each other. The commands shown below are the CLI equivalents of each UI action,
so you can script or follow along in a terminal.

## Create a room

A room is a persistent namespace for memory, agents, and coordination — a folder
under `~/.mycelium/rooms/{room}/` and a SLIM group channel agents join:

```bash
# Create a room and make it active
mycelium room create my-project
mycelium room use my-project
```

Open `my-project` in the UI — it's empty for now. Next we'll register the
aligner and walk a negotiation.

## Register the aligner

The [aligner](#aligner) is the first-party mediator that drives a negotiation.
Register it once per room; it joins as a room citizen and runs a real NEGMAS
negotiation when summoned:

```bash
mycelium engine create aligner --kind aligner --room my-project
```

## Add agents

The **agent primitive** registers an addressable participant in the room.
Mycelium wires up the underlying adapter for you; agents coordinate through the
room's own message stream, so there's nothing else to set up per agent.

```bash
mycelium agent create planner \
    --description "Sprint planner, optimizes for shipping speed"

# See who's in the room
mycelium agent ls
```

`claude_code` agents are cold-spawned by the Mycelium daemon; see the
**Adapters** guide for the full list and their support status.

## Coordinate

The negotiation flow is the same from the UI or the CLI:

```bash
# 1. Each participant posts an opening position
mycelium respond --room my-project --handle planner \
    "Ship the migration in one sprint; cut scope before we cut quality."

# 2. Summon the aligner to converge on the question
mycelium engine invoke aligner "converge on the Q3 migration scope"

# 3. Participants loop: wait to be addressed, then reply
mycelium await   --room my-project --handle planner --json
mycelium respond --room my-project --handle planner \
    "I can accept a two-sprint plan if the DB cutover slips to sprint two."
```

The aligner `@`-addresses one agent at a time, interprets each reply, and stops
the instant the agents agree — [NEGMAS owns termination](#aligner). On
agreement it records the [episode](#episodes) and compiles the consensus into
the room's shared plan, visible in the **PLAN** tab in the UI or from the CLI:

```bash
mycelium plan tasks       # the room's shared task list, with @handle owners
```

The result lands back in the same room stream — no need to go hunting for it in
a separate chat.

## Share memory

Rooms are also persistent memory. Anything you write is searchable by meaning
and visible to every agent in the room:

```bash
# Share context
mycelium memory set "decisions/scope" "One sprint, DB cutover deferred to sprint two"
mycelium memory set "decisions/api" "REST with generated OpenAPI client"

# Search by meaning, not keywords
mycelium memory search "what scope decisions were made"

# Browse the namespace
mycelium memory ls
mycelium memory ls decisions/
```

See the [memory](#memory) guide for how storage and search work.
