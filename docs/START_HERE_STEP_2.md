# START HERE — Step 2 (SLIM node + hello-world over a group)

Companion to [`START_HERE.md`](./START_HERE.md). Step 1 is **done and merged-ready**
(PR #419 against `slim-native-rewrite`); you are picking up **Step 2**. Read `START_HERE.md`
and [`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) first if you haven't — the same rules
apply. This file gives you (a) the exact state Step 1 left behind, (b) your Step 2 marching
orders, (c) the SLIM facts you must internalize before touching anything, and (d) the traps
specific to this step.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 2**, with **§7 (SLIM primer)** and **Part VI (SLIM quickstart +
   cloned source)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste** — they are AGNTCY's own examples
   and approximate the API. **The cloned bindings are the ground truth** (see §"SLIM facts"
   below); write the implementation yourself, matching the surrounding style.
4. **Verify before you edit** — paths below were accurate at the end of Step 1; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; open questions have a default. **Step 2's resolve-first
   is the identity tier — default to a dev shared secret (≥32 chars), which also seeds MLS.**
   JWT/SPIRE is a prod concern, out of scope here.

## Where Step 1 left things (your starting state)

Branch off `slim-native-rewrite` once Step 1 (PR #419) is merged, or off `step1-kill-database`.
**The database is gone.** Memory is markdown files + a local JSONL index, and the backend is a
thin, DB-free process. Concretely:

- **Store:** `services/filesystem.py` (canonical markdown + `.room.json` room sidecars) +
  `services/search_index.py` (one `.search-index.jsonl` per room, brute-force cosine) +
  `services/indexer.py`/`reindex.py` (rebuild-from-files). `services/embedding.py` (fastembed,
  384-dim) is unchanged.
- **In-process bus:** `app/bus.py` is now an **in-memory pub/sub** (replaces Postgres
  LISTEN/NOTIFY). `routes/stream.py` (SSE) subscribes to it and is **marked deprecated**
  (retired Step 10). `routes/memory.py`, `messages.py`, `sessions.py`, `plan.py` publish to it.
- **In-memory shims:** `services/local_state.py` holds messages / presence / subscriptions in
  process memory. `routes/sessions.py` is a **presence shim** (the join-window/MAS machinery is
  gone); `routes/messages.py` and `services/event_sweep.py` are in-memory. All carry
  `# TODO(step3)` markers.
- **L9 core is kept and untouched:** `services/l9.py`, `l9_episode.py`, `l9_models.py`. The
  failure subkind is **still `abort`** in `l9.py:VALID_SUBKINDS` — the flip to `rejected` is
  **Step 3**, not here.
- **No database anywhere:** `database.py`, `models.py`, alembic, and the DB deps
  (asyncpg/sqlalchemy/pgvector/agensgraph) are removed. `config.py` has no `DATABASE_URL`.
- **Docker (`docker/compose.yml` / `compose-dev.yml`):** three services remain —
  `mycelium-backend` (8000), `mycelium-frontend` (profile `ui`, 3000), `mycelium-collector`
  (profile `metrics`, 4318). **No `mycelium-db`, no CFN, no volumes block.**
- **CLI:** top-level commands are registered in `cli.py` via `app.command(name=...)(fn)` (e.g.
  `up`→`instance.start`, `down`, `pull`, `doctor`, `install`) and command *groups* via
  `app.add_typer(...)` (`room`, `memory`, `plan`, `config`, `agent`, `daemon`, …). **There is no
  `hub` group and no `connect` command yet.** `config.py`'s `MyceliumConfig` has
  `ServerConfig.api_url` and `RuntimeConfig` ports (`backend_port`, `collector_port`,
  `frontend_port`) — **no DB fields.** The daemon (`daemon/dispatch.py`) still holds an **httpx
  SSE** stream per room (SLIM retargeting is Step 5, not now).

### Carry-forward from Step 1 (acknowledge, don't fix yet)

The bus and presence/message stores are **single-process, in-memory shims** — correct for now,
replaced by the SLIM bus + durable persister in Steps 3–4. **Step 2 does not wire any of them to
SLIM.** Step 2 is *plumbing only*: stand up the node, add the binding + naming/identity helper,
add `hub host`/`connect`, and prove a throwaway two-client group round-trip. Keep the SLIM code
**isolated** from the room/coordination flow so Step 1's green stays green. The room-becomes-a-
channel wiring is **Step 3**.

## Your Step 2 scope (from the bible, Part V · Step 2)

- **Add a `slim` node service** to `compose.yml` **and** `compose-dev.yml` (image
  `ghcr.io/agntcy/slim`, port **46357**, mount a minimal node config — see bible §7a). This is
  the only heavy thing in the target stack.
- **Add the SLIM binding dependency:** Python **`slim-bindings`** (PyPI) for the backend/daemon.
  (Node `@agntcy/slim-bindings` is only needed later, if/when a TS connector lands.)
- **Naming/identity helper:** map `workspace/room/agent` → a SLIM `Name` (3-tuple
  `org/namespace/app` — proposed mapping: **org = workspace/tenant, namespace = room, app =
  agent id**). Mint a **dev shared secret (≥32 chars)** per agent; it also seeds MLS.
- **`mycelium hub host`** (spin the node, print the connect address) and **`mycelium connect
  <address>`** (store the node endpoint in config). **Same command whether self- or
  mycelium-hosted.** A new `commands/hub.py` (or fold into `instance.py`) + a node-endpoint field
  in the CLI `config.py`.
- **A throwaway harness** proving the round-trip: a moderator process creates a group channel and
  invites a second process; the second `publish`es; the moderator receives it.

**Key files:** new SLIM client-wrapper module (backend `app/services/`, reusable by the daemon),
`docker/compose*.yml`, CLI `cli.py` + new `commands/hub.py`, CLI `config.py` (node endpoint).

## SLIM facts you must internalize first (§7 + Part VI)

Read bible §7 in full. The load-bearing facts:

- **What runs:** one stateless Rust binary — the **`slim` node** (`ghcr.io/agntcy/slim`, default
  **46357**). No database. Clients embed `slim-bindings` and connect to it. The control-plane +
  SPIRE are **only** for multi-cluster/cross-org — ignore them for the MVP.
- **Group = the room:** a **multicast** channel. The **moderator** (mycelium's backend, always-on)
  creates the session and **invites** each member; others wait to be invited. **Any member's
  publish is delivered to all current members.** Presence is built in via heartbeats. MLS is
  optional, decentralized, no key server.
- **⚠ THE CRITICAL CAVEAT — no durable inbox.** SLIM does **not** retain messages for an
  offline/asleep member; rejoin only re-keys, it does **not** replay. **mycelium must build the
  persister** — but that's **Step 4**, not Step 2. Don't try to solve it here; just know why the
  round-trip harness needs both clients online at once.

**Ground-truth API (cloned under `~/Documents/GitHub/_slim-research/`, verified — prefer these
over the bible's prose):**

- **`slim-bindings/python/examples/group.py`** is a full moderator+participant group example.
  **`common.py`** shows app creation/connection. Read both before writing the wrapper.
- Shape: `slim_bindings.Name.from_string("org/ns/app")` · `service =
  slim_bindings.get_global_service()` · `service.create_app_with_secret(local_name, secret)` ·
  `await service.connect_async(client_config)` → `conn_id`. Moderator:
  `SessionConfig(session_type=SessionType.GROUP, …)` → `app.create_session(session_config,
  channel_name)`, then per member `await app.set_route_async(name, conn_id)` +
  `handle = await session.invite_async(name); await handle.wait_async()`. Passive members:
  `await app.listen_for_session_async()`. Send: `await session.publish_async(bytes)` (or
  `publish_to_async(ctx, …)` for a targeted reply). Receive: `await session.get_message_async(…)`
  — **this blocking pull loop is the wake monitor.**
- Method names in the bible's §7e (`subscribe_async`, `invite`) are approximate — **use the
  names in the examples** (`set_route_async`, `invite_async`/`wait_async`,
  `listen_for_session_async`).

## Definition of Done

`mycelium hub host` runs a `slim` node, and a test **exchanges a broadcast between two clients on
one group channel** (moderator creates + invites; participant publishes; moderator receives the
bytes). The `workspace/room/agent` → `Name` mapping is covered by a unit test.

## Tests to write (end of step)

- **Name-mapping unit test** — `workspace/room/agent` → `org/ns/app` `Name` (and back), plus the
  shared-secret minting. Must run **offline**, no node required.
- **SLIM round-trip integration test** — two clients, one group, one broadcast, received by the
  other. This needs a running `slim` node: **guard it** so the unit suite stays green without one
  (skip-if-unreachable, mirroring how the old `test_integration.py` was gated on availability), or
  spin a node in a fixture. Do **not** make the default `pytest` run depend on a live node.

## Verification gate (must pass before you call Step 2 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```

Then prove the DoD by hand: `mycelium hub host` brings up a node on `:46357`; run the round-trip
harness (two clients on one channel) and see the broadcast arrive.

## Traps specific to Step 2

- **`slim-bindings` is a native (Rust) wheel** — availability is per-platform. Pin it, and keep
  the SLIM import **lazy/isolated** in its wrapper module so backend/CLI modules that don't touch
  SLIM still import cleanly (and so a missing wheel degrades gracefully rather than breaking every
  gate).
- **Don't touch the coordination flow.** No room→channel wiring, no persister, no L9-over-SLIM —
  those are Steps 3–4. Step 2 is a standalone hello-world plus the node/naming/`hub`/`connect`
  plumbing. If you find yourself editing `routes/sessions.py` or `l9.py`, you've overshot.
- **Add the node to both compose files.** `compose.yml` (released path) *and* `compose-dev.yml`.
- **`hub host` = `connect` target, same command for anyone.** Self-hosted is the default;
  a mycelium-hosted rendezvous is just a different address (MLS makes the node a blind ciphertext
  forwarder). Don't fork the command per host.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results. Open a PR against
`slim-native-rewrite` (same as Steps 0–1). Deferrals to name explicitly: SLIM is **not yet
wired** into rooms/coordination (Step 3), there is **no durable inbox/persister** yet (Step 4),
the daemon still uses **httpx SSE** (retargeted in Step 5), and the `abort`→`rejected` L9 subkind
is **Step 3**.
