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
  <em>A coordination layer for multi-agent systems — shared rooms, persistent memory, and semantic negotiation.</em>
</div>

---

## The Problem

AI agents are powerful individually, but they can't think together. When multiple agents work on the same problem, there's no shared memory, no way to negotiate trade-offs, and no context that persists across sessions. Every conversation starts from zero.

## What Mycelium Does

Mycelium gives agents **rooms** to coordinate in, **persistent memory** that accumulates within a room, and a **CognitiveEngine** that mediates negotiation so every agent has a voice and the team arrives at a single shared answer.

```bash
# Agent 1 shares context in a persistent room
mycelium memory set "position/julia" "I think we should use REST, not GraphQL" --handle julia-agent

# Agent 2 (hours later, different session) reads and adds their perspective
mycelium memory search "API design decisions"
mycelium memory set "position/selina" "Agree on REST, but we need pagination standards" --handle selina-agent

# CognitiveEngine synthesizes when enough context accumulates
mycelium synthesize
```

When agents need to agree on something in real time, they spawn a session within a room and CognitiveEngine runs structured negotiation:

```bash
mycelium session join --handle julia-agent -m "budget=high, scope=full"
# CognitiveEngine drives propose/respond rounds until consensus
```

## How It Works

**1. Shared Intent** — When agents need to agree, a session is spawned within the room. CognitiveEngine orchestrates multi-issue negotiation via NegMAS through a structured state machine (`idle → waiting → negotiating → complete`). Agents respond to structured proposals and reach a single consensus — every agent has a voice, and the result is one shared answer.

**2. Shared Memory** — Rooms are folders. Memories are markdown files at `.mycelium/rooms/{room}/{namespace}/{key}.md`. Any agent with file I/O can read and write room memory directly — the CLI is sugar. Memories accumulate across agents and sessions, and are searchable by meaning via a pgvector index in AgensGraph.

**3. Shared Context** — Any agent joining a room runs `mycelium catchup` and instantly inherits everything the swarm has learned — decisions made, what failed, open questions, recommended next actions. No repeated context-setting. Intelligence compounds instead of resetting.

## Quick Start

```bash
# Install
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# Create a room and start sharing context
mycelium room create my-project
mycelium room use my-project
mycelium memory set "context/goal" "Build a REST API for the new service"
mycelium memory set "decisions/db" "AgensGraph with pgvector for embeddings"

# Search what's been shared
mycelium memory search "database decisions"

# See everything in the room
mycelium memory ls
```

## Architecture

**Memories live on the filesystem** — rooms are folders, memories are markdown files with YAML frontmatter at `.mycelium/rooms/{room}/{key}.md`. This is the source of truth. Direct writes (cat, editor, agent file I/O) always work; run `mycelium reindex` to refresh the search index after bypassing the CLI.

**AgensGraph** (PostgreSQL 16 fork) is the coordination and search backend:
- Rooms, sessions, messages, subscriptions — coordination state
- pgvector embeddings for semantic memory search (384-dim, local, no API key)
- LISTEN/NOTIFY → SSE (Server-Sent Events) for real-time streaming

No external message broker, no separate vector DB, no Redis. One database.

**Rooms are git-friendly** — commit `.mycelium/rooms/` to share context across machines. Agents on different machines pull the folder and inherit the room's full memory.

Room folders use standard namespaces:

```
.mycelium/rooms/{room}/
├── decisions/    Why choices were made
├── status/       Current state of things
├── context/      Background & constraints
├── work/         In-progress and completed work
├── procedures/   How-to guides and runbooks
└── log/          Events and observations
```

Repo layout:

```
.mycelium/            Memory storage (rooms are folders, memories are markdown files)
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
| Run duration | Agent run duration: avg/min/max in seconds | OTLP histogram |
| Msg duration | Message processing duration: avg/min/max in seconds | OTLP histogram |
| Queue depth | Pending messages in queue: avg/min/max | OTLP histogram |
| Queue wait | Time messages wait in queue: avg/min/max in seconds | OTLP histogram |
| Total turns | Total LLM round-trips across all sessions | OTLP trace spans |
| Turns | LLM round-trips per agent (how many API calls tasks took) | OTLP trace spans |
| Avg Run | Per-agent mean run duration in seconds | OTLP histogram |
| Queue | Per-agent queue depth: avg/max | OTLP histogram |
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

Mycelium builds on OSS projects we found invaluable in this space:

- [ioc-cfn-mgmt-plane](https://outshift.cisco.com) + [ioc-cfn-svc](https://outshift.cisco.com) — Agent registration and fabric orchestration, from Outshift by Cisco [Internet of Cognition](https://outshift.cisco.com/internet-of-cognition) concepts
- [NegMAS](https://negmas.readthedocs.io/) — Multi-issue negotiation
- [AgensGraph](https://github.com/skaiworldwide-oss/agensgraph) — Multi-model graph database
- [FastAPI](https://fastapi.tiangolo.com/) + [pgvector](https://github.com/pgvector/pgvector) + [sentence-transformers](https://www.sbert.net/)
