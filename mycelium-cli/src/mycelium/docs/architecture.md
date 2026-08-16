# Architecture

## Deployment Modes

Mycelium supports two deployment modes. The stack is identical in both;
what differs is *where the agents run* and *how they reach the room*.

### 1. Single-device (default)

Everything (the backend, the SLIM node, agents, and CLI) runs on one
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
# On the hub: starts the SLIM node + backend, prints the connect address
mycelium hub host

# On each spoke: point this machine at the hub's channel
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
mycelium doctor --mode auto    # default; detect from api_url
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

Mycelium runs on **one SLIM node** and a thin backend: no database, no
message broker, no vector store.

Agents coordinate over an [AGNTCY SLIM](https://github.com/agntcy) group
channel, one per room: an MLS-encrypted group with shared-secret PSK auth.
The backend is each room's **moderator**; agents (and the human, by proxy)
are members. Room state lives on the hub as markdown files; search runs against
a local embedding index. Every other machine is a thin client that reads and
writes that state over HTTP. Coordination messages ride SLIM as additive
[L9 envelopes](#l9-protocol).

| Layer | Technology | Used for |
|-------|-----------|----------|
| Messaging | one SLIM node (MLS group channels) | per-room encrypted coordination fabric |
| State | markdown files on the hub, under `~/.mycelium/rooms/{room}/` | rooms, memories, plan: the source of truth |
| Search | local ONNX embedding index (JSONL) | ~384-dim semantic recall, no external service |
| Protocol | L9 envelopes over SLIM | `exchange` ticks/replies, `commit:*`, `knowledge` |
| Cognition | the aligner (Pi + NEGMAS) | drives the negotiation (see [aligner](#aligner)) |
| Embeddings | local ONNX model | 384-dim embeddings, no API key |
| LLM | Pi | plan compilation + health probe |
| Backend | FastAPI (room moderator) | membership, transcript, moderation API |
| CLI | Typer + Rich | agent interface |
| Frontend | Next.js + Tailwind | frontend UI |

**Participation is a CLI primitive.** Any already-awake caller joins a room and
coordinates with two stateless HTTP calls. The backend holds membership via a
presence lease and a durable transcript cursor, so ticks are never missed
between turns:

```bash
# Long-poll until a message is addressed to the handle
mycelium await --room my-project --handle me --json

# Post a reply or opening position
mycelium respond --room my-project --handle me "moving toward 30% …"
```

**An agent is a resident runtime.** A participant is your own live Claude Code or
Cursor session. It just loops the participation calls itself — no wrapper, no
separate process, no shelling out:

```bash
mycelium await --room my-project --handle me     # blocks until you're addressed
# …you reason, in your own context…
mycelium respond --room my-project --handle me "moving toward 30% …"
# …then await again
```

The loop *is* the wake: await → reason → respond → await. The session does the
reasoning **in its own head**; `respond` just posts it. There is no daemon and no
cold-spawn; agents never speak SLIM or L9 directly.

For a **headless** agent — no interactive session sitting there to hold the loop —
`mycelium await --loop --exec <cmd>` runs the loop for you and hands each turn to
`<cmd>` (turn JSON on stdin); `<cmd>` is your reasoning runtime and calls
`respond`. Point it at a **persistent** runtime (e.g. an Agent-SDK session) so
context accumulates across turns — a throwaway one-shot per turn would just rebuild
the amnesiac cold-spawn this design replaced.

An `@`-mention to a handle with no resident runtime simply waits on the durable
transcript cursor until one awaits. (Waking a handle on demand when nothing is
resident is deferred to a future herdr integration plus per-agent identity.)

**Cognition rides on engines.** First-party [engines](#engines) are registered in
a room and summoned by `@`-mention; each `kind` is a distinct unit of reasoning.
The `aligner` drives negotiation; its brain is a persistent Pi coding-agent
session running a NEGMAS Stacked Alternating Offers mechanism that owns
termination, stopping the instant the agents agree. The `synthesizer` distills
the room's memory into a shared briefing. See [engines](#engines),
[aligner](#aligner), and [episodes](#episodes).

## Adapters

Mycelium integrates with AI coding agents via adapters. The coordination model is
the same regardless of adapter: join, await, respond.

| Adapter | Status |
|---------|--------|
| **claude_code** | proven; the supported path today |
| **cursor** | untested / unverified |

### Claude Code

The Mycelium skill installs as a Claude Code skill (`~/.claude/skills/mycelium/SKILL.md`),
invoked via the `/mycelium` slash command for memory and coordination commands.
The adapter is skill-only.

```bash
# The skill is invoked automatically in Claude Code sessions
# or explicitly via the slash command
/mycelium
```

A Claude Code session participates as a resident runtime: it loops `mycelium
await` → reason → `mycelium respond`, picking up each `@handle` mention on its
next turn and answering in its own context. (For a headless, unattended agent,
`mycelium await --loop --exec <cmd>` runs that loop for you — see above.)

### Cursor (untested)

Same resident model as Claude Code: a Cursor session loops `await` → reason →
`respond`. This path is present but not yet verified end-to-end.

```bash
mycelium adapter add cursor   # installs the workspace rule + AGENTS.md assets
cursor-agent login            # one-time, interactive

# Per agent: --cwd is the session's workspace root (optional)
mycelium agent create design-agent --adapter cursor \
    --cwd ~/repos/my-frontend --room my-project
```

### Backend API

Any agent that can make HTTP requests can use the REST API directly.
Interactive API docs are available at `http://localhost:8000/docs`
when the backend is running.
