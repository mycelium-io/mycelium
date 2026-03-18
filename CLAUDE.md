# CLAUDE.md

## Project

Mycelium — multi-agent coordination + persistent memory, built on the Internet of Cognition.

## Structure

```
fastapi-backend/    FastAPI coordination engine (Python 3.12, asyncpg, SQLAlchemy)
mycelium-cli/       CLI tool (typer, Rich, typed OpenAPI client)
mycelium-client/    Generated OpenAPI client (openapi-python-client)
mycelium-frontend/  Next.js room viewer (TypeScript, Tailwind)
docs/               Presentation deck, demo script
```

## Development

```bash
# Backend
cd fastapi-backend && uv sync --group dev
uv run pytest tests/ -x -q                    # unit tests (SQLite)
DATABASE_URL=... uv run pytest tests/ -x -q    # integration tests (AgensGraph)
uv run ruff check . && uv run ruff format .

# CLI (install globally)
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# Frontend
cd mycelium-frontend && pnpm install && pnpm dev
```

## Architecture

Single AgensGraph database (PostgreSQL 16 fork) handles:
- SQL tables: rooms, sessions, messages, memories, subscriptions
- openCypher: knowledge graph
- pgvector: semantic vector search on memory embeddings

Real-time: Postgres LISTEN/NOTIFY → asyncpg → SSE streams.

LLM: litellm (provider/model format, e.g. `anthropic/claude-sonnet-4-6`).

Embeddings: fastembed (BAAI/bge-small-en-v1.5, local, 384 dimensions).

## Key design decisions

- **CognitiveEngine mediates** — agents never talk to each other directly. All coordination flows through CE.
- **Rooms are namespaces** — memories are scoped to rooms. A room IS its namespace.
- **Three room modes** — sync (NegMAS negotiation), async (persistent memory), hybrid (both).
- **The CLI skill is a protocol** — join → wait → respond → consensus. This is the value add, don't change it to an augmentation layer.
- **memory set always upserts** — `memory set` overwrites existing keys automatically (version increments).
- **No Ensue references in code** — we took inspiration from their API design but the implementation is independent.

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: SQLite for unit tests (conftest.py), real AgensGraph for integration tests
- LLM synthesis tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
