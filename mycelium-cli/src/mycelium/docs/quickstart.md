# Quick Start

## Install

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

The installer sets up the CLI, prompts for your LLM provider, then brings up
the full stack (backend + AgensGraph) via `docker compose`.
Run `mycelium --help` after install to verify.

> **An LLM key is required for coordination.** Memory works without one, but
> the CognitiveEngine needs an LLM to negotiate; if you pick "Skip" at the
> prompt, agents will join sessions but never reach consensus. You can add it
> later with `mycelium config set llm.model <model>` and `mycelium config apply`.

The install command is interactive — it checks Docker, pulls base images, asks for
your LLM config, then calls `docker compose up` and provisions a default
workspace automatically. No manual backend setup required.

```bash
# What mycelium install does:
#  1. Check Docker + disk space
#  2. Pull base images (postgres, AgensGraph) in the background
#  3. Prompt for LLM provider (Anthropic, OpenAI, Ollama, OpenRouter, ...)
#  4. docker compose up --build -d
#  5. Health-poll until services are ready
#  6. Provision default workspace + MAS
#  7. Write ~/.mycelium/config.toml

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
mycelium up       # start the backend + AgensGraph stack
mycelium status   # health check — backend, database, LLM
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

A room is a persistent namespace for memory, agents, and coordination:

```bash
# Create a room and make it active
mycelium room create my-project
mycelium room use my-project
```

Open `my-project` in the UI — it's empty for now. Next we'll add agents and
start talking to them.

## Add agents

The **agent primitive** registers an addressable agent in the room. Mycelium
wires up the underlying adapter for you; agents coordinate through the room's
own message stream, so there's nothing else to set up per agent.

```bash
# Greenfield — provision a brand-new agent
mycelium agent create planner --adapter openclaw \
    --description "Sprint planner, optimizes for shipping speed"

# Brownfield — adopt agents that already exist in your OpenClaw gateway
mycelium agent add
```

`claude_code` and `cursor` agents are cold-spawned by the Mycelium daemon;
see the **Adapters** guide for the full list.

```bash
# See who's in the room
mycelium agent ls
```

## Coordinate

In the UI room view, type in the chat box and **`@`-mention** an agent — it
replies in the live message stream. The same message can be sent from the CLI:

```bash
# Send an @-addressed message to a registered agent
mycelium agent invoke planner "draft a plan for the Q3 migration"
```

When you ask multiple agents to reach a decision, Mycelium's CognitiveEngine
runs a structured negotiation. On consensus, the agreement compiles into the
room's shared plan — visible in the **PLAN** tab in the UI, or from the CLI:

```bash
mycelium plan tasks       # the room's shared task list
```

The result lands back in the same room stream — no need to go hunting for it in
a separate chat.

## Share memory

Rooms are also persistent memory. Anything you write is searchable by meaning
and visible to every agent in the room:

```bash
# Share context
mycelium memory set "decisions/db" "PostgreSQL with pgvector"
mycelium memory set "decisions/api" "REST with generated OpenAPI client"

# Search by meaning, not keywords
mycelium memory search "what database decisions were made"

# Browse the namespace
mycelium memory ls
mycelium memory ls decisions/
```

> Prefer to script the low-level negotiation directly? The
> `mycelium session join` / `session await` commands drive the CognitiveEngine
> from the terminal — see the **Sessions** reference.
