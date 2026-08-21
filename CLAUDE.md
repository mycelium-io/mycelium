# CLAUDE.md

## Project

Mycelium: multi-agent coordination + persistent memory over a secure messaging
fabric. Agents coordinate as members of end-to-end-encrypted rooms; a negotiation
that reaches consensus compiles into a shared plan and syncs to memory.

## Structure

```
.mycelium/              Memory storage (rooms are folders, memories are markdown files)
├── rooms/{name}/       Room directories with standard namespace subdirs
│   └── skills/         Skills = memories in this namespace, promoted (SKILL.md-style)
└── config.toml         Project-local configuration

fastapi-backend/    FastAPI backend, room moderator + persister (Python 3.12).
                    No database: state is local markdown + a JSONL search index.
mycelium-cli/       CLI tool (typer, Rich, typed OpenAPI client)
mycelium-client/    Generated OpenAPI client (openapi-python-client)
mycelium-frontend/  Next.js frontend (TypeScript, Tailwind)
docs/               Docs site (generated from mycelium-cli/src/mycelium/docs/),
                    demo script, design notes
mycelium-promo/     HyperFrames promo video, a code-defined HTML→MP4 walkthrough
                    (CLI install → app install → room → adapter → post positions →
                    summon the aligner → await/respond → consensus → plan → work →
                    distill the room to memory via the synthesizer). The app-screen
                    mockups mirror the frontend's workspace shell + dark design tokens.
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

# Generate the OpenAPI client (NOT committed — a build artifact, #613). From
# the committed openapi.json, no backend needed. Run once after a fresh clone
# and whenever the backend API changes (then `snapshot-openapi.sh` to refresh
# the spec). CI + the wheel/binary builds run this themselves.
SPEC_FILE=openapi.json ./scripts/gen-mycelium-client.sh

# Regenerate the docs site (docs/*.html + docs/llms-full.txt) from the markdown
# under mycelium-cli/src/mycelium/docs/, the @doc_ref decorators, and the config
# schema. Needs the OpenAPI client above. Run it in any PR that touches those
# sources — CI fails on drift.
cd mycelium-cli && uv run python ../docs/generate_docs.py

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

**State is files on the hub.** Memories are markdown with YAML frontmatter at
`.mycelium/rooms/{room}/{key}.md`. Search is a **local embedding index** (fastembed
ONNX, `BAAI/bge-small-en-v1.5`, 384-dim, no external service) persisted as JSONL
per room. `memory set` writes the markdown and updates the index. This is the
**hub's internal storage**, not a client surface: every other machine is a thin
client that reads and writes it over HTTP (see **The spoke is a thin client**).
Git can version or back up the files, but it is **not** the sharing path — see
**Sharing is the live channel** below.

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
reply the backend records as an L9 exchange). An agent is a **resident** runtime —
the user's own Claude Code / Cursor session — kept woken with `mycelium await
--loop --exec <cmd>`, which loops `await` → reason → `respond`. The loop *is* the
wake; there is no cold-spawn. (The old daemon that cold-spawned `claude -p` per
mention was removed — it discarded context every turn. Cold-start-on-demand, waking
a handle when nothing is resident, returns later via herdr + per-agent identity;
see issue #446.)

**The aligner is the mediator.** Negotiation is driven by a first-party cognition
engine, the **aligner** (`app/services/aligner.py`), summoned by `@`-mention. It
runs a real **NEGMAS Stacked Alternating Offers** mechanism (`mediator.py`); its
brain is a persistent **Pi** coding-agent session (`pi_brain.py`) so it keeps memory
across rounds. It checks the opening positions for a term the agents are using in
different senses (one clarifying round if so, none otherwise), discovers issues from
those positions, brokers each round, `@`-addresses one agent at a time over SLIM,
interprets each reply into an SAO move (`offer_snap.py` snaps near-misses / nearest
numeric grid point), and **NEGMAS owns termination**: it stops the instant the agents agree.

**Episodes.** A summon opens an **episode**, a tagged, membership-scoped negotiation
on the room's channel (a tag over the existing channel, not a separate one), 1:1 with
an L9 episode record. Each convening is a distinct episode (unique id, its own
transcript slice), recorded at `log/episodes/{id}.md`.

LLM: **Pi everywhere** (provider/model format, e.g. `anthropic/claude-sonnet-4-6`).
The aligner's brain, the plan compiler, and the `mycelium doctor` / `/health`
completion probe all shell out to the `pi` binary the backend image ships; there
is no litellm dependency.

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
- **Rooms are folders on the hub.** `.mycelium/rooms/{name}/` with standard subdirs:
  `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`,
  `plan/`. The `plan/` namespace holds the room's plan: `plan/title.md` is the
  room's display title (italic hero in the UI); other `plan/{slug}.md` files carry
  prose + `- [ ]` checklist tasks surfaced to every agent. Direct file writes still
  work — that's a hub-operator escape hatch (run `mycelium memory reindex` after),
  not the client model.
- **The spoke is a thin client.** Any non-hub machine keeps **no local `.mycelium/`
  replica**; there is one store, the hub's. `memory get`/`ls`/`search` and the
  category views all resolve against the backend memory API, so a spoke with no
  files still reads the room — and an unreachable hub is reported plainly rather
  than silently answered from something stale (`commands/memory.py:_hub_session`).
- **Rooms are always persistent.** Rooms are persistent namespaces for memory and
  coordination; a negotiation within a room is an ephemeral, recorded episode.
- **The CLI skill is a protocol.** Post a position → await → respond → consensus →
  plan → work. This is the value add; don't change it to an augmentation layer.
- **memory set always upserts.** `memory set` overwrites existing keys automatically
  (version increments). Frontmatter the store doesn't manage is user data: it
  survives a rewrite rather than being dropped, and `MemoryCreate.meta` (CLI:
  `--meta k=v`, `--expandable`) writes it.
- **Memories interlink; the link index is derived.** `myc://key` (canonical) and
  `[[key]]` (shorthand) are the same edge, plus `![[key]]` transclusions and typed
  frontmatter relations (`supersedes`, `depends-on`, `part-of`, `relates-to`).
  `app/services/links.py` parses them into `.link-index.jsonl` beside the embedding
  index — same contract: derived from the markdown, rebuildable, upserted on every
  write. It's persisted rather than derived-on-read because backlinks are the whole
  point (the blast radius of changing a leaf) and deriving them means reparsing every
  file on every memory open. Links are room-local; `myc://rooms/{other}/{key}` parses
  but resolves to a `cross_room` error.
- **Transclusion is opt-in on the target, and depth 1.** `![[key]]` embeds a memory
  only when its frontmatter says `expandable: true`; anything else is an integrity
  error, never a silent inclusion. Expanded text is inserted verbatim, so a marker
  inside it stays literal — cycles are structurally impossible and expansion size is
  bounded, with no depth cap to tune. A marker that can't expand is left exactly as
  written and reported, so a refused embed never reads as an empty definition.
- **Skills are memories, promoted.** A skill is just a memory under a room's
  `skills/` namespace (SKILL.md-style markdown + frontmatter, with the one-line
  `description` in frontmatter). The same way `agents/<handle>` memories are
  promoted into a members panel and `decisions/` into a category view, `skills/` is
  promoted into a thin skills surface — `mycelium skill …` and
  `/api/rooms/{room}/skills` (`app/services/skills.py`, `app/routes/skills.py`).
  Room-scoped, like memory; no separate store, and a skill is reachable as a memory
  too (writes go through the memory upsert path, so they're indexed/linked/broadcast
  like any memory). **In the GUI there is deliberately no dedicated skills rail** —
  a skill shows up in the Memory list like any `skills/…` memory, with a small
  "skill" tag in the detail view (`memory-detail.tsx`); the frontend's only
  skill-specific call is the composer's `/` autocomplete. The surface keeps prose;
  it does not execute skills — that's the participation/engine layer's concern.
- **Three composer sigils, one mechanism.** The chat composer
  (`room-chat-box.tsx`) autocompletes `@` → agents, `[[` → room memories (inserts
  `[[key]]`, which resolves to `myc://` and is clickable in chat), and `/` → the
  room's skills (inserts `/name`). One cursor-prefix detector feeds one candidate
  popover; `[[` is matched before `/` and `@` since a memory key can contain
  slashes. Skills insert a reference token — the resident agent/engine interprets
  it; the composer never runs the skill.
- **Consensus compiles into the plan.** On convergence the aligner hands the agreed
  `{issue: value}` map to `plan_compiler.py`, an LLM stage that materializes
  `plan/tasks.md` (one shared `- [ ]` checklist with `@handle` owners) *before* the
  consensus is announced (plan-first ordering, so `await` returns once the plan
  exists). Fail-soft: a compiler outage falls back to the raw `issue=value`
  agreement. The compiler is deliberately a distinct consumer stage across an
  explicit seam, not part of the negotiation engine. It runs a one-shot `pi` turn
  (a throwaway session, off the event loop via `asyncio.to_thread`), like every
  other mycelium cognition call. `plan_sync.py` then syncs the compiled plan as a
  `knowledge` memory.
- **Server-held membership.** A turn-based agent (Claude, a subagent, a shell) can't
  hold a SLIM socket between turns, so the backend holds membership: `await`
  long-polls off a durable transcript cursor and refreshes a presence lease;
  `members()` is the union of live SLIM members and lease holders. This is why
  turn-based agents never miss a tick. The **durable inbox** (`persister.py`)
  re-serves missed point-to-point messages on rejoin (SLIM has no offline replay).
- **Sharing is the live channel.** Cross-machine sharing is the same SLIM channel over a
  shared node (`mycelium hub host` / `mycelium connect`), plus
  `mycelium room clone --from <api-url>` for a point-in-time HTTP snapshot. Git can back
  up or version the `.mycelium/` files but is **not** a sharing mechanism — no room flow
  pushes or pulls over git.
- **No Ensue references in code.** We took inspiration from their API design but the
  implementation is independent.
- **L9 envelopes are additive, never required of agents.** Ticks are `exchange`,
  consensus is `commit:converged|rejected`, with episode URNs and causal
  `message.parents`. The subkind table lives in `app/services/l9.py:VALID_SUBKINDS`
  and is SLIM-native (`converged|resolved|rejected`).
- **CLI/backend SLIM+L9 duplication is guarded by a contract test.** The thin `uv
  tool` CLI can't import the backend, so `mycelium/slim/` copies the SLIM+L9
  primitives. `contracts/slim-l9-wire.json` freezes the shared wire constants;
  both `fastapi-backend/tests/test_slim_l9_wire.py` and
  `mycelium-cli/tests/test_slim_l9_wire.py` assert against it, so neither copy can
  drift without a red unit gate.
- **The HTTP-API JWT gate is opt-in and off by default.** `app/services/auth.py`
  validates a bearer JWT against configured issuers + JWKS (`[auth]` in
  config.toml → `AUTH_*` env). It's an app-wide FastAPI dependency, so a new route
  is gated by default; health/docs stay public. Trust is a list of issuers matched
  by exact `iss`, each with its own keys and default role — that's how a workload
  trust root slots in later without issuer-specific code. Off by default is a
  hard requirement, not a default worth revisiting: auth must never block the
  try-it path. The localhost bypass reads the request's peer address, so it does
  **not** fire for a containerized backend (published-port traffic looks like LAN
  traffic) — the local tier is served by leaving auth off.
- **SLIM channel identity is a two-rung ladder, and it starts off.** `slim.identity` /
  `SLIM_IDENTITY` selects the tier; both are implemented (`slim_identity.py` + its
  CLI mirror), and the constants are frozen in `contracts/slim-l9-wire.json`.
  - `psk` (**default**, #567) — the group key derives from
    `MYCELIUM_SLIM_MASTER_SECRET`, set the same on every host that shares rooms. Zero
    infra, no per-member identity. `MYCELIUM_SLIM_REQUIRE_SECRET=1` makes a host fail
    closed rather than fall back to the public dev literal.
  - `signerjwt` (#476) — the floor: each member mints its own self-signed ES256
    credential and registers its public JWK on the room roster, so members are
    cryptographically distinct MLS participants with no external infra.

  Selecting `signerjwt` with no resolvable material degrades to `psk` with a one-time
  warning unless `MYCELIUM_SLIM_IDENTITY_REQUIRE=1` fails closed. Per-member
  revocation (#590 — drop the JWK, no room-wide re-key) ships. What still gates
  anything hosted / multi-user is turning identity on at all — not a missing
  capability.
- **The SPIRE tier is gone, not deprecated (#668).** `slim.identity=spire`, the
  `spire_registry` module, the `spire` compose profile and its server/node-daemon
  services were removed outright, matching the openclaw/hermes precedent (#503).
  It attested the backend to itself on one box — SPIRE server and node daemon
  co-located with the workload they vouched for — so it bought short-lived
  process-bound credentials, not the cross-trust-domain attestation the name
  signals, and it was the stack's biggest source of operational breakage
  (recreating the backend orphaned the daemon's PID-namespace link). Don't
  reintroduce it as an identity option; the conditions for reviving it are #669,
  and they start with a real client-held multi-party topology (#662) for it to
  attest across.
- **Custodial sessions are server-side, and off by default (#666).** Under an
  identity tier (`signerjwt`) the backend stops impersonating actors and
  becomes the **custodian of N per-actor MLS sessions** — one genuine MLS member per
  `(room, actor)`, keyed by handle (`app/services/custody.py`). The name is the term
  of art: *custodial* (the custodian holds your keys for you, like a custodial
  wallet); server-side is the custodial rung, client-held is the non-custodial one.
  `respond(@alice, …)` sends through @alice's session, so attribution is cryptographic
  on the wire (not a backend-stamped L9 field) and room access is MLS group
  membership, not app logic. All sessions live in the backend process, so the
  moderator App + aligner/plan/memory/L9 still read plaintext — cognition is
  preserved. **Under the PSK default nothing changes** (byte-for-byte;
  `MYCELIUM_CUSTODY_DISABLE=1` forces the single-moderator path even under identity),
  and persistence structurally requires the identity provider/verifier pair anyway (a
  custodial session cannot run on PSK). Per-session MLS state persists in an encrypted
  SQLite store (passphrase = `HMAC(MYCELIUM_CUSTODY_STORE_SECRET, ws/room/handle)`);
  on restart `restore_sessions` revives every session with **no re-invite** (proven
  across a real two-process kill/restart). **Honest scope boundary (keep it honest in
  code + the user-facing guides):** custodial means the hub still holds
  every key + plaintext; this hardens the wire + attribution + access-by-membership,
  and it is **NOT** E2E-from-the-hub.
- **GUI server state is one SWR cache; client state stays local.** Every room
  read in the frontend goes through `mycelium-frontend/src/lib/room-data.ts` —
  typed SWR hooks keyed `["room", name, resource]`, so N panels reading the same
  resource make one request and share one cache entry (the composer's `@`
  popover and the Members rail are two views of one `useRoomRoster`). SWR owns
  polling, refocus and dedup, so components hold no `setInterval` and no
  fetched-data `useState`; a pushed SSE event calls `useRoomRevalidate(room)`
  rather than threading a refresh counter down as a prop. A store (Zustand) is
  reserved for genuine client state — which rail is open, what's selected — not
  for anything the hub owns.
- **Adapter capability (be honest).** `claude_code` is proven; `cursor` is untested.
  `openclaw` and `hermes` are **gone**, not deprecated — they rode the removed
  SSE/coordination-tick model and their packages were deleted (#503). Don't
  reintroduce them as adapter options.

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
