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
- `/` — the rooms dashboard (three seeded rooms).
- `/room/atlas-migration` — a rich, **converged** room: memories, agents, a
  compiled plan with checked-off tasks, and a finished L9 episode in the inspector.
- `/room/pricing-model` — an **in-progress** negotiation: no plan yet, a pending
  consent invite (the dialog pops), and a scripted live negotiation that resolves
  over SSE while you watch.
- `/room/scratch` — a brand-new **empty** room (every empty state).
- `/metrics` — populated observability (tokens/cost by agent + model, hosts).

## How it works

Both Next route handlers consult the mock layer first when `MYCELIUM_UI_MOCK=1`:

- `src/app/api/[...path]/route.ts` → `handleMock(req)` serves fixtures for any
  `/api/*` request it recognizes; unrecognized routes return `null` and fall
  through to the real backend (so it degrades, never hangs).
- `src/app/api/rooms/[name]/messages/stream/route.ts` → `mockStream(name)` replays
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
