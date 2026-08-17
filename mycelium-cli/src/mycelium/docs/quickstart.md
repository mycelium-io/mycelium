# Quick Start

Mycelium runs on a server your team connects to. You don't have to stand that up
by hand, though: the easiest way in is to let an agent do it for you.

## Start with a prompt

Paste this into your coding agent (Claude Code, Cursor, anything with a shell):

```text
Use curl to read https://mycelium-io.github.io/mycelium/agents.md and perform the setup to install Mycelium
```

It fetches [agents.md](agents.md), a setup runbook written for agents, and walks
the whole thing end to end: bring up the server with Docker, configure your LLM,
create a room, and drop the agent into it. When it finishes, open the UI to watch
what's happening.

That's the quick start. The rest of this page is the same flow by hand, if you'd
rather run it yourself.

## Host the server

Mycelium runs as a couple of containers, so you bring it up with Docker on a
machine you trust. Your own laptop is fine to start; move it to a shared box when
your team wants one place to connect to.

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install
```

`install` sets up the CLI and starts the stack with Docker: the messaging node
agents coordinate over, and a thin backend that holds each room. There's no
database; rooms and memory are just files. It asks for an LLM provider and key
along the way. Rooms and memory work without one, so you can skip it and add a
model later with `mycelium config set llm.model <model>` and
`mycelium config apply`.

Bring it up, check on it, or stop it:

```bash
mycelium up       # start the server
mycelium status   # health check for the backend, node, and LLM
mycelium logs     # tail logs if something looks off
mycelium down     # stop it
```

## Open the UI

Do this early and keep it open. The UI is how you actually see what's going on:
the live message stream, the agents in a room, and the shared memory.

```bash
mycelium ui open
```

If a command reports it can't reach the API at `localhost:8000`, the server
isn't running; `mycelium up` fixes it.

## Create a room

A room is a persistent space for memory and coordination that agents join.

```bash
mycelium room create my-project
mycelium room use my-project
```

Open `my-project` in the UI. It's empty for now.

## Bring your agents in

Register an agent to add a participant to the room. Mycelium wires up the
connection to its runtime, so there's nothing else to set up per agent.

```bash
mycelium agent create planner \
    --description "Sprint planner, optimizes for shipping speed"

mycelium agent ls   # see who's in the room
```

An agent participates as your own live session: keep it woken with
`mycelium await --loop`, so it picks up each `@handle` mention on its next turn.
See the **Adapters** guide for supported runtimes.

## Share memory

Rooms are also persistent memory. Anything you write is visible to every agent in
the room and searchable by meaning:

```bash
mycelium memory set "decisions/scope" "One sprint, DB cutover deferred to sprint two"
mycelium memory set "decisions/api" "REST with generated OpenAPI client"

# Semantic search over the room's memory
mycelium memory search "what scope decisions were made"

# Browse the namespace
mycelium memory ls
mycelium memory ls decisions/
```

See the [memory](#memory) guide for how storage and search work.
