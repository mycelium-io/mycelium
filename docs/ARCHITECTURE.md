# Architecture

Mycelium is an adaptive layer between agent frameworks (OpenClaw, Claude Code)
and the IoC Cognition Fabric. It provides shared rooms, persistent memory, and
a coordination engine that mediates structured negotiation so agents reach
consensus without stepping on each other.

## System Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Mycelium System                                 │
│                                                                              │
│  ┌───────────────────────┐      ┌──────────────────────────────────────────┐ │
│  │  CLI (Python/Typer)   │      │  Adapters                                │ │
│  │                       │      │                                          │ │
│  │  room, memory,        │      │  OpenClaw Plugin + Hooks (JS/TS)         │ │
│  │  message, session,    │      │    gateway_start → health check          │ │
│  │  notebook, metrics,   │      │    session_start → SSE stream            │ │
│  │  config, adapter,     │      │    before_agent_start → prompt inject    │ │
│  │  install, synthesize, │      │    message_sent → room relay             │ │
│  │  catchup, watch       │      │                                          │ │
│  │                       │      │  Claude Code Hooks (shell)               │ │
│  │  OTLP metrics         │      │    session lifecycle + memory sync       │ │
│  │  collector (:4318)    │      │                                          │ │
│  └───────────┬───────────┘      └───────────────────┬──────────────────────┘ │
│              │ REST API                             │ REST API + SSE         │
│              │                                      │                        │
│              ▼                                      ▼                        │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                   Mycelium Backend (FastAPI :8000)                   │    │
│  │                                                                      │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐     │    │
│  │  │ Rooms /     │ │ Memory      │ │ Sessions /  │ │ SSE         │     │    │
│  │  │ Messages    │ │ (KVP +      │ │ Presence    │ │ Stream      │     │    │
│  │  │             │ │ Semantic    │ │             │ │             │     │    │
│  │  │ CRUD +      │ │ Search)     │ │ Join/leave  │ │ LISTEN/     │     │    │
│  │  │ namespaces  │ │             │ │ + negotiate │ │ NOTIFY      │     │    │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘     │    │
│  │                                                                      │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐     │    │
│  │  │ Workspaces  │ │ MAS         │ │ Agents      │ │ Audit       │     │    │
│  │  │ Registry    │ │ Registry    │ │ Registry    │ │ Events      │     │    │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘     │    │
│  │                                                                      │    │
│  │  ┌─────────────────────────────────────────────────────────────┐     │    │
│  │  │  Coordination Engine                                        │     │    │
│  │  │                                                             │     │    │
│  │  │  State machine (idle → waiting → negotiating → complete).   │     │    │
│  │  │  Drives multi-issue NegMAS negotiation via structured       │     │    │
│  │  │  propose/respond rounds over room messages. Fires           │     │    │
│  │  │  coordination_tick and coordination_consensus events over   │     │    │
│  │  │  SSE to wake remote agents.                                 │     │    │
│  │  └─────────────────────────────────────────────────────────────┘     │    │
│  │                                                                      │    │
│  │  ┌──────────────────┐                                                │    │
│  │  │  Knowledge Layer │  Direct AgensGraph access for                  │    │
│  │  │  (graph_db,      │  Mycelium-native graph operations              │    │
│  │  │   service,       │  (room knowledge, memory embeddings).          │    │
│  │  │   ingestion)     │  CFN-format operations go via REST.            │    │
│  │  └────────┬─────────┘                                                │    │
│  └───────────┼──────────────────────────────────────────────────────────┘    │
│              │ SQL + openCypher + pgvector                                   │
│              ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                 AgensGraph (PostgreSQL 16 fork) :5432                │    │
│  │                                                                      │    │
│  │  Database: mycelium                                                  │    │
│  │    SQL tables: rooms, messages, sessions, agents, MAS, workspaces,   │    │
│  │                memories, audit_events, notebooks                     │    │
│  │    openCypher:  per-MAS knowledge graphs (graph_{mas_id})            │    │
│  │    pgvector:    384-dim embeddings for semantic memory search        │    │
│  │                                                                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                  Frontend (Next.js :3000)                            │    │
│  │                                                                      │    │
│  │  Room browser, message timeline, memory viewer, session monitor      │    │
│  │  Connects to Mycelium Backend REST API + SSE                         │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                  Matrix / Synapse :8008 (optional)                   │    │
│  │                                                                      │    │
│  │  Chat transport for multi-device agent coordination                  │    │
│  │  OpenClaw gateways connect as Matrix clients                         │    │
│  │  Element on laptops for human observation                            │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
           │                                          ▲
           │ REST (optional, --ioc)                   │ REST
           ▼                                          │
┌──────────────────────────────────────────────────────────────────────────────┐
│                       IoC CFN Stack (Docker, profile: cfn)                   │
│                                                                              │
│  ┌────────────────────────────────┐  ┌───────────────────────────┐           │
│  │  ioc-cfn-mgmt-plane-svc 9000   │  │  ioc-cfn-svc 9002         │           │
│  │                                │  │                           │           │
│  │  Workspace / MAS / Agent CRUD  │  │                           │           │
│  │  Memory provider registration  │  │  Shared memory R/W        │           │
│  │  CFN node registration         │  │  Knowledge extraction     │           │
│  │  Heartbeat + config refresh    │  │  Evidence gathering       │           │
│  │  Audit + policies              │  │  Semantic negotiation     │           │
│  │                                │  │                           │           │
│  │  Mycelium registers as memory  │  │  Routes cognition         │           │
│  │  provider on startup           │  │  engine calls to          │           │
│  └────────────────────────────────┘  │  Mycelium Backend         │           │
│                                      └───────────────────────────┘           │
│                                                                              │
│  Databases hosted in AgensGraph:  cfn_mgmt, cfn_cp                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### 1. CLI (Python / Typer)

The CLI is the operator and agent-facing tool for room management, memory
operations, coordination, and metrics. All commands communicate with the
Mycelium Backend over REST.


| Responsibility     | Detail                                                                       |
| ------------------ | ---------------------------------------------------------------------------- |
| Room management    | `room create`, `room use`, `room ls`, `watch`, `synthesize`                  |
| Memory operations  | `memory set`, `memory search`, `memory ls`, `catchup`, `sync`                |
| Messaging          | `message propose`, `message respond`, `message send`                         |
| Sessions           | `session join`, `session ls`                                                 |
| Instance lifecycle | `init`, `install`, `up`, `down`, `status`, `logs`, `migrate`                 |
| Metrics            | OTLP collector on :4318, `metrics collect`, `metrics show`, `metrics status` |
| Adapters           | `adapter add openclaw`, `adapter add claude-code`                            |
| Configuration      | `config show`, `config set`                                                  |
| Output formats     | Rich terminal tables (default), JSON (`--json`), verbose (`-v`)              |


### 2. Adapters (JS/TS + Shell)

Adapters connect agent frameworks to Mycelium. Each adapter consists of hooks
(lifecycle scripts), a plugin or skill definition, and optionally an extension
that runs inside the framework's gateway process.

#### OpenClaw Adapter


| Component                         | Detail                                                                                                                                                                                                   |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plugin (`index.ts`)               | Runs inside the OpenClaw gateway process; maintains SSE connections to the backend; injects context into agent prompts; relays agent messages to coordination rooms; wakes agents on coordination events |
| `mycelium-bootstrap` hook         | Fires on `agent:bootstrap`; injects `MYCELIUM_API_URL` and `MYCELIUM_ROOM_ID` into agent environment                                                                                                     |
| `mycelium-knowledge-extract` hook | Knowledge extraction on conversation events                                                                                                                                                              |
| SKILL.md                          | Agent skill definition providing `mycelium` CLI instructions                                                                                                                                             |


#### Claude Code Adapter


| Component         | Detail                                                                         |
| ----------------- | ------------------------------------------------------------------------------ |
| Shell hooks       | `session-start`, `session-end`, `post-tool-use`, `pre-compact`, `sync`, `stop` |
| `mycelium-api.sh` | Batch memory operations via REST                                               |
| SKILL.md          | Agent skill definition for Claude Code                                         |


### 3. Mycelium Backend (FastAPI :8000)

The backend is the central coordination engine. It owns all state and is the
only component with direct database access.


| Responsibility  | Detail                                                                                                                                                                                                                     |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Room CRUD       | Create/list/delete rooms; namespace-based memory layout                                                                                                                                                                    |
| Messages        | POST messages to rooms; Postgres NOTIFY on new messages                                                                                                                                                                    |
| Sessions        | Agent join/leave; presence tracking; negotiation state machine                                                                                                                                                             |
| SSE streaming   | `GET /agents/{handle}/stream` — persistent connection for real-time coordination events (coordination_tick, coordination_consensus)                                                                                        |
| Memory          | Filesystem-native KVP storage (`.mycelium/rooms/{room}/{key}.md`) with YAML frontmatter; pgvector semantic search (384-dim embeddings)                                                                                     |
| Coordination    | Multi-issue negotiation via NegMAS; state machine drives propose/respond rounds; fires SSE events to wake remote agents                                                                                                    |
| Knowledge graph | Direct AgensGraph access for Mycelium-native graph operations                                                                                                                                                              |
| Registry        | Workspace / MAS / Agent CRUD                                                                                                                                                                                               |
| Audit           | Event logging for coordination and memory operations                                                                                                                                                                       |
| CFN integration | Adapts IoC Cognition Fabric for agent frameworks: proxies shared-memory and negotiation requests via REST; exposes callback endpoints for `ioc-cfn-svc`; registers as memory provider with mgmt plane on startup (`--ioc`) |
| Notebooks       | Collaborative notebook storage and retrieval                                                                                                                                                                               |
| Reindexing      | Filesystem watcher for incremental search index updates                                                                                                                                                                    |


### 4. AgensGraph (PostgreSQL 16 fork :5432)

Single database instance serving relational tables, graph queries, and vector
search. No external message broker, no separate vector DB, no Redis.


| Database   | Purpose                                                                                                                     | Consumers              |
| ---------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| `mycelium` | SQL tables (rooms, messages, sessions, agents, etc.) + openCypher knowledge graphs (`graph_{mas_id}`) + pgvector embeddings | Mycelium Backend       |
| `cfn_mgmt` | Management plane state (workspaces, MAS, policies, audit). Created when `--ioc` is enabled.                                 | ioc-cfn-mgmt-plane-svc |
| `cfn_cp`   | CFN control plane state (shared memory, heartbeat). Created when `--ioc` is enabled.                                        | ioc-cfn-svc            |


### 5. IoC CFN Stack (Docker, profile: cfn — external to Mycelium)

The IoC Cognition Fabric provides the cognitive backend that Mycelium adapts
for agent frameworks: LLM-based knowledge extraction, evidence gathering,
and semantic negotiation. Mycelium can run standalone for basic coordination
(`mycelium install`), but the full architecture includes the IoC stack
(`mycelium install --ioc`). Communication is exclusively via REST — no IoC
code is imported or linked.

#### ioc-cfn-mgmt-plane-svc (:9000)


| Responsibility               | Detail                                                    |
| ---------------------------- | --------------------------------------------------------- |
| Registry                     | Workspace, MAS, Agent, CFN node, memory provider CRUD     |
| Memory provider registration | Mycelium registers itself on startup                      |
| Heartbeat                    | CFN nodes report health; mgmt plane pushes config updates |
| Audit + policies             | Centralized governance for the CFN fabric                 |


#### ioc-cfn-svc (9002)


| Responsibility           | Detail                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------- |
| Shared memory            | Create/update and query shared memories (concepts + relations in knowledge graph)   |
| Knowledge extraction     | LLM-based concept/relationship extraction from raw data (OpenClaw and OTel formats) |
| Evidence gathering       | Intent-based graph traversal returning natural language evidence summaries          |
| Semantic negotiation     | Multi-round structured negotiation (start + decide lifecycle)                       |
| Cognition engine routing | Routes `COGNITION_ENGINE_SVC_URL` calls to the Mycelium Backend                     |


### 6. Frontend (Next.js :3000)

A development UI for observing coordination state. Connects to the Mycelium
Backend REST API and SSE stream.


| Responsibility  | Detail                                           |
| --------------- | ------------------------------------------------ |
| Room browser    | View rooms, messages, and memory state           |
| Session monitor | Observe active sessions and negotiation progress |


### 7. Matrix / Synapse (:8008, optional)

Chat transport for multi-device deployments. Not required for single-device
use or CLI-only workflows.


| Responsibility    | Detail                                                                             |
| ----------------- | ---------------------------------------------------------------------------------- |
| Message transport | OpenClaw gateways connect as Matrix clients to relay agent messages across devices |
| Human observation | Element clients connect to Synapse for monitoring agent conversations              |


## Data Flow

### Memory Write Flow

```
  Agent (via CLI or plugin)
        │
        │  mycelium memory set "decisions/db" "Use AgensGraph"
        │
        ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Mycelium Backend                                                │
  │                                                                  │
  │  1. Write markdown file to .mycelium/rooms/{room}/{key}.md       │
  │  2. Compute 384-dim embedding (sentence-transformers, local)     │
  │  3. Upsert pgvector row for semantic search                      │
  │  4. NOTIFY on Postgres channel                                   │
  │  5. SSE push to subscribed agents                                │
  └──────────────────────────────────────────────────────────────────┘
```

### Coordination Flow (Negotiation)

Works identically in single-device and multi-device modes. In single-device
mode both agents run on localhost; in multi-device mode they may be on
different laptops (e.g. alice-laptop and bob-laptop) pointing at a central backend.

```
  Agent A                           Mycelium Backend                      Agent B
       │                                    │                                  │
       │  session join --handle A           │                                  │
       ├───────────────────────────────────►│                                  │
       │                                    │  session join --handle B         │
       │                                    │◄─────────────────────────────────┤
       │                                    │                                  │
       │                           Coordination engine fires tick-0            │
       │                           (join window elapsed)                       │
       │                                    │                                  │
       │  SSE: coordination_tick            │  SSE: coordination_tick          │
       │◄───────────────────────────────────┤──────────────────────────────────►
       │                                    │                                  │
       │  message propose BUDGET=high       │                                  │
       ├───────────────────────────────────►│                                  │
       │                                    │  SSE: coordination_tick          │
       │                                    │──────────────────────────────────►
       │                                    │                                  │
       │                                    │  message respond accept          │
       │                                    │◄─────────────────────────────────┤
       │                                    │                                  │
       │                           Coordination engine: consensus reached      │
       │                                    │                                  │
       │  SSE: coordination_consensus       │  SSE: coordination_consensus     │
       │◄───────────────────────────────────┤──────────────────────────────────►
       │                                    │                                  │
```

### CFN Shared Memory Flow (via REST)

```
  Mycelium Backend                     ioc-cfn-svc (9002)               AgensGraph
       │                                    │                                │
       │  POST .../shared-memories          │                                │
       │  (raw data + format metadata)      │                                │
       ├───────────────────────────────────►│                                │
       │                                    │  1. LLM extraction             │
       │                                    │  2. Concept/relation mapping   │
       │                                    │  3. Upsert knowledge graph ────►
       │                                    │                                │
       │  201 Created + response_id         │                                │
       │◄───────────────────────────────────┤                                │
       │                                    │                                │
       │  POST .../shared-memories/query    │                                │
       │  (intent string)                   │                                │
       ├───────────────────────────────────►│                                │
       │                                    │  1. Evidence pipeline          │
       │                                    │  2. Graph traversal + LLM  ────►
       │                                    │                                │
       │  200 OK + evidence summary         │                                │
       │◄───────────────────────────────────┤                                │
       │                                    │                                │
```

### CFN Management Plane Registration

```
  Mycelium Backend                     ioc-cfn-mgmt-plane-svc (:9000)
       │                                    │
       │  POST /api/memory-providers        │
       │  { name: "mycelium", url: ... }    │
       ├───────────────────────────────────►│
       │                                    │
       │  201 Created (or 409 exists)       │
       │◄───────────────────────────────────┤
       │                                    │
```

## Deployment Modes

Mycelium supports two deployment modes. The backend and database are
identical in both — the difference is where agents run and how they
reach the backend.

### Single-Device Install

Everything runs on one machine: backend, database, agents, and CLI. This is
the default `mycelium install` experience. No network configuration required.

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Single Device (localhost)                     │
│                                                                     │
│  ┌──────────────────┐    REST    ┌───────────────────────────────┐  │
│  │  OpenClaw GW     │───────────►│  Mycelium Backend :8000       │  │
│  │  + Agents        │◄───SSE─────│                               │  │
│  │                  │            │  Coordination Engine          │  │
│  │  Claude Code     │───────────►│  Memory + Rooms + Sessions    │  │
│  │  + Agents        │            │  Knowledge Layer              │  │
│  └──────────────────┘            └───────────────┬───────────────┘  │
│                                                  │                  │
│  ┌──────────────────┐                            │ SQL+Cypher+vec   │
│  │  CLI             │──REST─────────────────────►│                  │
│  │  mycelium ...    │                            ▼                  │
│  └──────────────────┘            ┌───────────────────────────────┐  │
│                                  │  AgensGraph :5432             │  │
│                                  │  mycelium DB                  │  │
│                                  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │ REST (optional, --ioc)
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  IoC CFN Stack (optional, --ioc flag)                               │
│  ioc-cfn-mgmt-plane-svc 9000     ioc-cfn-svc 9002                   │
└─────────────────────────────────────────────────────────────────────┘
```


| Setting                         | Value                                              |
| ------------------------------- | -------------------------------------------------- |
| `MYCELIUM_API_URL`              | `http://localhost:8000` (default)                  |
| `server.api_url` in config.toml | `http://localhost:8000`                            |
| Matrix / Synapse                | Not required                                       |
| Install command                 | `mycelium install` (add `--ioc` for IoC CFN stack) |
| Docker compose profiles         | default (add `cfn` profile with `--ioc`)           |


### Multi-Device Install

The backend and IoC CFN stack run on a central host. Remote devices run only
agents (OpenClaw gateways or Claude Code), configured to point at the central
backend. Matrix provides cross-device chat transport.

```
┌──────────────┐      ┌──────────────────────────────────┐      ┌──────────────┐
│ alice-laptop │      │           central-host           │      │  bob-laptop  │
│              │      │                                  │      │              │
│ OpenClaw GW  │─REST►│  Mycelium Backend  :8000         │◄REST─│ OpenClaw GW  │
│ + Agents     │      │  AgensGraph        :5432         │      │ + Agents     │
│              │─Mtrx►│  Synapse           :8008         │◄Mtrx─│              │
│              │      │                                  │      │              │
└──────────────┘      └───────────────┬──────────────────┘      └──────────────┘
                                      │ ▲
                         REST + Element│ │REST (--ioc)
                        ┌─────────────┘ └──────────────┐
                        ▼                              ▼
                  ┌────────────┐       ┌───────────────────────────┐
                  │  Observers │       │  IoC CFN Stack            │
                  │  (Element, │       │  CFN mgmt 9000            │
                  │   curl)    │       │  CFN svc  9002            │
                  └────────────┘       └───────────────────────────┘
```


| Setting            | Central Host                   | Remote Devices                      |
| ------------------ | ------------------------------ | ----------------------------------- |
| `MYCELIUM_API_URL` | `http://localhost:8000`        | `http://<central-ip>:8000`          |
| Matrix homeserver  | Synapse on `:8008`             | Point to `http://<central-ip>:8008` |
| Install command    | `mycelium install`             | CLI only (no local backend)         |
| Agents             | Optional (can also run agents) | OpenClaw gateway + agents           |


**Configuration required on remote devices:**

- Set `MYCELIUM_API_URL=http://<central-ip>:8000` in the gateway environment
so the bootstrap hook injects it into every agent session and the Mycelium
Plugin uses it for SSE streams, context fetching, and message forwarding.
- Set `channels.matrix.accounts.default.homeserver` in `openclaw.json` to
`http://<central-ip>:8008` (pointing to central Synapse).

**How agents on remote devices connect:**

- The `mycelium-bootstrap` hook fires on `agent:bootstrap` and injects
`MYCELIUM_API_URL` and `MYCELIUM_ROOM_ID` into the agent's environment.
- The Mycelium Plugin opens a persistent SSE connection to the central backend
for real-time coordination events.
- All memory reads/writes go to the centralized AgensGraph on the central host.


| Path                          | Ports     | Transport                           |
| ----------------------------- | --------- | ----------------------------------- |
| Agents → Mycelium Backend     | :8000     | REST (memory, messages, sessions)   |
| Plugin → Mycelium Backend     | :8000     | SSE (coordination events)           |
| Agents → Synapse              | :8008     | Matrix client protocol (chat relay) |
| Observers → central host      | 8000–8999 | REST + Element                      |
| Laptop ↔ laptop (via central) | :8000     | All traffic routes through central  |


### What's the Same in Both Modes

The backend is identical — same Docker compose, same FastAPI app, same
AgensGraph. The only differences are:


| Concern            | Single-Device               | Multi-Device                                       |
| ------------------ | --------------------------- | -------------------------------------------------- |
| `MYCELIUM_API_URL` | `localhost:8000`            | `<central-ip>:8000`                                |
| Agent gateways     | Local                       | Local + remote                                     |
| Matrix / Synapse   | Not needed                  | Required for cross-device chat                     |
| IoC CFN stack      | Optional (`--ioc`)          | Central host only (`--ioc`); not needed on remotes |
| Memory namespace   | Shared via local filesystem | Shared via centralized API                         |
| Network config     | None                        | `MYCELIUM_API_URL` + Matrix homeserver on remotes  |


## Filesystem Layout

### Memory Storage

Rooms are folders. Memories are markdown files with YAML frontmatter. This is
the source of truth — direct file writes always work; run `mycelium reindex`
to refresh the search index.

```
.mycelium/rooms/{room}/
├── decisions/    Why choices were made
├── status/       Current state of things
├── context/      Background and constraints
├── work/         In-progress and completed work
├── procedures/   How-to guides and runbooks
└── log/          Events and observations
```

### Repository Layout

```
mycelium-cli/               CLI + adapters
  src/mycelium/
    commands/               Typer command groups (room, memory, session, ...)
    adapters/
      openclaw/             Plugin (index.ts), hooks, SKILL.md
      claude-code/          Shell hooks, scripts, SKILL.md
    docker/                 compose.yml, initdb scripts, env defaults
    docs/                   CLI reference, metrics field guide
fastapi-backend/            FastAPI coordination engine
  app/
    routes/                 REST endpoints (rooms, messages, memory, ...)
    knowledge/              AgensGraph graph operations (schemas, service, ingestion)
    agents/                 Coordination engine internals
      semantic_negotiation/ Room-based negotiation coordinator + coordination state machine
      protocol/sstp/        Structured semantic transfer protocol messages
    services/               Reindex, metrics, catchup, synthesis
    models.py               SQLAlchemy models
    database.py             Async session factory
    config.py               Settings (env-based)
mycelium-client/            Generated typed OpenAPI client
mycelium-frontend/          Next.js development UI
docs/                       Architecture, setup guides, diagrams
```

## IoC Service Integration

Mycelium adapts the IoC Cognition Fabric for agent frameworks, forwarding
knowledge extraction, evidence gathering, and negotiation requests to the
IoC services via REST. Both run as Docker containers under the `cfn`
compose profile (`--ioc`) and share AgensGraph as their database backend.
No IoC code is imported or linked into Mycelium.


| Capability               | REST Endpoint                                               | Service            |
| ------------------------ | ----------------------------------------------------------- | ------------------ |
| Knowledge extraction     | `POST :9002/api/.../shared-memories`                        | ioc-cfn-svc        |
| Evidence gathering       | `POST :9002/api/.../shared-memories/query`                  | ioc-cfn-svc        |
| Semantic negotiation     | `POST :9002/api/.../semantic-negotiation/start` + `/decide` | ioc-cfn-svc        |
| Memory provider register | `POST :9000/api/memory-providers`                           | ioc-cfn-mgmt-plane |


## Component Communication Summary

```
                       ┌──────────────────────────────┐
                       | Mycelium System              │             
┌──────────┐   REST    │ ┌───────────────────┐        │
│  CLI     │───────────┼►│  Mycelium         │        │
│  (Python)│           │ │  Backend          │        │
└──────────┘           │ │  (FastAPI :8000)  │        │
                       │ │                   │        │
┌──────────┐   REST    │ │  ┌─────────────┐  │        │
│  OpenClaw│───────────┼►│  │ Coordinatn  │  │        │
│  Plugin  │◄──SSE─────┼─│  │ Engine      │  │        │
│  (JS/TS) │           │ │  └─────────────┘  │        │
└──────────┘           │ │                   │        │
                       │ │  ┌─────────────┐  │        │
┌──────────┐   REST    │ │  │ Knowledge   │  │        │
│  Claude  │───────────┼►│  │ Layer       │  │        │
│  Code    │           │ │  └─────────────┘  │        │
│  Hooks   │           │ │                   │        │
└──────────┘           │ │  SQL+Cypher+vec   │        │
                       │ └─────────┬─────────┘        │
                       │           │                  │
                       │           ▼                  │
                       │ ┌───────────────────┐        │
                       │ │  AgensGraph       │        │
                       │ │  (:5432)          │        │
                       │ │  mycelium DB      │        │
                       │ └───────────────────┘        │
                       └──────────────────────────────┘
                                             │ REST (optional, --ioc)
                                             ▼
                       ┌───────────────────────────────────────────────┐
                       │  IoC CFN Stack                                │
                       │                                               │
                       │  ┌───────────────────┐ ┌───────────────────┐  │
                       │  │  ioc-cfn-svc      │ │  ioc-cfn-mgmt     │  │
                       │  │  (9002)           │ │  (9000)           │  │
                       │  │  shared memory    │ │  registry         │  │
                       │  │  extraction       │ │  memory provider  │  │
                       │  │  evidence         │ │                   │  │
                       │  │  negotiation      │ │                   │  │
                       │  └───────────────────┘ └───────────────────┘  │
                       └───────────────────────────────────────────────┘
```

