<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.0.1 (expanded Development Standards from skills)
Added sections: Core Principles, Development Standards, Architecture Constraints, Governance
Modified principles: N/A (initial)
Removed sections: N/A (initial)
Templates requiring updates:
  ✅ .specify/templates/constitution-template.md (source)
  ✅ .specify/memory/constitution.md (this file)
  ⚠ .specify/templates/plan-template.md (review Constitution Check alignment)
  ⚠ .specify/templates/spec-template.md (review scope/requirements alignment)
  ⚠ .specify/templates/tasks-template.md (review task categorization)
Deferred TODOs: none
-->

# Mycelium Constitution

## Core Principles

### I. Single Database, No External Brokers

Mycelium MUST use one AgensGraph (PostgreSQL 16) instance as the sole source of truth.
No external message brokers, no separate vector databases, no Redis.
The single database handles SQL coordination state, knowledge graph (openCypher),
and semantic search (pgvector) — all in one. Real-time messaging uses Postgres
LISTEN/NOTIFY via asyncpg, not a separate pubsub layer.

**Rationale:** Operational simplicity and reduced failure surface. Every new external
dependency is a deployment burden and a consistency risk. If PostgreSQL can do it, use
PostgreSQL.

### II. Filesystem-Native Memory

Rooms MUST be representable as plain directories and memories as markdown files with
YAML frontmatter. The canonical path structure is
`.mycelium/rooms/{room_name}/{namespace}/{key}.md`. Direct filesystem operations
(cat, editor writes, agent file I/O) MUST always produce valid state — run `reindex`
to refresh the search index after out-of-band writes.

Standard namespaces: `decisions/`, `status/`, `context/`, `work/`, `procedures/`, `log/`.
Rooms MUST be git-friendly so context can be committed and shared across machines.

**Rationale:** Filesystem-native design means no proprietary format lock-in, easy
inspection/debugging, and trivial portability via git. Agents and humans can always
read and write memory without a running server.

### III. CognitiveEngine Mediation (NON-NEGOTIABLE)

Agents MUST NOT communicate directly with each other. All multi-agent coordination
MUST flow through the CognitiveEngine, which mediates structured negotiation using
NegMAS. Negotiation state machine: `idle → waiting → negotiating → complete`.
Every agent has a voice; the engine resolves to a single shared consensus answer.

Sessions are ephemeral coordination contexts within persistent rooms. Rooms persist
across sessions; sessions do not persist across restarts.

**Rationale:** Direct agent-to-agent communication creates unauditable, uncontrolled
coordination. The CognitiveEngine ensures every decision is structured, logged, and
reproducible.

### IV. Test-First, Two-Tier Testing

Tests MUST be written before implementation (TDD). Two tiers are REQUIRED:

- **Unit tests (SQLite):** In-memory `sqlite+aiosqlite://`, fresh schema per test,
  no pgvector (vector search tests skipped). Cover CRUD, coordination state,
  filesystem operations.
- **Integration tests (AgensGraph):** Real PostgreSQL 16 with AgensGraph. Cover
  semantic search, LISTEN/NOTIFY, knowledge graph. Activated via `DATABASE_URL` env var.

LLM synthesis tests MUST be guarded by `MYCELIUM_LLM_TESTS=1` (token cost control).
Use `pytest-asyncio` for all async tests.

**Rationale:** SQLite units keep the feedback loop fast; AgensGraph integration tests
catch real database behavior. Never merge a feature without both tiers green.

### V. Simplicity Over Abstraction (YAGNI)

Start simple. Every abstraction MUST justify its existence with at least two concrete
current uses. No speculative generalization, no premature interfaces. Libraries and
services MUST have a clear, singular purpose. Complexity MUST be documented in
CLAUDE.md or inline comments — unexplained complexity is a defect.

**Rationale:** The codebase is maintained by a small team. Unnecessary complexity
increases onboarding cost and bug surface with no commensurate benefit.

## Development Standards

- **Package management:** MUST use `uv` exclusively (not pip or bare python).
- **Linting/formatting:** MUST pass `ruff check . && ruff format .` before commit.
  Ruff uses `select = ["ALL"]` with explicit ignores configured in each `pyproject.toml`.
  Line length 100 (backend), 120 (client).
- **Type checking:** `mypy` MUST pass for the CLI package.
- **Branching:** NEVER commit feature work directly to `main`. Always branch first.
  Direct commits to `main` are reserved for release tagging only (via `/release`).
- **Precommit gate (ALL must pass before merge):**
  1. `ruff check --fix . && ruff format .` — backend and CLI
  2. `pytest tests/ -x -q` — backend unit tests
  3. `npx tsc --noEmit && npx next build` — frontend
  4. If backend schemas/routes changed: regenerate the OpenAPI client
     (`openapi-python-client generate`) and copy to `mycelium-client/` and
     `mycelium-cli/src/mycelium_backend_client/`
  5. If CLI commands added/modified: ensure `@doc_ref` decorator present, then run
     `/generate-cli-docs` to regenerate `docs/index.html`
- **CLI commands:** Every new or modified CLI command MUST have a `@doc_ref` decorator
  with `usage`, `desc`, and `group` fields before it can be merged.
- **LLM integration:** MUST use `litellm` with `provider/model` format
  (e.g., `anthropic/claude-sonnet-4-6`). No direct vendor SDK calls in core logic.
- **Embeddings:** MUST use sentence-transformers `all-MiniLM-L6-v2` (local, no API key).
- **Commit messages:** Conventional commits — `feat:`, `fix:`, `refactor:`, `docs:`,
  `test:`, `chore:`. Imperative mood, concise subject, context in body if needed.

## Architecture Constraints

- Backend: Python 3.12, FastAPI (async), SQLAlchemy (async), asyncpg.
- CLI: Python 3.12, Typer, Rich, httpx.
- Client: Auto-generated via openapi-python-client — do not hand-edit generated files.
- Frontend: Next.js + Tailwind (React). Kept minimal; coordination logic lives in backend.
- Infrastructure: Docker for all services. No bare-metal deployment assumptions.
- Agent adapters (Claude Code, OpenClaw) MUST use the same coordination protocol:
  `join → wait → respond → consensus`. Adapters are thin; protocol logic stays in CLI.

## Governance

This constitution supersedes all other development practices and conventions.
Amendments MUST be:
1. Proposed with rationale and migration plan.
2. Documented in this file with a version bump.
3. Reflected in CLAUDE.md and any affected template files.

All PRs MUST verify compliance with the principles above. Complexity introduced in
violation of Principle V requires explicit justification in the PR description.

Version bumping rules:
- **MAJOR:** Principle removal, redefinition, or backward-incompatible governance change.
- **MINOR:** New principle, section, or materially expanded guidance.
- **PATCH:** Clarifications, wording fixes, non-semantic refinements.

See `CLAUDE.md` for runtime development guidance (commands, test invocation, tooling).

**Version**: 1.0.1 | **Ratified**: 2026-03-23 | **Last Amended**: 2026-03-23
