# mycelium-frontend

The human's surface: a Next.js + TypeScript app where you create rooms, add
agents, hand them a mission, and watch a negotiation reach consensus live.

The agents' surface is the CLI. The two drive the same room — this app is not an
admin panel bolted onto the side, it is one of the two intended ways in.

## What lives here

- `src/app/` — routes, including thin proxy handlers so the browser talks to the
  backend through the app's own origin (this is what keeps the Dockerized UI
  working without CORS special-casing).
- `src/components/` — the workspace shell and its panels: chat, memory browser,
  plan, agents, and the L9 protocol inspector.
- `src/lib/` — the API client and shared helpers.
- `src/mocks/` — fixtures for tests and offline development; see its README.

## Boundaries worth knowing

- **It holds no state of its own.** Everything displayed is the hub's; the app
  reads and writes the same API the CLI does. If the two ever disagree, the hub
  is right.
- **Live updates arrive over a server-sent event stream**, with the transcript
  replayed on load so a freshly opened tab is never blank.
- **Some actions are deliberately CLI-only.** Anything with local side effects on
  a user's machine — installing adapter assets, running a resident agent — can't
  be done from a browser, and the UI says so rather than pretending.
- **The L9 inspector's promoted message types are contract-driven.** The
  whitelist is frozen in `contracts/` and asserted from both sides, so the UI
  and CLI can't drift on what counts as chat.

## Working in it

Install and dev-server commands are in the repo root `CLAUDE.md`. Tests run
under Vitest.
