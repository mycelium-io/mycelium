# fastapi-backend

The always-on hub process: each room's **moderator**, the owner of its memory,
and the host of the cognition engines.

There is **no database**. A room's durable state is files — markdown with YAML
frontmatter under the data directory — plus a JSONL embedding index for search.
Anything that looks like it needs a schema migration probably belongs in a file
instead.

## What lives here

- `app/routes/` — the HTTP API. This is the only surface clients touch; the CLI
  and the frontend are both just callers of it.
- `app/services/` — the actual work: SLIM channel + moderator lifecycle, L9
  envelope construction and episode tracking, the aligner and synthesizer
  engines, memory persistence and the search index, plan compilation.
- `tests/` — see its own README for how the suite is sliced.

## Boundaries worth knowing

- **The backend is the hub, and the hub owns the store.** Other machines keep no
  replica; they read and write this one over HTTP. A read reflects what the room
  actually says, so there is no sync step to forget.
- **The backend moderates; it does not think for agents.** It brokers, records,
  and persists. Agent reasoning happens in the agents' own runtimes.
- **Engines are summoned, never ambient.** Nothing runs on a timer or a join
  window; an engine wakes on an `@`-mention and goes back to sleep.
- **LLM calls shell out to `pi`.** There is no provider SDK dependency here.

## Working in it

Setup, the test command, and the lint/typecheck gate are in the repo root
`CLAUDE.md`. When the backend is running, the API documents itself at `/docs`.

`openapi.json` at the repo root is the committed snapshot of that API, and the
typed clients are generated from it rather than committed. Change a route or a
schema and you owe the snapshot a refresh — `make openapi` (equivalently
`scripts/snapshot-openapi.sh`, which reads the spec straight off the app object,
no server needed). CI runs the same dump and fails if it disagrees with the
committed file.
