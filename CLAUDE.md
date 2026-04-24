# CLAUDE.md

## Project

Mycelium — multi-agent coordination + persistent memory, built on the Internet of Cognition.

## Structure

```
.mycelium/              Memory storage (rooms are folders, memories are markdown files)
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

**Memory**: Stored as markdown files with YAML frontmatter in `.mycelium/rooms/{room}/{key}.md`.

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

- **CognitiveEngine mediates** — agents never talk to each other directly. All coordination flows through CE.
- **Rooms are folders** — `.mycelium/rooms/{name}/` with standard subdirs: `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`.
- **Rooms are always persistent** — rooms are persistent namespaces for memory and coordination. Spawn sessions within rooms for real-time NegMAS negotiation.
- **The CLI skill is a protocol** — join → wait → respond → consensus. This is the value add, don't change it to an augmentation layer.
- **memory set always upserts** — `memory set` overwrites existing keys automatically (version increments).
- **Git for sharing** — rooms can be shared via git push/pull.
- **No Ensue references in code** — we took inspiration from their API design but the implementation is independent.

## Local development

> **This section is for contributors iterating on the backend source.** End users should follow the normal install path: `curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` then `mycelium install`.

### Starting the stack

The normal `mycelium up` / `mycelium install` flow uses `compose.yml` with `pull_policy: always` — it always pulls released images and is the correct path for end users. For dev, use `compose-dev.yml` instead, which builds `mycelium-backend` from local source and wires `~/.mycelium/.env` into all service containers. **Always run from the repo root.**

```bash
# Full stack with CFN (required for negotiate/session commands)
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  --profile cfn up -d --build

# Memory only (no CFN)
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --build
```

On subsequent runs, drop `--build` unless you've changed backend code.

### LLM config

All containers get their LLM settings from `~/.mycelium/.env`, which is generated from `config.toml`. Set these once:

```bash
mycelium config set llm.model "anthropic/bedrock/global.anthropic.claude-sonnet-4-6"
mycelium config set llm.api_key "<key>"
mycelium config set llm.base_url "<base-url>"
mycelium config apply
```

Then recreate any running CFN containers to pick up the new env:
```bash
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  --profile cfn up -d --force-recreate ioc-cognition-fabric-node-svc
```

**Important:** `mycelium config apply` regenerates `.env` from `config.toml`. If you edit `.env` directly, those changes will be overwritten. Always use `mycelium config set` to persist values.

### MAS ID

`mas_id` in `config.toml` is a CFN Multi-Agent System UUID required for `session join`/`await`/`negotiate`. Each room gets its own MAS ID on creation — use the one for the room you're testing:

```bash
mycelium room create my-room        # prints MAS ID on creation
mycelium config set server.mas_id <uuid-from-above>
```

After a volume wipe, existing MAS IDs are gone. Create a new room and use its ID.

### Running the backend outside Docker (hot-reload)

```bash
cd fastapi-backend
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/mycelium" \
  uv run uvicorn app.main:app --reload --port 8000
```

DB container still needs to be running (`docker compose up -d mycelium-db`). Update `config.toml` if you change the backend port:
```bash
mycelium config set server.api_url "http://localhost:8000"
mycelium config apply
```

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: SQLite for unit tests (conftest.py), real AgensGraph for integration tests
- Tests use temp directories for `.mycelium/` data (conftest.py sets MYCELIUM_DATA_DIR)
- LLM synthesis tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
