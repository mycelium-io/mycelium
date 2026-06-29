# mycelium

A coordination layer for multi-agent systems — shared **rooms**, **persistent memory** that accumulates across sessions, and a **CognitiveEngine** that mediates structured negotiation so multiple agents can converge on a single answer.

This file is the maintainer's hint to a [tiny-teams-with-tokens](https://github.com/juliarvalenti/tiny-teams-with-tokens) ingest agent generating Mycelium's status wiki. It's not the README and not a substitute for reading the actual code — it's a pointer to *where to look first* and *what's easy to misdescribe*.

## Read these first

The fastest path to "what is this and why":

- [CLAUDE.md](CLAUDE.md) — authoritative design rules + architecture overview. Read this before anything else.
- [README.md](README.md) — user-facing pitch and quick start.
- [docs/index.html](docs/index.html) — presentation deck (more conceptual framing).
- [docs/demo-script.md](docs/demo-script.md) — narrative walkthrough of a coordination flow.

## Repo layout

Mycelium is a multi-component monorepo. When you describe "the architecture" you should mention all of these by their actual roles:

- [`fastapi-backend/`](fastapi-backend/) — the coordination engine (Python 3.12, FastAPI, asyncpg, SQLAlchemy). Talks to AgensGraph (a PostgreSQL 16 fork) for SQL + pgvector + openCypher.
- [`mycelium-cli/`](mycelium-cli/) — the user-facing CLI (typer + Rich). The primary surface most users touch. Hosts the adapter logic for Claude Code, Cursor, OpenClaw.
- [`mycelium-client/`](mycelium-client/) — auto-generated OpenAPI client. Treat as build output; don't document its internals.
- [`mycelium-frontend/`](mycelium-frontend/) — Next.js + Tailwind UI shipped via `mycelium up --ui`.
- [`mycelium-promo/`](mycelium-promo/) — HyperFrames promo video (HTML→MP4). Out of scope for the wiki.
- [`docs/`](docs/) — presentation site + demo script.

## Where the actual logic lives

If you're documenting how Mycelium works, ground every claim against one of these:

- [`fastapi-backend/app/main.py`](fastapi-backend/app/main.py) — backend entrypoint.
- [`fastapi-backend/app/services/coordination.py`](fastapi-backend/app/services/coordination.py) — the heart of CognitiveEngine. Posts `coordination_tick` messages that drive negotiation. Read this if you want to understand the actual mediation loop.
- [`fastapi-backend/app/services/cfn_negotiation.py`](fastapi-backend/app/services/cfn_negotiation.py), [`cfn_resolve.py`](fastapi-backend/app/services/cfn_resolve.py), [`cfn_knowledge.py`](fastapi-backend/app/services/cfn_knowledge.py) — the CFN (Coordination Fabric Network) consensus pieces.
- [`fastapi-backend/app/services/embedding.py`](fastapi-backend/app/services/embedding.py), [`indexer.py`](fastapi-backend/app/services/indexer.py), [`reindex.py`](fastapi-backend/app/services/reindex.py) — pgvector search index over memory.
- [`fastapi-backend/app/routes/`](fastapi-backend/app/routes/) — HTTP API surface (rooms, sessions, memory, coordination, CFN proxy, SSE streams).
- [`mycelium-cli/src/mycelium/commands/`](mycelium-cli/src/mycelium/commands/) — every CLI verb (`memory`, `room`, `session`, `negotiate`, `cfn`, `adapter`, `install`, …).
- [`mycelium-cli/src/mycelium/integrations/`](mycelium-cli/src/mycelium/integrations/) — one package per runtime family (`claude_code/`, `openclaw/`), each holding its dispatch+install code and an `assets/` bundle. **Important** — see "Things easy to mis-describe" below.

## What to emphasize

- **Rooms are folders, memory is markdown.** `.mycelium/rooms/{name}/{key}.md` with YAML frontmatter. The filesystem is authoritative; pgvector is a search index over it. Direct file writes work; `reindex` updates the search index.
- **CognitiveEngine mediates everything.** Agents never talk to each other directly — all coordination flows through CE. Don't describe Mycelium as a "messaging layer" or "agent chat"; it's a structured-negotiation mediator.
- **Sessions live inside rooms.** Rooms are persistent namespaces; sessions are short-lived NegMAS negotiation rounds spawned within a room when agents need to agree on something in real time. The two words mean different things — "session" in Mycelium is *not* an agent conversation turn.
- **Multi-component is the point.** A user touching only the CLI sees half the system. A user touching only the backend sees the other half. Document both.

## Things easy to mis-describe

- **Two delivery paths for coordination ticks — keep them in sync.** When `coordination_tick` is posted to a session room, agents see it via:
  1. **CLI path** (Claude Code, Cursor, plain shell): the agent runs `mycelium await` (or `mycelium negotiate await`) which streams ticks from the SSE endpoint.
  2. **OpenClaw path:** the agent does NOT run `mycelium await`. The `mycelium-room` channel plugin in [`mycelium-cli/src/mycelium/integrations/openclaw/assets/`](mycelium-cli/src/mycelium/integrations/openclaw/assets/) subscribes to the SSE on its behalf and dispatches a *human-readable string* into the agent's session via `formatTickInstruction()`.

  Adding a field to the tick payload (`coordination.py:_fan_out_cfn_messages`) is **not enough on its own** — the openclaw flow won't surface it until `formatTickInstruction()` is also updated. Always change both. Mention this whenever you describe ticks or coordination flow.
- **AgensGraph is PostgreSQL 16, not Neo4j.** It exposes openCypher *on top of* Postgres. Don't conflate it with a separate graph database.
- **memory set always upserts.** It overwrites existing keys; the row's version increments. Don't describe it as "create-only".
- **Two compose files.** `compose.yml` (released images, end-user path) and `compose-dev.yml` (builds backend from source). End users use the install script + `mycelium install`; only contributors run docker compose by hand.

## Out of scope for the wiki

- Promo video pipeline (`mycelium-promo/`) — internal marketing artifact.
- Generated client internals (`mycelium-client/`) — build output, not source of truth.
- Docs site rendering details (`docs/generate_docs.py`, CSS, etc.).
- Step-by-step end-user install — that's what the README is for.
