# mycelium

<div align="center">
  <img src="docs/banner.png?v=2" alt="mycelium" width="800" />
</div>

<p align="center">
  <a href="https://github.com/mycelium-io/mycelium/actions/workflows/ci.yml?branch=main"><img src="https://img.shields.io/github/actions/workflow/status/mycelium-io/mycelium/ci.yml?branch=main&style=for-the-badge" alt="CI status"></a>
  <a href="https://github.com/mycelium-io/mycelium/releases"><img src="https://img.shields.io/github/v/release/mycelium-io/mycelium?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white&style=for-the-badge">
</p>

<div align="center">
  <em>A coordination layer for multi-agent systems — shared rooms, persistent memory, and semantic negotiation.</em>
</div>

---

<div align="center">

https://github.com/user-attachments/assets/b4a60f86-2bc8-4515-8b7a-45a06df5df97

<em>install → coordinate → plan → work.</em>

</div>

---

## The Problem

Very little exists for agents operating as autonomous peers on a shared mission. To get reliable results, practitioners reach for an orchestrator, a predefined workflow, or a tightly defined handoff structure. Users attempting peer agent coordination have to manually construct scaffolding for memory sharing and context passing. And even then, without coordination infrastructure, the result is AI theatre — agents that talk over each other, repeat work already done, fail to recognise disagreement, and fail to negotiate trade-offs.

## Who Mycelium Is For

Mycelium is built for autonomous agents operating as peers — no predefined workflow, no centralized supervisor, no hierarchy. That includes agents like OpenClaw or Claude Code — given a mission and a tool allowlist, left to plan and execute without step-by-step human approval.

Alignment pays off at 3+ agents. At three it improves decision quality over uncoordinated approaches; at four or more it's often the difference between converging on a shared answer and not converging at all.

If your system has a central orchestrator routing tasks to worker agents, you probably don't need Mycelium — your orchestrator is already the coordination layer. Mycelium is for the case where there is no orchestrator, and you don't want one.

## What Mycelium Does

Mycelium provides coordination functions for autonomous agents operating as peers. The first: alignment — agreeing on a shared position at the start of a mission or any point during it — so decisions don't get re-litigated, work doesn't get duplicated, and every agent that joins inherits what the others already know.

Mycelium gives agents **rooms** to coordinate in, **persistent memory** that accumulates within a room, and a **CognitiveEngine** that mediates negotiation so every agent has a voice and the team arrives at a single shared answer.

**Do you need an agent runtime?** Yes. Mycelium coordinates agents; it doesn't replace them. You bring the agents — Claude Code, Cursor, or OpenClaw — and Mycelium is the room, shared memory, and negotiator they meet in. *(You can use the memory layer solo with no runtime, but coordination is the point.)*

```bash
# Agent 1 shares context in a persistent room
mycelium memory set "position/julia" "I think we should use REST, not GraphQL" --handle julia-agent

# Agent 2 (hours later, different session) reads and adds their perspective
mycelium memory search "API design decisions"
mycelium memory set "position/selina" "Agree on REST, but we need pagination standards" --handle selina-agent
```

When agents need to agree on something in real time, they spawn a session within a room and CognitiveEngine runs structured negotiation:

```bash
mycelium session join --handle julia-agent -m "budget=high, scope=full"
# CognitiveEngine drives propose/respond rounds until consensus
# on consensus, the agreement is compiled into the room's shared plan
mycelium plan tasks   # the - [ ] checklist the team now executes against
```

> **Note:** Mycelium uses "session" to mean a structured negotiation round within a room — not an agent conversation turn.

## How It Works

**1. Alignment** — When agents need to agree, a session is spawned within the room. CognitiveEngine orchestrates multi-issue negotiation through a structured state machine (`idle → waiting → negotiating → complete`). Agents respond to structured proposals and reach a single consensus — every agent has a voice, and the result is one shared answer, not parallel outputs a human has to reconcile. From that consensus Mycelium compiles a **shared plan** — a `- [ ]` checklist at `plan/tasks.md` the whole team executes against. The arc is one line: join → negotiate → **plan** → work. The negotiation decides *what*; the plan is *how the team carries it out*.

**2. Room Memory** — Rooms are folders. Memories are markdown files at `~/.mycelium/rooms/{room}/{namespace}/{key}.md`. Any agent with file I/O can read and write room memory directly — the CLI is sugar. Memories accumulate across agents and sessions, and are searchable by meaning via a pgvector index in AgensGraph.

**3. Peer Collaboration Environment** — Any agent joining a room reads from `~/.mycelium/rooms/{room}/` and instantly inherits everything the swarm has learned — decisions made, what failed, open questions, the room's shared plan. No repeated context-setting. Intelligence compounds instead of resetting.

## Quick Start

You'll need **Docker**, an **LLM API key** (required for negotiation — agents
can't reach consensus without one), and **at least one agent runtime** (Claude
Code, Cursor, or OpenClaw).

```bash
# 1. Install the CLI
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# 2. Set up the stack (pulls images, prompts for your LLM key, writes ~/.mycelium/config.toml)
mycelium install

# 3. Create a room — a shared space for agents, memory, and coordination
mycelium room create my-project
mycelium room use my-project

# 4. Add agents to the room (one per role)
mycelium agent create planner --adapter openclaw \
    --description "Sprint planner, optimizes for shipping speed"
mycelium agent create builder --adapter openclaw \
    --description "Implementer, optimizes for correctness"
#    (claude-code and cursor agents work too — see Adapters below)

# 5. Put them to work. When agents need to agree, CognitiveEngine negotiates a
#    single shared answer and compiles it into the room's plan.
mycelium agent invoke planner "draft a plan for the Q3 migration"
mycelium plan tasks        # the shared - [ ] checklist the team executes against
```

Rooms are also persistent memory — anything you write is searchable by meaning
and inherited by every agent that joins:

```bash
mycelium memory set "decisions/db" "AgensGraph with pgvector for embeddings"
mycelium memory search "database decisions"
mycelium memory ls
```

## Architecture

**Memories live on the filesystem** — rooms are folders, memories are markdown files with YAML frontmatter at `~/.mycelium/rooms/{room}/{key}.md`. This is the source of truth. Direct writes (cat, editor, agent file I/O) always work; run `mycelium reindex` to refresh the search index after bypassing the CLI.

**AgensGraph** (PostgreSQL 16 fork) is the coordination and search backend:
- Rooms, sessions, messages, subscriptions — coordination state
- pgvector embeddings for semantic memory search (384-dim, local, no API key)
- LISTEN/NOTIFY → SSE (Server-Sent Events) for real-time streaming

No external message broker, no separate vector DB, no Redis. One database.

**Rooms are git-friendly** — commit `~/.mycelium/rooms/` to share context across machines. Agents on different machines pull the folder and inherit the room's full memory.

**Deployment modes** — by default everything runs on a single device (your laptop): backend, database, agents, and CLI all on `localhost`. That's the primary target and what `mycelium install` sets up out of the box. For small teams that want to share memory and coordination state, Mycelium also supports a hub-and-spoke mode: one machine runs the backend (the **hub**), other teammates run only the CLI + agents (**spokes**) pointing at it over HTTPS/SSE. `mycelium doctor` auto-detects which mode you're in based on `server.api_url`; pass `--mode hub` or `--mode spoke` to override. See [`docs/architecture.md`](mycelium-cli/src/mycelium/docs/architecture.md#deployment-modes) for details.

Room folders use standard namespaces:

```
~/.mycelium/rooms/{room}/
├── plan/         Shared checklist — compiled from negotiation consensus
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

Mycelium works with any agent that can make HTTP requests via the REST API. Native adapters are available for:

**OpenClaw** — Two plugins + hooks for the OpenClaw agent runtime. The `mycelium` plugin delivers SSE-based coordination ticks that wake agents automatically when it's their turn. The `mycelium-channel` plugin turns any Mycelium room into an addressed message bus — agents DM each other via `@handle` mentions through the room itself, with no external chat platform required.

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

**Claude Code** — Installs the `mycelium` skill (`~/.claude/skills/mycelium/SKILL.md`), giving Claude Code memory and coordination commands via `/mycelium`. (On reinstall it also backs up `~/.claude/settings.json` and clears any stale hook wiring from earlier versions.)

```bash
mycelium adapter add claude-code
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

- [ioc-cfn-mgmt-backend-svc](https://github.com/outshift-open/ioc-cfn-mgmt-backend-svc) + [ioc-cfn-cognition-engines](https://github.com/outshift-open/ioc-cfn-cognition-engines) + [ioc-cognition-fabric-node-svc](https://github.com/outshift-open/ioc-cognition-fabric-node-svc) — Agent registration and fabric orchestration, from Outshift by Cisco
- [NegMAS](https://negmas.readthedocs.io/) — Multi-issue negotiation (inside the Cognition Fabric)
- [AgensGraph](https://github.com/skaiworldwide-oss/agensgraph) — Multi-model graph database
- [FastAPI](https://fastapi.tiangolo.com/) + [pgvector](https://github.com/pgvector/pgvector) + [fastembed](https://github.com/qdrant/fastembed)
