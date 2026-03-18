# mycelium

<div align="center">
  <img src="docs/banner.png?v=2" alt="mycelium" width="800" />
</div>

<p align="center">
  <a href="https://github.com/mycelium-io/mycelium/actions/workflows/ci.yml?branch=main"><img src="https://img.shields.io/github/actions/workflow/status/mycelium-io/mycelium/ci.yml?branch=main&style=for-the-badge" alt="CI status"></a>
  <a href="https://github.com/mycelium-io/mycelium/releases"><img src="https://img.shields.io/github/v/release/mycelium-io/mycelium?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white&style=for-the-badge">
</p>

<div align="center">
  <em>A coordination layer for multi-agent systems — shared rooms, persistent memory, and semantic negotiation, built on the Internet of Cognition.</em>
</div>

---

## The Problem

AI agents are powerful individually, but they can't think together. When multiple agents work on the same problem, there's no shared memory, no way to negotiate trade-offs, and no context that persists across sessions. Every conversation starts from zero.

## What Mycelium Does

Mycelium gives agents **rooms** to coordinate in, **persistent memory** that compounds across sessions, and a **CognitiveEngine** that mediates negotiation so agents never have to talk directly to each other.

```bash
# Agent 1 shares context in a persistent room
mycelium memory set "position/julia" "I think we should use REST, not GraphQL" --handle julia-agent

# Agent 2 (hours later, different session) reads and adds their perspective
mycelium memory search "API design decisions"
mycelium memory set "position/selina" "Agree on REST, but we need pagination standards" --handle selina-agent

# CognitiveEngine synthesizes when enough context accumulates
mycelium room synthesize
```

When agents need to agree on something in real time, they join a sync room and CognitiveEngine runs structured negotiation:

```bash
mycelium room join --handle julia-agent -m "budget=high, scope=full"
# CognitiveEngine drives propose/respond rounds until consensus
```

## How It Works

Three pillars from the [Internet of Cognition](https://outshift.cisco.com) architecture:

**1. Coordination Protocol** (Shared Intent) — Rooms with a state machine (`idle → waiting → negotiating → complete`). CognitiveEngine orchestrates multi-issue negotiation via NegMAS. Agents respond to structured proposals; they never address each other directly.

**2. Persistent Memory** (Shared Context) — Namespaced key-value store with semantic vector search. Memories persist across sessions, accumulate across agents, and are searchable by meaning, not just keywords. Backed by AgensGraph + pgvector.

**3. Knowledge Graph** (Collective Innovation) — Two-stage LLM extraction turns agent conversations into structured concepts and relationships in an openCypher graph. CognitiveEngine queries this to inform future negotiations.

## Room Modes

| Mode | When to use | How it works |
|------|------------|--------------|
| **sync** | Agents are online together, need to agree now | 60s join window → NegMAS negotiation → consensus |
| **async** | Agents contribute across sessions | Persistent namespace, CognitiveEngine synthesizes on trigger |
| **hybrid** | Accumulate context, then negotiate | Write memories, then escalate to sync when ready |

## Quick Start

```bash
# Install
pip install mycelium-cli
mycelium install

# Create a room and start sharing context
mycelium room create my-project --mode async
mycelium room set my-project
mycelium memory set "context/goal" "Build a REST API for the new service"
mycelium memory set "decision/db" "PostgreSQL with pgvector for embeddings"

# Search what's been shared
mycelium memory search "database decisions"

# See everything in the room
mycelium memory ls
```

## Architecture

Everything runs on a single **AgensGraph** instance (PostgreSQL 16 fork):
- SQL tables for rooms, sessions, messages, memories
- openCypher for the knowledge graph
- pgvector for semantic memory search
- LISTEN/NOTIFY for real-time SSE streaming

No external message broker, no separate vector DB, no Redis. One database.

```
mycelium-cli/         CLI + adapters (OpenClaw, Claude Code)
fastapi-backend/      FastAPI coordination engine
mycelium-client/      Generated typed OpenAPI client
```

## Adapters

Mycelium integrates with AI coding agents via adapters:

**Claude Code** — Lifecycle hooks capture tool use and context automatically. The mycelium skill provides memory and coordination commands.

```bash
mycelium adapter add claude-code
```

**OpenClaw** — Plugin + hooks for the OpenClaw agent runtime. Same coordination protocol, same memory API.

```bash
mycelium adapter add openclaw
```

## Metrics

Mycelium includes a lightweight metrics collector that receives OpenTelemetry data from OpenClaw's `diagnostics-otel` plugin and displays it in rich terminal tables.

### Quick Start

```bash
# Install the metrics dependencies
cd mycelium-cli && pnpm run build:metrics

# Configure OpenClaw to export telemetry
mycelium adapter add openclaw --step=otel

# Start the OTLP collector (background)
mycelium metrics collect --bg

# View metrics
mycelium metrics show
mycelium metrics show --workspace   # include per-file workspace breakdown
mycelium metrics show --json        # raw JSON output
```

### What It Shows

**Overall Summary** — cumulative token usage, cost, message counts, run durations, and queue health.

**Per-Agent Breakdown** — tokens, cost, session counts, and workspace file sizes for each agent.

**Recent Sessions** — per-session detail including model, token counts, LLM round-trip count (turns), and timestamps.

**Workspace Files** — file-by-file size breakdown of each agent's `~/.openclaw` workspace directory (with `--workspace`).

### Field Reference

| Field | Description | Source |
|-------|-------------|--------|
| Total tokens | Cumulative LLM tokens across all agents | OTLP counter |
| &nbsp;&nbsp;input | Tokens sent to the model (prompts + context) | OTLP counter |
| &nbsp;&nbsp;output | Tokens generated by the model | OTLP counter |
| &nbsp;&nbsp;cache read | Tokens served from prompt cache (reduced cost) | OTLP counter |
| &nbsp;&nbsp;cache write | Tokens written to prompt cache | OTLP counter |
| Cost (openclaw) | Estimated cost as reported by OpenClaw | OTLP counter (unverified) |
| Messages | Total messages processed by the gateway | OTLP counter |
| Avg run | Mean agent run duration | OTLP histogram |
| Queue depth | Average and max pending messages in queue | OTLP histogram |
| Turns | LLM round-trips per session (how many API calls a task took) | OTLP trace spans |
| Workspace | Total file size in the agent's workspace directory | Filesystem |
| Gateway | Current gateway status | `openclaw status` |

### Commands

| Command | Description |
|---------|-------------|
| `mycelium metrics collect` | Start the OTLP receiver (foreground) |
| `mycelium metrics collect --bg` | Start the OTLP receiver in the background |
| `mycelium metrics stop` | Stop the background collector |
| `mycelium metrics show` | Display metrics tables |
| `mycelium metrics reset` | Delete collected metrics data |

The collector listens on port 4318 (OTLP standard). Override with `--port` or `MYCELIUM_METRICS_PORT`.

## Development

```bash
cd fastapi-backend
uv sync --group dev
uv run pytest tests/                    # unit tests (SQLite)
DATABASE_URL=... uv run pytest tests/   # integration tests (AgensGraph)
```

Interactive API docs at `http://localhost:8000/docs` when the backend is running.

## Built On

- [Internet of Cognition](https://outshift.cisco.com) — Outshift by Cisco
- [NegMAS](https://negmas.readthedocs.io/) — Multi-issue negotiation
- [AgensGraph](https://github.com/skaiworldwide-oss/agensgraph) — Multi-model graph database
- [FastAPI](https://fastapi.tiangolo.com/) + [pgvector](https://github.com/pgvector/pgvector) + [fastembed](https://github.com/qdrant/fastembed)
