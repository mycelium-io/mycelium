# START HERE — Step 1 (Kill the database)

Companion to [`START_HERE.md`](./START_HERE.md). Step 0 is **done and merged-ready**
(PR against `slim-native-rewrite`); you are picking up **Step 1**. Read `START_HERE.md`
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 0
left behind, (b) your Step 1 marching orders, and (c) the traps that are specific to this step.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 1**, with **§11 (Memory)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code blocks in the bible are **reference, not paste**. Write it yourself, matching the
   surrounding style.
4. **Verify before you edit** — paths below were accurate at the end of Step 0; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; open questions have a default — Step 1's is **"JSONL
   is decided,"** so there's nothing to resolve first.

## Where Step 0 left things (your starting state)

Branch off the Step 0 branch (`step0-rip-out-cfn`) — or off `slim-native-rewrite` once Step 0
is merged. The CFN/coordination/knowledge surface is **gone**; the **L9 core is kept**
(`app/services/l9.py`, `l9_episode.py`, `l9_models.py`). **The database is still fully present
and load-bearing** — that is your whole job to remove:

- `app/database.py` — async SQLAlchemy engine + `get_async_session` + `create_db_and_tables()`.
- `app/models.py` — SQLAlchemy `Base` and tables: `rooms`, `coordination_sessions`, `messages`,
  `participants` (presence), `audit_events`, `memories`, `memory_subscriptions`, `agents`.
- `app/main.py` lifespan still calls `create_db_and_tables()`; `_check_database()` (in `/health`)
  runs `SELECT 1`.
- `app/config.py` still has `DATABASE_URL` and `GRAPH_DB_URL`.
- **These routes still query the DB, not just memory:** `routes/memory.py` (memories table +
  pgvector-ish search via `indexer.py`), `routes/rooms.py` (rooms table), `routes/sessions.py`
  (coordination_sessions + participants), `routes/messages.py` (messages table + asyncpg
  NOTIFY), `routes/stream.py` (a **separate raw asyncpg** LISTEN/NOTIFY connection).
- Tests wire an **in-memory SQLite** DB: `tests/conftest.py` (`db_session` fixture,
  `Base.metadata.create_all`, `client` fixture overriding `get_async_session`). Killing
  `models.py`/`database.py` **breaks conftest** — plan to rework it.
- Docker: `docker/compose.yml` still defines **`mycelium-db`** (the only DB service left) and
  `mycelium-backend` depends on it `service_healthy`. `compose-dev.yml` still builds it locally.
  CLI `docker_utils.py` still emits `DATABASE_URL`/`GRAPH_DB_URL`; `config.py` (CLI) still has
  `database_url()` + `db_password`/`db_port` and `ServerConfig.database_url`.

**Heads-up (the real scope):** "kill the DB" is *not* just the memory path. Because
`rooms`/`sessions`/`messages`/`stream` all sit on SQLAlchemy today, you must decide a home for
that state. The bible is explicit: **memory → markdown + JSONL now; presence/room state →
files or in-memory now, and it moves onto SLIM in Steps 3–4.** So for Step 1, *rooms* become
file-backed (rooms are already folders — `filesystem.py`), and *presence/messages/sessions*
become the minimum viable local/in-memory shim to keep endpoints answering. Don't rebuild them
richly — Steps 3–4 replace them with the SLIM bus.

### Carry-forward from the Step 0 review (acknowledge, don't fix yet)

The coordination-*session* scaffolding in `routes/sessions.py` (`spawn_session`,
`_spawn_coordination_session`, and the join-window state machine in `join_room`) survived Step 0
CFN-free but is now **inert** — it still writes `CoordinationSession`/`Participant` rows, but
nothing acts on the join deadline (the timer was CFN's). **Dropping the DB in Step 1 forces the
issue:** these rows lose their table. Simplest correct move for Step 1 is to reduce this to the
minimum presence shim (or stub the endpoints) rather than reimplement it — the real
replacement is **room = SLIM channel in Steps 3–4**. Leave a `# TODO(step3)` where you stub so
it isn't mistaken for finished behavior.

## Your Step 1 scope (from the bible, Part V · Step 1)

- **Search index → local JSONL.** One JSONL file of `{embedding, metadata}` per memory,
  embeddings via the **kept** `services/embedding.py` (fastembed, BAAI/bge-small-en-v1.5,
  384-dim). Implement **brute-force cosine** `memory search` in-process over it. (§11: fine at
  personal scale; a real index is a later problem.)
- **Retarget `indexer.py` / `reindex.py`** from pgvector → the JSONL index, including a
  **rebuild-from-files** path (`reindex` scans `.mycelium/rooms/**` and regenerates the JSONL).
- **Remove the DB:** delete `database.py`, drop `models.py` DB usage, remove the
  `create_db_and_tables()` call, and remove `DATABASE_URL` / `GRAPH_DB_URL` from
  `app/config.py`. Rework `/health`'s DB probe. Room/presence state that's still needed becomes
  files / in-memory.
- **Compose:** remove `mycelium-db` from `compose.yml` / `compose-dev.yml`; update CLI
  `instance.py` / `install.py` / `doctor.py` (drop DB checks/containers/`DATABASE_URL` emission,
  `db_password`/`db_port`, `database_url()` as applicable).
- **`stream.py` (SSE):** it uses asyncpg LISTEN/NOTIFY. The UI still uses SSE until Step 10 and
  the coordination bus moves to SLIM in Step 3 — so **mark it deprecated and keep a minimal SSE
  (or stub it); do not block on it.** Don't invest in a DB-free NOTIFY replacement here.
- **Conflict policy [decided, implement it]:** last-write-wins ordered by the memory's
  incrementing `version`; a write on a **stale base fails with details** (current content +
  `updated_by` + `updated_at`). **No merge handler.** (Bible §11.)

## Definition of Done

The stack runs with **no `mycelium-db` container**, and `memory set` / `get` / `ls` / `search`
(including **semantic** search) all work against **files + JSONL** with no database anywhere.

## Tests to write (end of step)

- Memory CRUD over files.
- `memory search` returns correct **top-k** over a seeded JSONL.
- `reindex` rebuilds the JSONL from the markdown files.
- Conflict = **last-write-wins**, and a **stale-base write is rejected with details**.
- Rework `conftest.py` so the suite no longer needs SQLAlchemy/SQLite.

## Verification gate (must pass before you call Step 1 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
uv run pytest tests/ -x -q

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```

Then prove the DoD by hand: bring the stack up **without** `mycelium-db` and run
`memory set` / `get` / `ls` / `search` end to end.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results. Open a PR against
`slim-native-rewrite` (same as Step 0). Deferrals to name explicitly: SSE/`stream.py` still
present (retired in Step 10), presence/session shim is temporary (SLIM in Steps 3–4), the
`abort`→`rejected` L9 subkind is **Step 3**.
