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
  a scripted SSE negotiation.

Files:
- `fixtures.ts` — the canonical data (rooms, memories, agents, plans, messages,
  episodes + L9 chains, invites, metrics), shaped to match `src/lib/api.ts`.
- `handlers.ts` — the REST router mirroring the backend endpoints.
- `stream.ts` — the scripted live SSE timeline.
- `index.ts` — `isMockMode()` + exports.

The toggle is read per-request server-side, so nothing is baked into the build and
the fixtures never reach the client bundle. To design a new state, add or edit a
room in `fixtures.ts` — no component changes needed.
