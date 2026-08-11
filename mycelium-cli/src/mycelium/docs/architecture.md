# Architecture

## Deployment Modes

Mycelium supports two deployment modes. The stack is identical in both —
what differs is *where the agents run* and *how they reach the room*.

### 1. Single-device (default)

Everything — the backend, the SLIM node, agents, and CLI — runs on one
machine, typically a developer's laptop. This is what `mycelium install`
sets up out of the box. No network configuration, no remote services to
point at, no shared infrastructure required.

This is the primary deployment target. Use it when one person (or one
machine) owns the whole agent workflow.

### 2. Hub-and-spoke (small teams)

A second, optional mode for small teams that want to share memory, rooms,
and coordination across machines. One machine runs the SLIM node and
backend (the **hub**); other machines run only the CLI + agents (**spokes**)
and connect to the hub's channel.

| Role  | What runs locally | When to use |
|-------|-------------------|-------------|
| **Hub**   | The SLIM node + the thin FastAPI backend (room moderator). | The team's shared coordination server. One per team. |
| **Spoke** | CLI + agents only. Points at the hub's SLIM address. | Each teammate's laptop. Agents on the spoke participate in shared rooms hosted by the hub. |

Stand a hub up and point spokes at it:

```bash
# On the hub — starts the SLIM node + backend, prints the connect address
mycelium hub host

# On each spoke — point this machine at the hub's channel
mycelium hub connect http://<hub-ip>:46357
```

See the [Hub & Spoke Setup guide](#hub-and-spoke) for step-by-step
instructions.

`mycelium doctor` auto-detects which mode you're in by looking at
`server.api_url` in `~/.mycelium/config.toml`: if it points to
`localhost`/`127.0.0.1`, you're a hub; otherwise a spoke. Override the
auto-detection with:

```bash
mycelium doctor --mode hub     # force hub checks
mycelium doctor --mode spoke   # force spoke checks (skip local-only)
mycelium doctor --mode auto    # default — detect from api_url
```

### Syncing room files (remote backend)

When the backend runs on a remote server (EC2, Raspberry Pi, a hub), room files
sync via the HTTP API. The adapter does not auto-sync; run `mycelium sync`
yourself when you want fresh state.

```bash
# Clone a room from a remote backend
mycelium room clone my-project --from http://ec2-host:8000

# Fetch all memories from the backend and write local files
mycelium sync
```

## Stack

Mycelium runs on **one SLIM node** and a thin backend — no database, no
message broker, no vector store.

Agents coordinate over an [AGNTCY SLIM](https://github.com/agntcy) group
channel, one per room: an MLS-encrypted group with shared-secret PSK auth.
The backend is each room's **moderator** — agents (and the human, by proxy)
are members. Room state lives on disk as markdown files; search runs against a
local embedding index. Coordination messages ride SLIM as additive
[L9 envelopes](#l9-protocol).

| Layer | Technology | Used for |
|-------|-----------|----------|
| Messaging | one SLIM node (MLS group channels) | per-room encrypted coordination fabric |
| State | markdown files under `~/.mycelium/rooms/{room}/` | rooms, memories, plan — the source of truth |
| Search | local ONNX embedding index (JSONL) | ~384-dim semantic recall, no external service |
| Protocol | L9 envelopes over SLIM | `exchange` ticks/replies, `commit:*`, `knowledge` |
| Cognition | the aligner — Pi + NEGMAS | drives the negotiation (see [aligner](#aligner)) |
| Embeddings | local ONNX model | 384-dim embeddings, no API key |
| LLM | litellm | plan compilation (100+ providers) |
| Backend | FastAPI (room moderator) | membership, transcript, moderation API |
| Waker | optional daemon | cold-spawns runtimes that can't wake themselves |
| CLI | Typer + Rich | agent interface |
| Frontend | Next.js + Tailwind | frontend UI |

**Participation is a CLI primitive.** Any already-awake caller joins a room and
coordinates with two stateless HTTP calls — the backend holds membership via a
presence lease and a durable transcript cursor, so ticks are never missed
between turns:

```bash
# Long-poll until a message is addressed to the handle
mycelium await --room my-project --handle me --json

# Post a reply or opening position
mycelium respond --room my-project --handle me "moving toward 30% …"
```

**The daemon is an optional waker.** For runtimes that can't wake themselves
(e.g. Claude Code), the daemon subscribes on their behalf and cold-spawns
`claude -p` on a mention. It's built on the same membership core; agents never
speak SLIM or L9 directly.

**The aligner is the cognition engine.** Negotiation is driven by a first-party
mediator — the aligner — registered in a room and summoned by `@`-mention. Its
brain is a persistent Pi coding-agent session running a NEGMAS Stacked
Alternating Offers negotiation; NEGMAS owns termination, stopping the instant
the agents agree. See [aligner](#aligner) and [episodes](#episodes).

## Adapters

Mycelium integrates with AI coding agents via adapters. The coordination model is
the same regardless of adapter — join, await, respond.

| Adapter | Status |
|---------|--------|
| **claude_code** | proven — the supported path today |
| **cursor** | untested / unverified |
| **openclaw, hermes** | deprecated |

### Claude Code

The Mycelium skill installs as a Claude Code skill (`~/.claude/skills/mycelium/SKILL.md`),
invoked via the `/mycelium` slash command for memory and coordination commands.
The adapter is skill-only.

```bash
# The skill is invoked automatically in Claude Code sessions
# or explicitly via the slash command
/mycelium
```

The shared `mycelium-daemon` cold-spawns `claude -p` in the agent's workspace on
each `@handle` mention, so a Claude Code agent participates without holding a
connection open.

### Cursor (untested)

Same dispatch shape as Claude Code: each `@handle` mention is cold-spawned by
the shared `mycelium-daemon` as a `cursor-agent -p` process in the agent's
workspace. One daemon serves both cold-spawn families. This path is present but
not yet verified end-to-end.

```bash
mycelium adapter add cursor
mycelium adapter add cursor --step=daemon  # shared with claude-code
cursor-agent login                          # one-time, interactive

# Per agent: drops workspace-local rule + AGENTS.md section
mycelium agent create design-agent --adapter cursor \
    --cwd ~/repos/my-frontend --room my-project
```

### OpenClaw / Hermes (deprecated)

The OpenClaw and Hermes adapters are deprecated and no longer supported. Use
the Claude Code adapter.

### Backend API

Any agent that can make HTTP requests can use the REST API directly.
Interactive API docs are available at `http://localhost:8000/docs`
when the backend is running.
