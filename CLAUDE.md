# CLAUDE.md

## Project

Mycelium: multi-agent coordination + persistent memory over a secure messaging
fabric. Agents coordinate as members of end-to-end-encrypted rooms; a negotiation
that reaches consensus compiles into a shared plan and syncs to memory.

## Structure

```
.mycelium/              Memory storage (rooms are folders, memories are markdown files)
├── rooms/{name}/       Room directories with standard namespace subdirs
└── config.toml         Project-local configuration

fastapi-backend/    FastAPI backend, room moderator + persister (Python 3.12).
                    No database: state is local markdown + a JSONL search index.
mycelium-cli/       CLI tool (typer, Rich, typed OpenAPI client) + the daemon
mycelium-client/    Generated OpenAPI client (openapi-python-client)
mycelium-frontend/  Next.js frontend (TypeScript, Tailwind)
docs/               Docs site (generated from mycelium-cli/src/mycelium/docs/),
                    demo script, design notes
mycelium-promo/     HyperFrames promo video, a code-defined HTML→MP4 walkthrough
                    (CLI install → app install → room → adapter → post positions →
                    summon the aligner → await/respond → consensus → plan → work).
                    Renders 1920x1080 H.264. `cd mycelium-promo && npm run dev` to
                    preview, `npm run render` to export to renders/*.mp4.
                    The README + docs/index.html embed the rendered MP4 via a
                    `user-attachments/assets/...` URL; these only auto-render
                    inline when uploaded via GitHub's web drag-drop (gh CLI has
                    no equivalent). After re-rendering, drag the new MP4 into a
                    PR comment to mint a fresh URL, then swap it into both embeds.
```

## Development

```bash
# Backend (no database; unit tests run against local files + temp dirs)
cd fastapi-backend && uv sync --group dev
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .

# The live-node integration slices need a running SLIM node; they skip without one:
MYCELIUM_SLIM_ENDPOINT=http://127.0.0.1:46357 uv run pytest tests/test_slim_roundtrip.py -q

# CLI (install globally)
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# CLI quality gate (matches CI); run before pushing
cd mycelium-cli && uv run ruff check . && uv run ruff format --check . \
  && uv run ty check . && uv run pytest tests/ -x -q

# Frontend
cd mycelium-frontend && pnpm install && pnpm dev
```

## Architecture

Mycelium is **SLIM-native**: one SLIM messaging node, a thin FastAPI backend, and
local files. There is **no database**.

**Rooms are SLIM group channels.** Each room is one durable AGNTCY SLIM group
channel (MLS-encrypted multicast; the node forwards only ciphertext). The always-on
backend is each room's **moderator**; agents (and the human, by proxy) are members.
`app/services/room_channels.py` owns the moderator/channel lifecycle;
`app/services/slim_client.py` wraps the `slim-bindings` client.

**State is files.** Memories are markdown with YAML frontmatter at
`.mycelium/rooms/{room}/{key}.md`. Search is a **local embedding index** (fastembed
ONNX, `BAAI/bge-small-en-v1.5`, 384-dim, no external service) persisted as JSONL
per room. `memory set` writes the markdown and updates the index; direct file
writes work too; run `mycelium reindex` to resync. Sharing is git.

**L9 rides SLIM.** Coordination messages carry additive IOC **L9** JSON envelopes:
`exchange` (ticks/replies), `commit:converged|resolved|rejected`, `knowledge`.
Agents never need to speak L9; the backend synthesizes reply envelopes from parsed
agent replies. Modules: `app/services/l9.py` (envelope construction + the subkind
table), `l9_episode.py` (episode tracking + quality metrics MPC/GAR/SCR +
`log/episodes/{short_id}.md` records), `l9_slim.py` (L9-over-SLIM channel),
`l9_models.py` (pydantic bindings vendored from outshift-open/ioc-protocols-models).

**Participation is a CLI primitive.** Any awake caller joins a room and coordinates
with two stateless HTTP calls (`app/routes/participate.py`): `mycelium await` (a
long-poll; the server holds membership via a presence lease + durable transcript
cursor, so a tick is never missed between turns) and `mycelium respond` (posts a
reply the backend records as an L9 exchange). The **daemon** (`mycelium-cli/.../
daemon/`) is an optional auto-waker for runtimes that can't wake themselves; it
cold-spawns `claude -p` on a mention, built on the same membership core
(`slim/member.py`) so the CLI and daemon paths can't drift.

**The aligner is the mediator.** Negotiation is driven by a first-party cognition
engine, the **aligner** (`app/services/aligner.py`), summoned by `@`-mention. It
runs a real **NEGMAS Stacked Alternating Offers** mechanism (`mediator.py`); its
brain is a persistent **Pi** coding-agent session (`pi_brain.py`) so it keeps memory
across rounds. It discovers issues from the agents' opening positions, brokers each
round, `@`-addresses one agent at a time over SLIM, interprets each reply into an
SAO move (`offer_snap.py` snaps near-misses / nearest numeric grid point), and
**NEGMAS owns termination**: it stops the instant the agents agree.

**Episodes.** A summon opens an **episode**, a tagged, membership-scoped negotiation
on the room's channel (a tag over the existing channel, not a separate one), 1:1 with
an L9 episode record. Each convening is a distinct episode (unique id, its own
transcript slice), recorded at `log/episodes/{id}.md`.

LLM: litellm (provider/model format, e.g. `anthropic/claude-sonnet-4-6`). The
aligner's Pi brain and the plan compiler are the LLM consumers.

## Key design decisions

- **The aligner mediates.** Agents never talk to each other directly; all
  coordination flows through the aligner. It's a first-party engine registered as a
  room citizen (`mycelium engine create aligner --kind aligner`) and summoned
  (`mycelium engine invoke aligner "…"`), not auto-run on a join window.
- **The aligner's brain is Pi (only).** The SAO mediator runs on a persistent Pi
  session; there is no litellm fallback brain. Pi ships in the backend image;
  OpenShell sandboxing (`ALIGNER_PI_OPENSHELL`) is an optional command-prefix seam,
  off by default. See `pi_brain.py`.
- **NEGMAS owns termination.** The mechanism stops at unanimity; the mediator never
  loops to the step cap (the anti-theatre property). A failed negotiation commits as
  `rejected`.
- **Faithful interpretation, never fabricated.** An unreadable proposer holds its
  own last line, never the standing offer (no phantom convergence); numeric offers
  snap to the nearest real grid point or refuse, never to a fabricated value
  (`offer_snap.py`).
- **Rooms are folders.** `.mycelium/rooms/{name}/` with standard subdirs:
  `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`,
  `plan/`. The `plan/` namespace holds the room's plan: `plan/title.md` is the
  room's display title (italic hero in the UI); other `plan/{slug}.md` files carry
  prose + `- [ ]` checklist tasks surfaced to every agent.
- **Rooms are always persistent.** Rooms are persistent namespaces for memory and
  coordination; a negotiation within a room is an ephemeral, recorded episode.
- **The CLI skill is a protocol.** Post a position → await → respond → consensus →
  plan → work. This is the value add; don't change it to an augmentation layer.
- **memory set always upserts.** `memory set` overwrites existing keys automatically
  (version increments).
- **Consensus compiles into the plan.** On convergence the aligner hands the agreed
  `{issue: value}` map to `plan_compiler.py`, an LLM stage that materializes
  `plan/tasks.md` (one shared `- [ ]` checklist with `@handle` owners) *before* the
  consensus is announced (plan-first ordering, so `await` returns once the plan
  exists). Fail-soft: a compiler outage falls back to the raw `issue=value`
  agreement. The compiler is deliberately a distinct consumer stage across an
  explicit seam, not part of the negotiation engine. `litellm.acompletion` doesn't
  work for Bedrock, so the compiler routes Bedrock models through threaded sync
  `completion`. `plan_sync.py` then syncs the compiled plan as a `knowledge` memory.
- **Server-held membership.** A turn-based agent (Claude, a subagent, a shell) can't
  hold a SLIM socket between turns, so the backend holds membership: `await`
  long-polls off a durable transcript cursor and refreshes a presence lease;
  `members()` is the union of live SLIM members and lease holders. This is why
  turn-based agents never miss a tick. The **durable inbox** (`persister.py`)
  re-serves missed point-to-point messages on rejoin (SLIM has no offline replay).
- **Git for sharing.** Rooms can be shared via git push/pull; cross-machine is the
  same channel over a shared SLIM node (`mycelium hub host` / `mycelium connect`).
- **No Ensue references in code.** We took inspiration from their API design but the
  implementation is independent.
- **L9 envelopes are additive, never required of agents.** Ticks are `exchange`,
  consensus is `commit:converged|rejected`, with episode URNs and causal
  `message.parents`. The subkind table lives in `app/services/l9.py:VALID_SUBKINDS`
  and is SLIM-native (`converged|resolved|rejected`).
- **CLI/backend SLIM+L9 duplication is guarded by a golden test.** The thin `uv
  tool` CLI can't import the backend, so `mycelium/slim/` copies the SLIM+L9
  primitives. `slim-l9-golden.json` (repo root) freezes the shared wire constants;
  both `fastapi-backend/tests/test_slim_l9_golden.py` and
  `mycelium-cli/tests/test_slim_l9_golden.py` assert against it, so neither copy can
  drift without a red unit gate.
- **SLIM security is a shared-secret PSK today (D1).** The group key derives from
  `MYCELIUM_SLIM_MASTER_SECRET` (set the same on every host that shares rooms);
  `MYCELIUM_SLIM_REQUIRE_SECRET=1` makes a host fail closed rather than fall back to
  the public dev literal. There is no per-agent identity/revocation yet: **real
  identity (JWT/SPIRE) is a hard prerequisite before anything hosted / multi-user**.
- **Adapter capability (be honest).** `claude_code` is proven; `cursor` is untested;
  `openclaw` and `hermes` are deprecated (they rode the removed SSE/coordination-tick
  model and have not been migrated to SLIM).

## Local development

> **This section is for contributors iterating on the backend source.** End users
> follow the normal install path:
> `curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` then
> `mycelium install`.

### Starting the stack

The normal `mycelium up` / `mycelium install` flow uses `compose.yml` with
`pull_policy: always` (released images), the correct path for end users. For dev,
add `compose-dev.yml`, which builds `mycelium-backend` from local source and wires
`~/.mycelium/.env` into the containers. The stack is a SLIM node + the backend (+
optional frontend/collector), with **no database**. Always run from the repo root.

```bash
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --build
```

On subsequent runs, drop `--build` unless you've changed backend code. Add
`--profile ui` for the frontend.

### LLM config

All containers get their LLM settings from `~/.mycelium/.env`, generated from
`config.toml`. Set these once (the aligner's Pi brain uses them):

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "<key>"
mycelium config set llm.base_url "<base-url>"
mycelium config apply
```

Then recreate the backend to pick up the new env:

```bash
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --force-recreate mycelium-backend
```

**Important:** `mycelium config apply` regenerates `.env` from `config.toml`. If you
edit `.env` directly, those changes are overwritten. Always use `mycelium config set`.

### Running the backend outside Docker (hot-reload)

```bash
cd fastapi-backend
uv run uvicorn app.main:app --reload --port 8000
```

No DB is needed. The SLIM node still must be running (`mycelium hub host`, or the
`slim` compose service). The aligner's Pi mediator needs `pi` on PATH when the
backend runs on the host (the image ships it; `mycelium doctor` warns if it's
missing). Update `config.toml` if you change the backend port:

```bash
mycelium config set server.api_url "http://localhost:8000"
mycelium config apply
```

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: unit tests run against local files + temp `.mycelium/` dirs (conftest.py
  sets `MYCELIUM_DATA_DIR`); the live-node SLIM slices are guarded by a reachable
  node (`MYCELIUM_SLIM_ENDPOINT`) and skip without one
- Live-LLM tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
