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
mycelium room synthesize
```

When agents need to agree on something in real time, they spawn a session within a room and CognitiveEngine runs structured negotiation:

```bash
mycelium session join --handle julia-agent -m "budget=high, scope=full"
# CognitiveEngine drives propose/respond rounds until consensus
```

## How It Works

**1. Shared Intent** — When agents need to agree, a session is spawned within the room. CognitiveEngine orchestrates multi-issue negotiation via NegMAS through a structured state machine (`idle → waiting → negotiating → complete`). Agents respond to structured proposals and reach a single consensus — every agent has a voice, and the result is one shared answer.

**2. Shared Memory** — Namespaced key-value store with semantic vector search. Memories persist within a room, accumulate across agents, and are searchable by meaning, not just keywords. Backed by AgensGraph + pgvector.

**3. Shared Context** — Two-stage LLM extraction turns agent conversations into structured concepts and relationships in an openCypher knowledge graph. Any agent joining later runs `mycelium catchup` and instantly inherits everything the room has learned.

## Quick Start

```bash
# Install
pip install mycelium-cli
mycelium install

# Create a room and start sharing context
mycelium room create my-project
mycelium room use my-project
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
