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

## The Problem

When multiple autonomous agents such as OpenClaw work on the same problem, coordination is harder than it looks. There's no shared memory that persists across conversations, no structured way to negotiate trade-offs, and no guarantee that agents will reach a consistent answer rather than contradicting each other.

This problem exists in some form regardless of your OpenClaw deployment pattern — whether you are running peer agents across one or more gateways, or subagents under a single orchestrator.

## What Mycelium Does

- **Alignment** — When agents need to agree, a session is spawned within the room. The CognitiveEngine orchestrates multi-issue negotiation via [NegMAS](https://negmas.readthedocs.io/) through a structured state machine (`idle → waiting → negotiating → complete`), polling every agent, synthesizing positions into proposals, and iterating until the team reaches a single authoritative output. Every agent has a voice; the result is one shared answer, not parallel outputs a human has to reconcile. This is infrastructure, not a prompt pattern.
- **Alignment memory** — Rooms are folders. Memories are markdown files at `.mycelium/rooms/{room}/{namespace}/{key}.md` — readable and writable by any OpenClaw agent with file I/O. Past alignments are stored and surfaced to agents and the CognitiveEngine. Settled questions are not re-litigated unless conditions genuinely change. Dead ends are logged so no agent repeats them. Memories accumulate across agents and conversations and are searchable by meaning via a pgvector index in AgensGraph. Without this, alignment decisions get lost in the noise and every OpenClaw conversation starts from zero.
- **Peer collaboration environment** — OpenClaw peers or subagents collaborate in shared rooms out of the box, across a single gateway or multiple gateways. Rooms are provisioned automatically with scoped memory namespaces. Any agent joining a room runs `mycelium catchup` and instantly inherits everything the swarm has learned — decisions made, what failed, open questions, recommended next actions. No repeated context-setting. Without Mycelium, peer collaboration requires configuring shared memory paths and handling conflicts and governance patterns explicitly. With Mycelium, agents join a room and the environment is there.

> **Current scope:** Right now, Mycelium delivers alignment and alignment memory. The project intends to extend this into the full coordination stack — multi-objective negotiation, task allocation, drift detection, and more.


### How It Works

Mycelium gives OpenClaw agents **rooms** to coordinate in, **persistent memory** that accumulates within a room, and a **CognitiveEngine** that mediates negotiation so every agent has a voice and the team arrives at a single shared answer.

```bash
# Agent 1 shares context in a persistent room
mycelium memory set "position/julia" "I think we should use REST, not GraphQL" --handle julia-agent

# Agent 2 (hours later, different session) reads and adds their perspective
mycelium memory search "API design decisions"
mycelium memory set "position/selina" "Agree on REST, but we need pagination standards" --handle selina-agent

# CognitiveEngine synthesizes when enough context accumulates
mycelium synthesize
```

When agents need to agree in real time, they spawn a session within a room and the CognitiveEngine runs structured negotiation:

```bash
mycelium session join --handle julia-agent -m "budget=high, scope=full"
# CognitiveEngine drives propose/respond rounds until consensus
```

> **Note:** Mycelium uses "session" to mean a structured negotiation round within a room — not an OpenClaw conversation turn. These are different things.

## Alternatives

Your options without Mycelium are native OpenClaw with collaboration prompts, or open-source projects that construct entire agent teams such as getclawe/clawe, ClawTeam-OpenClaw,  antfarm, and many others. These provide collaboration primitives — delegation, handoffs, and shared memory — but leave the hard problems of structured consensus, governed memory, and consistent outcomes to the developer to solve. 

The difference: they make it *possible* for autonomous agents to collaborate. Mycelium makes that collaboration more *structured, efficient, and observable.*

In the peer pattern, OpenClaw or other autonomous agents have no native way to reach consensus — coordination collapses into ping-pong messaging or prompt engineering that doesn't scale. In the subagent pattern, the orchestrator can synthesize a final answer, but there's no shared memory that persists across conversations, no structured record of why decisions were made, and no mechanism for subagents to surface conflicts upstream.

Across both patterns, without Mycelium:

- Agents contradict each other with no resolution mechanism, or the orchestrator/operator/parent agent arbitrates unilaterally
- Past decisions are added to memory but not reliably referenced or surfaced in future coordiantion
- Shared memory exists but isn't governed — agents can't reliably surface what was decided and why
- Coordination is held together by prompt engineering or user intervention, not infrastructure

If your workflow needs one coherent answer from multiple autonomous agents, you'll build this coordination layer yourself or you'll use Mycelium.

## Who It's For and Why We're Building It

**Mycelium is explicitly built for developers** who are running multiple agents, especially OpenClaw, and have hit — or can clearly see — the point where unstructured coordination breaks down.

It's for you if:

- You have experienced an OpenClaw agent conflicting with another agent's output, or not listening to each other
- You want to hand the coordination problem to infrastructure you can trust, not prompt-engineer your way around it

**Mycelium is not yet the right fit if:**

- You are running a simple orchestrator → subagent chain where the orchestrator has full authority and no peer coordination is needed
- You haven't yet hit coordination complexity — the value becomes obvious once you've felt the cost of agents contradicting each other or losing context across conversations

### Principles:

- **Coordination is an infrastructure problem, not a prompting problem.** If your OpenClaw agents need to agree with each other, a cleverer system prompt is not the answer. Prompt-based coordination works until it doesn't — and when it breaks, it breaks silently, in production, in ways that are hard to trace. Infrastructure fails loudly and can be fixed. We are building infrastructure.
- **Decisions should aid future coordination.** When agent teams reach a decision, that decision shouldn't disappear into the noise of a conversation log. It should be available to every future coordination activity — across agents, across conversations, and across rooms. The system should get more consistent and more informed over time. Most multi-agent systems treat each decision as an isolated event. We treat them as inputs to everything that follows.
- **Peer autonomous agents are going to bec ome increasingly more prevalent.** The orchestrator model works well for many things — one agent with authority, others that execute. But as agents become more capable and more autonomous, peer agent architectures — where multiple autonomous agents coordinate as equals, without a single point of authority — will become increasingly common. The tooling for that pattern is still inadequate. Mycelium is built for it.

If you want to design every interaction between your agents from scratch, native OpenClaw with user intervention is the right tool. Mycelium is for developers who want to hand the coordination problem to infrastructure and focus on what their agents actually do.

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

Mycelium integrates with OpenClaw and Claude Code via adapters:

**OpenClaw** — Plugin + hooks for the OpenClaw agent runtime. Same coordination protocol, same memory API.

```bash
mycelium adapter add openclaw
```

**Claude Code** — Lifecycle hooks capture tool use and context automatically. The mycelium skill provides memory and coordination commands.

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

- [ioc-cfn-mgmt-plane](https://outshift.cisco.com) + [ioc-cfn-svc](https://outshift.cisco.com) — Agent registration and fabric orchestration, from Outshift by Cisco [Internet of Cognition](https://outshift.cisco.com/internet-of-cognition) concepts
- [NegMAS](https://negmas.readthedocs.io/) — Multi-issue negotiation
- [AgensGraph](https://github.com/skaiworldwide-oss/agensgraph) — Multi-model graph database
- [FastAPI](https://fastapi.tiangolo.com/) + [pgvector](https://github.com/pgvector/pgvector) + [sentence-transformers](https://www.sbert.net/)

