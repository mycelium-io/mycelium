# Fake-backend mode (`src/mocks`)

Render the **real UI** in every state — populated, in-progress, empty — with **no
SLIM node, no LLM, and no backend server**. This is the frontend analogue of the
backend/CLI fake stacks: one command to reach any state, for design and
visual-regression work.

## Run it

```bash
pnpm dev:mock        # = MYCELIUM_UI_MOCK=1 next dev
```

Then browse:
- `/` — the rooms dashboard (four seeded rooms).

Every room is a small online coffee shop at work, so what you see reads as
something a real team does:

- `/room/checkout` — a rich, **converged** room: adding Apple Pay and fixing
  double charges. Memories, agents, board rows with pull requests and CI, flows
  running in task threads, and a finished negotiation in the inspector.
- `/room/subscription-pricing` — an **in-progress** negotiation over what the
  coffee subscription costs, with a bridged A2A agent, and a scripted live
  negotiation that resolves over SSE while you watch.
- `/room/storefront` — the room **under load**: a dozen people and three dozen
  agents, each working one website ticket.
- `/room/scratch` — a brand-new **empty** room (every empty state).
- `/metrics` — populated observability (tokens/cost by agent + model, hosts).

## How it works

Both Next route handlers consult the mock layer first when `MYCELIUM_UI_MOCK=1`:

- `src/app/api/[...path]/route.ts` → `handleMock(req)` serves fixtures for any
  `/api/*` request it recognizes; unrecognized routes return `null` and fall
  through to the real backend (so it degrades, never hangs).
- `src/app/api/stream/route.ts` → `mockStream(name)` on the room channel replays
  a scripted SSE negotiation, and forwards whatever the room's writes put on its
  stream.

Writes behave the way the hub's do: a posted message is stored and arrives on
the stream (the channel only ever appends what arrives live), `POST /tasks` mints
a `work/` row with a thread of its own and raises a `filed` notice, and
`/fields` and `/assignments/{claim,release,resolve}` move a row and say so. `POST /engines` registers an engine as its `agents/<handle>` manifest. The
store lives for the dev server's life; restart it to start over.

## The demo scenario

```bash
MYCELIUM_UI_MOCK=1 MYCELIUM_UI_MOCK_SCENARIO=demo next dev
```

swaps `checkout` for the room *before* its double-charge story (real
timestamps, no @builder yet) and adds a director (`demo.ts`) that plays the
agents' side when a person does theirs: an agent added from **Your machine**
joins and says hello; a task filed for it is claimed in its thread;
`@conductor review @builder @reviewer` in that thread runs the review flow,
which ends with @reviewer filing a decision the two disagree on; and `@aligner`
in the decision's thread brokers an agreement that compiles into new rows.
Each act plays once per server. `mycelium-promo/` records the product demo
through it.

## The Learn scenario

```bash
MYCELIUM_UI_MOCK=1 MYCELIUM_UI_MOCK_SCENARIO=learn:pair-idea next dev
```

adds an `orders` room in the state one Learn take starts from (`learn.ts`
lists them), Sam's machine with a runner that asks before it starts anything,
and a director for that take: a pair working a task in its thread, an agent
launched into a worktree, two teammates' agents and the aligner, pull requests
moving on the board, a swarm checking in and splitting its task.
`mycelium-promo/learn/` records the Learn videos through it.

Files:
- `fixtures.ts` — the canonical data (rooms, memories, agents, plans, messages,
  episodes + packet chains, invites, metrics), shaped to match `src/lib/api.ts`.
- `handlers.ts` — the REST router mirroring the backend endpoints.
- `stream.ts` — the scripted live SSE timeline.
- `live.ts` — the room streams writes publish to, shared across route modules.
- `director.ts` — the writes a scripted agent makes (say, file, claim, resolve), shared by the scenarios.
- `demo.ts` — the demo scenario's room and director.
- `learn.ts` — the Learn scenario's room and director, one take at a time.
- `index.ts` — `isMockMode()` + exports.

The toggle is read per-request server-side, so nothing is baked into the build and
the fixtures never reach the client bundle. To design a new state, add or edit a
room in `fixtures.ts` — no component changes needed.
