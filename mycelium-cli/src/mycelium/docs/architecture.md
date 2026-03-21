# Architecture

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

### Backend API

Any agent that can make HTTP requests can use the REST API directly.
Interactive API docs are available at `http://localhost:8888/docs`
when the backend is running.
