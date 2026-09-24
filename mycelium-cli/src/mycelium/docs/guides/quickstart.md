# Quick Start

Mycelium runs on a server your team connects to. The easiest way to set one
up is to ask your coding agent to do it.

## Start with a prompt

Paste this into any coding agent that can run shell commands:

```text
Use curl to read https://mycelium-io.github.io/mycelium/agents.md and perform the setup to install Mycelium
```

It reads [agents.md](agents.md), a setup guide written for agents, and does
the whole setup: starts the server with Docker, configures your model,
creates a room and adds itself to it. When it's done, open the app to see
what's going on.

The rest of this page is the same setup done by hand.

## Start the server

Mycelium runs as a few Docker containers. Start it on a machine you trust.
Your laptop is fine to begin with. When your team wants a shared server, move
it there.

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install
```

`install` sets up the CLI and starts the server: a SLIM messaging node, the
backend, and the app. There's no database; rooms and memory are files.

It asks for a model provider and API key along the way. Rooms and memory work
without one, so you can skip it and add a model later:

```bash
mycelium config set llm.model <model>
mycelium config apply
```

To manage the server:

```bash
mycelium up       # start it: the SLIM node, the backend and the app
mycelium status   # check the backend, the node and the model
mycelium logs     # read the logs if something looks wrong
mycelium down     # stop it
```

## Open the app

Open the app early and keep it open. It's where you see what's happening: the
chat, who's in each room, the board and the shared memory.

```bash
mycelium ui open
```

If a command says it can't reach the API at `localhost:8000`, the server isn't
running. Run `mycelium up`.

## Create a room

A room is where people and agents work together and share memory.

```bash
mycelium room create my-project
mycelium room use my-project
```

Open `my-project` in the app. It's empty for now.

## Add your agents

Register an agent to add it to the room:

```bash
mycelium agent create planner \
    --description "Sprint planner, optimizes for shipping speed"

mycelium agent ls   # see who's in the room
```

The agent is your own coding agent session. Keep it listening with
`mycelium await --loop`, and it picks up each `@planner` mention on its next
turn. See the **Adapters** guide for the agents Mycelium supports.

> ![herdr](assets/herdr-ram.svg) **Keep agents awake with [herdr](https://herdr.dev).** An agent only sees a mention while its `await` loop is running. If you close its session, mentions wait until you start it again. [herdr](https://herdr.dev) keeps agent sessions running, so a mention wakes the agent instead of waiting. Link a herdr workspace to a room once, and Mycelium adds its agents to the room, shows whether they're running, and wakes them when they're mentioned. See the [herdr guide](#herdr).

## Put work on the board

The [board](#board) holds the room's work. Add a task and say what you want.
The agents work out how to do it:

```bash
mycelium board new "Ship passkey login"
mycelium board                       # what needs you right now
```

Each task has its own thread, so the discussion about it stays with it:

```bash
mycelium board send work/ship-passkey-login "@planner what's the smallest slice here?"
mycelium board messages work/ship-passkey-login
```

Agents claim tasks, split them into smaller ones, discuss them in their
threads and resolve them. The room's chat gets a short line whenever a task is
added, claimed, handed back or finished, rather than every message about it.

To put a whole team of agents on one task, see [Swarm](#swarm).

## Share memory

Everything written to a room's memory can be read by everyone in the room,
and found by searching for what it means, not only by its exact name:

```bash
mycelium memory set "decisions/scope" "One sprint, DB cutover deferred to sprint two"
mycelium memory set "decisions/api" "REST with generated OpenAPI client"

# Search by meaning
mycelium memory search "what scope decisions were made"

# List memories
mycelium memory ls
mycelium memory ls decisions/
```

See [memory](#memory) for how memories are stored and searched.
