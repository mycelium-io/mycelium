# CLAUDE.md

## Project

Mycelium — multi-agent coordination + filesystem-native persistent memory, built on the Internet of Cognition.

## Structure

```
.mycelium/              Filesystem-native memory (rooms are folders, memories are markdown files)
├── rooms/{name}/       Room directories with standard namespace subdirs
├── notebooks/{handle}/ Agent-private notebook directories
└── config.toml         Project-local configuration

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

**Filesystem-native memory**: Source of truth is `.mycelium/rooms/{room}/{key}.md`. Markdown files with YAML frontmatter. The entire unix toolchain works — `cat`, `grep`, `sed`, `git diff`.

**AgensGraph** (PostgreSQL 16 fork) is the search index and coordination backend:
- pgvector: semantic vector search over memory embeddings (updated on write)
- SQL tables: rooms, sessions, messages, subscriptions, coordination state
- openCypher: knowledge graph (optional enrichment layer)

**Memory flow**:
1. `memory set` writes a markdown file to `.mycelium/rooms/{room}/{key}.md`
2. Simultaneously upserts a pgvector embedding in AgensGraph for semantic search
3. `memory get` / `memory ls` reads from the filesystem
4. `memory search` queries the pgvector index
5. Direct file writes (cat, editor, agent file I/O) work — run `reindex` to update search index

Real-time: Postgres LISTEN/NOTIFY → asyncpg → SSE streams.

LLM: litellm (provider/model format, e.g. `anthropic/claude-sonnet-4-6`).

Embeddings: sentence-transformers (all-MiniLM-L6-v2, local, 384 dimensions).

## Key design decisions

- **Filesystem is source of truth** — markdown files in `.mycelium/` are the primary storage. AgensGraph is the search index.
- **CognitiveEngine mediates** — agents never talk to each other directly. All coordination flows through CE.
- **Rooms are folders** — `mkdir -p .mycelium/rooms/my-project` creates a room. Standard subdirs: `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`.
- **Rooms are always persistent** — rooms are persistent namespaces for memory and coordination. Spawn sessions within rooms for real-time NegMAS negotiation.
- **The CLI skill is a protocol** — join → wait → respond → consensus. This is the value add, don't change it to an augmentation layer.
- **memory set always upserts** — `memory set` overwrites existing keys automatically (version increments).
- **Git for sharing** — rooms can be shared via git push/pull. No custom sync protocol.
- **No Ensue references in code** — we took inspiration from their API design but the implementation is independent.

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: SQLite for unit tests (conftest.py), real AgensGraph for integration tests
- Tests use temp directories for `.mycelium/` data (conftest.py sets MYCELIUM_DATA_DIR)
- LLM synthesis tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
