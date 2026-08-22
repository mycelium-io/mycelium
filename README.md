# mycelium

<div align="center">
  <img src="docs/banner.png?v=3" alt="mycelium" width="800" />
</div>

<p align="center">
  <a href="https://github.com/mycelium-io/mycelium/actions/workflows/ci.yml?branch=main"><img src="https://img.shields.io/github/actions/workflow/status/mycelium-io/mycelium/ci.yml?branch=main&style=for-the-badge" alt="CI status"></a>
  <a href="https://github.com/mycelium-io/mycelium/releases"><img src="https://img.shields.io/github/v/release/mycelium-io/mycelium?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white&style=for-the-badge">
</p>

<div align="center">
  <em>A coordination layer for multi-agent systems: shared rooms, persistent memory, and mediated negotiation over a SLIM node.</em>
</div>

---

<div align="center">

https://github.com/user-attachments/assets/5e7b41c8-f98a-4cf3-bb85-fe17d855de7a

<em>install → coordinate → plan → work.</em>

</div>

---

## The Problem

Very little exists for agents operating as autonomous peers on a shared mission. To get reliable results, practitioners reach for an orchestrator, a predefined workflow, or a tightly defined handoff structure. Users attempting peer agent coordination have to manually construct scaffolding for memory sharing and context passing. And even then, without coordination infrastructure, the result is AI theatre: agents that talk over each other, repeat work already done, fail to recognise disagreement, and fail to negotiate trade-offs.

## Who Mycelium Is For

Mycelium is built for autonomous agents operating as peers, with no predefined workflow, no centralized supervisor, and no hierarchy. That includes agents like Claude Code: given a mission and a tool allowlist, left to plan and execute without step-by-step human approval.

Alignment pays off at 3+ agents. At three it improves decision quality over uncoordinated approaches; at four or more it's often the difference between converging on a shared answer and not converging at all.

If your system has a central orchestrator routing tasks to worker agents, you probably don't need Mycelium: your orchestrator is already the coordination layer. Mycelium is for the case where there is no orchestrator, and you don't want one.

## Does It Work

Mycelium was evaluated across 14 decision scenarios in a controlled A/B study.
See [Evaluation Results](docs/evaluation.md) for the full findings.

## What Mycelium Does

Mycelium provides coordination functions for autonomous agents operating as peers. The first: alignment, agreeing on a shared position at the start of a mission or any point during it, so decisions don't get re-litigated, work doesn't get duplicated, and every agent that joins inherits what the others already know.

Mycelium gives agents **rooms** to coordinate in, **persistent memory** that accumulates within a room, and an **aligner** that mediates negotiation so every agent has a voice and the team arrives at a single shared answer.

**Two surfaces, one room, built for each other.** You and your agents
coordinate *together*:

- **You** work in the **UI**: create a room, add agents, hand them a mission, and watch them reach a shared decision and a plan, live.
- **Your agents** work through the **CLI**: they join the room, negotiate, and write to shared memory on their own (that's what the `mycelium` skill teaches them).

That's also why you need at least one **agent runtime** (Claude Code): the agents aren't an optional add-on, they're half the system.

```bash
# Agent 1 shares context in a persistent room
mycelium memory set "position/avery" "I think we should use REST, not GraphQL" --handle avery-agent

# Agent 2 (hours later, different session) reads and adds their perspective
mycelium memory search "API design decisions"
mycelium memory set "position/rowan" "Agree on REST, but we need pagination standards" --handle rowan-agent
```

When agents need to agree on something, one participant summons the aligner, and each agent takes turns responding until the team converges:

```bash
# Register the mediator once, then summon it on the open question
mycelium engine create aligner --kind aligner --room design
mycelium engine invoke aligner "converge on API design"

# Each participant loops: wait for its turn, then post a position
mycelium await   --room design --handle avery-agent --json
mycelium respond --room design --handle avery-agent "I can accept REST with pagination standards."

# On agreement the agreement is compiled into the room's shared plan
mycelium plan tasks   # the - [ ] checklist the team now executes against
```

## How It Works

**1. Alignment.** When agents need to agree, one participant summons the **aligner**, a first-party mediator that runs a real NEGMAS Stacked Alternating Offers negotiation. It discovers the issues from the agents' opening positions, brokers each round, addresses one agent at a time, interprets each reply, and stops the instant the agents agree. Every agent has a voice, and the result is one shared answer, not parallel outputs a human has to reconcile. From that consensus Mycelium compiles a **shared plan**: a `- [ ]` checklist at `plan/tasks.md` with `@handle` owners the whole team executes against. The arc is one line: summon → negotiate → **plan** → work. The negotiation decides *what*; the plan is *how the team carries it out*.

**2. Room Memory.** A room's memory is one store, held by the hub. Any agent reads and writes it with `mycelium memory set` / `get` / `ls` / `search` — from any machine, with nothing to sync and no copy to drift. Memories accumulate across agents and turns, and are searchable by meaning via an embedding index that runs on the hub, with no external service and no database.

**3. Peer Collaboration Environment.** Any agent joining a room reads that memory and instantly inherits everything the swarm has learned: decisions made, what failed, open questions, the room's shared plan. No repeated context-setting. Intelligence compounds instead of resetting.

## Quick Start

You'll need **Docker**, an **LLM API key** (agents can't negotiate without
one), and **at least one agent runtime** (Claude Code).

**Onboard your agent.** The fastest setup is to let an agent do it — paste
this prompt into Claude Code (or any agent runtime with a shell):

```text
Use curl to read https://mycelium-io.github.io/mycelium/agents.md and perform the setup to install Mycelium
```

The agent follows [agents.md](https://mycelium-io.github.io/mycelium/agents.md),
a setup runbook written for agents: it installs the CLI, brings up the stack,
and connects its own runtime as an adapter.

Or install by hand:

```bash
# 1. Install the CLI and bring up the stack
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install      # pulls images, prompts for your LLM key, writes ~/.mycelium/config.toml

# 2. Open the app: this is where you work
mycelium ui open
```

From the UI you:

1. **create a room** (a shared space for agents, memory, and the plan),
2. **add agents** to it (one per role),
3. **give them a mission** in the chat box and `@mention` them,
4. **watch** them negotiate live to a single shared answer that compiles into the room's **plan**.

Your agents drive that same room from the **CLI** on their own, waiting for
their turn, responding, and writing to shared memory (that's what the
`mycelium` skill teaches them). You don't run those by hand; they do.

Prefer to script the human side too? Every UI action has a CLI equivalent:

```bash
mycelium room create my-project && mycelium room use my-project
mycelium engine create aligner --kind aligner --room my-project
mycelium agent create planner --adapter claude-code --description "Sprint planner"
mycelium engine invoke aligner "converge on the Q3 migration plan"
mycelium plan tasks   # the shared - [ ] checklist the team executes against
```

## Architecture

**The hub holds the memory; everything else is a thin client.** On the hub, rooms are folders and memories are markdown files with YAML frontmatter at `~/.mycelium/rooms/{room}/{key}.md` — the source of truth, with search running against a **local embedding index** (~384-dim, on-device), no external vector service and no database. Every other machine keeps no replica: `mycelium memory` resolves against the hub over HTTP, so a read always reflects what the room actually says. (Operating the hub, direct file writes still work; run `mycelium memory reindex` to refresh the index after bypassing the CLI.)

**One SLIM node coordinates the room.** Agents coordinate over an [AGNTCY SLIM](https://github.com/agntcy/slim) group channel per room: MLS-encrypted end-to-end, with the node forwarding only ciphertext. An always-on thin FastAPI backend is each room's **moderator**; the agents (and you, by proxy) are members. There's no database, no message broker, no separate realtime service.

**Identity is a ladder, and it starts off.** Out of the box the channel key derives from a shared secret every host in the mesh sets alike — enough for a laptop or a trusted LAN, with no per-member identity. From there `slim.identity` climbs one rung: **SignerJwt** gives each member its own self-signed credential with no extra infrastructure, making members cryptographically distinct participants rather than holders of one shared key. Separately, an HTTP API JWT gate can be turned on for the backend. All of it is off by default, so the try-it path is never blocked by auth — and turning it on, rather than building it, is what's left before a hosted or multi-user deployment (revocation is the open piece).

**Participation is a CLI primitive.** Any already-awake caller joins a room and coordinates with two stateless calls: `mycelium await` long-polls until a message is addressed to its handle (the backend holds membership via a presence lease and a durable transcript cursor, so a tick is never missed between turns), and `mycelium respond` posts a reply or position. An agent participates as a **resident** runtime — your own live Claude Code session — kept woken with `mycelium await --loop --exec <cmd>`, which loops await → reason → respond. The loop *is* the wake: there's no daemon and no cold-spawn, so the session keeps its context between turns instead of starting over each time.

**Sharing is the live channel.** Two machines share a room by sharing the fabric: one runs `mycelium hub host`, the other runs `mycelium connect`, and both talk to the same room channel and the same memory store. Git can version or back up the hub's `~/.mycelium/` files, but it is not the sharing path — no room flow pushes or pulls over git. For a point-in-time copy, `mycelium room clone --from <api-url>` takes an HTTP snapshot.

**Mycelium speaks IOC L9.** Coordination rides SLIM as additive [Layer 9](https://github.com/outshift-open/ioc-protocols-models) epistemic envelopes (`exchange` for ticks/replies, `commit:converged|resolved|rejected`, `knowledge`) with episodes and causal message threading. Summoning the aligner opens an **episode**: a tagged, membership-scoped negotiation on the room's channel with its own record at `log/episodes/{id}.md` (the full causally-linked envelope chain), surfaced live in the UI protocol inspector. Agents can state confidence, cite evidence, and flag deference on replies; consensus gets measurable quality metrics. All of it is optional; agents never need to speak L9.

**Deployment modes.** By default everything runs on a single device (your laptop): backend, SLIM node, agents, and CLI all on `localhost`. That's the primary target and what `mycelium install` sets up out of the box. For small teams that want to share memory and coordination state, Mycelium supports a hub-and-spoke mode: one machine runs `mycelium hub host` to stand up the SLIM node and prints its address; teammates run `mycelium connect http://<hub-ip>:<port>` to point their CLI + agents at it. `mycelium doctor` auto-detects which mode you're in.

Room folders use standard namespaces:

```
~/.mycelium/rooms/{room}/
├── plan/         Shared checklist compiled from negotiation consensus
├── decisions/    Why choices were made
├── status/       Current state of things
├── context/      Background & constraints
├── work/         In-progress and completed work
├── procedures/   How-to guides and runbooks
└── log/          Events, observations, and episode records
```

Repo layout:

```
.mycelium/            Memory storage (rooms are folders, memories are markdown files)
mycelium-cli/         CLI + adapters
fastapi-backend/      FastAPI moderator + engines (aligner, synthesizer)
mycelium-client/      Generated typed OpenAPI client
mycelium-frontend/    Next.js UI
contracts/            Frozen JSON contracts shared across components
docs/                 Docs site + design notes
```

Each component directory carries its own README covering what lives inside it and the
boundaries worth knowing before changing anything there.

## Adapters

Mycelium reaches your agents through per-runtime adapters. An adapter doesn't run your
agent — it teaches the runtime you already use how to participate in a room. Support is
honest about maturity:

| Adapter | Status |
|---|---|
| `claude_code` | ✅ proven |
| `cursor` | ⚠️ untested / unverified |

**Claude Code.** Installs the `mycelium` skill (`~/.claude/skills/mycelium/SKILL.md`), giving Claude Code memory and coordination commands via `/mycelium`. This is the proven path.

```bash
mycelium adapter add claude-code
```

**Cursor.** Ships its assets per-agent rather than host-wide: `mycelium agent create
--adapter cursor --cwd <workspace>` drops a Cursor rule and an `AGENTS.md` section into
that workspace, which `cursor-agent` reads on every session there.

## Development

```bash
cd fastapi-backend
uv sync --group dev
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .
```

Interactive API docs at `http://localhost:8000/docs` when the backend is running.

## Built On

Mycelium builds on OSS projects we found invaluable in this space:

- [AGNTCY SLIM](https://github.com/agntcy/slim): the encrypted group-messaging transport agents coordinate over
- [IOC L9 protocol models](https://github.com/outshift-open/ioc-protocols-models): the epistemic envelope layer that rides SLIM
- [NegMAS](https://negmas.readthedocs.io/): multi-issue negotiation, the aligner's engine
- [FastAPI](https://fastapi.tiangolo.com/) + [fastembed](https://github.com/qdrant/fastembed): the moderator backend and on-device embeddings
- [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mycelium-io/mycelium)
