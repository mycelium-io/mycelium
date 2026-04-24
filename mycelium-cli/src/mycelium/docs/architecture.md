# Architecture

## Deployment Modes

Mycelium supports two deployment modes. The backend and database are
identical in both — what differs is *where the agents run* and *how they
reach the backend*.

### 1. Single-device (default)

Everything — backend, database, agents, and CLI — runs on one machine,
typically a developer's laptop. This is what `mycelium install` sets up
out of the box. No network configuration, no remote services to point
at, no shared infrastructure required. Agents talk to `localhost:8000`.

This is the primary deployment target. Use it when one person (or one
machine) owns the whole agent workflow.

### 2. Hub-and-spoke (small teams)

A second, optional mode for small teams that want to share memory, rooms,
and coordination state across machines. One machine runs the full backend
stack (the **hub**); other machines run only the CLI + agents (**spokes**)
and connect to the hub over HTTPS/SSE.

| Role  | What runs locally | When to use |
|-------|-------------------|-------------|
| **Hub**   | Full backend stack — FastAPI + AgensGraph (Postgres 16) + (optionally) the CFN management plane and cognition fabric node services. | The team's shared coordination server. One per team. |
| **Spoke** | CLI + agents only. Talks to a remote hub via HTTPS / SSE. No Docker containers, no local database. | Each teammate's laptop. Agents on the spoke participate in shared rooms hosted by the hub. |

Use this when a small team wants one place to look at shared memory,
results, and ongoing coordinations — without each member running their
own isolated stack.

`mycelium doctor` auto-detects which mode you're in by looking at
`server.api_url` in `~/.mycelium/config.toml`: if it points to
`localhost`/`127.0.0.1`, you're a hub; otherwise a spoke. The detection
just tells the doctor which checks are relevant — Docker containers,
runtime config drift, and the local CFN mgmt plane only matter on a hub.
Override the auto-detection with:

```bash
mycelium doctor --mode hub     # force hub checks
mycelium doctor --mode spoke   # force spoke checks (skip local-only)
mycelium doctor --mode auto    # default — detect from api_url
```

> **Terminology note.** Earlier releases used "leaf" instead of "spoke".
> The CLI flag `--mode leaf` was renamed to `--mode spoke` in a hard
> cutover (no alias) to align with the standard hub-and-spoke vocabulary.
> If you have scripts that pass `--mode leaf`, update them to `--mode spoke`.

## Stack

Everything runs on a single **AgensGraph** instance — a PostgreSQL 16 fork
with multi-model support. No external message broker, no separate vector database.

| Layer | Technology | Used for |
|-------|-----------|----------|
| SQL | AgensGraph (PG 16) | rooms, sessions, messages, memories |
| Graph | openCypher (AgensGraph) | knowledge graph — concepts, relationships |
| Vector | pgvector | semantic search on memory embeddings |
| Real-time | LISTEN/NOTIFY → asyncpg → SSE | live watch stream |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 384-dim local embeddings, no API key |
| LLM | litellm | synthesis, extraction, negotiation (100+ providers) |
| Backend | FastAPI + asyncpg + SQLAlchemy | coordination engine API |
| CLI | Typer + Rich | agent interface |
| Frontend | Next.js + Tailwind | room viewer UI |

## Adapters

Mycelium integrates with AI coding agents via adapters. The coordination model is
the same regardless of adapter — join, await, respond.

### Claude Code

The Mycelium skill ships as a Claude Code hook set. Lifecycle hooks capture tool use
and context automatically. The `mycelium` slash command provides memory
and coordination commands inline.

```bash
# The skill is invoked automatically in Claude Code sessions
# or explicitly via the slash command
/mycelium
```

### OpenClaw

Plugin + hooks for the OpenClaw agent runtime. Same coordination model,
same memory API.

```bash
mycelium adapter add openclaw

# Allow agents to run mycelium commands without manual approval
# For specific agents (recommended):
openclaw approvals allowlist add --agent "<agent-id>" "~/.local/bin/mycelium"
# Or for all agents (convenient but less restrictive):
openclaw approvals allowlist add --agent "*" "~/.local/bin/mycelium"

# Restart the gateway to pick up the plugin
openclaw gateway restart
```

### Containerized gateway

If OpenClaw runs inside Docker (VPS, self-hosted, Docker Compose), pass the
container name so Mycelium stages assets and runs install commands inside the
container via `docker exec`:

```bash
mycelium adapter add openclaw --openclaw-container openclaw-gateway-1

# Or set via env var
export OPENCLAW_CONTAINER=openclaw-gateway-1
mycelium adapter add openclaw
```

This handles path resolution, file ownership (root UID), and `openclaw.json`
load-path configuration automatically.

### Backend API

Any agent that can make HTTP requests can use the REST API directly.
Interactive API docs are available at `http://localhost:8888/docs`
when the backend is running.
