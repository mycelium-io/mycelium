# Smoke-Test Handoff — help Julia see the SLIM-native rewrite actually work

> **You are a fresh Claude Code session.** Your job: get the just-completed SLIM-native
> rewrite **running end-to-end on Julia's machine** so she can *see* it work — bring the
> stack up, drive one full `room → agent → converge → plan → memory → UI` flow, and debug
> whatever breaks **with her, in small visible steps.** This is a hands-on validation, not
> a code review.

## Read this honestly first: what's proven vs. not

The rewrite replaced a 4-service closed-source "CFN" cluster + a Postgres/AgensGraph fork
with **one `slim` messaging node + a thin FastAPI backend + local markdown/JSONL files — no
database.** It shipped in 10 reviewed steps (all merged into the `slim-native-rewrite`
branch). See `docs/slim-native-rebuild-bible.md` (the authoritative spec; Part III = repo
map, Part V = what each step did, Part VI = SLIM quickstart) and `docs/START_HERE.md`.

**Proven:** each step's fast unit tests, and a cumulative *live-node integration suite* that
was run by hand against a bare `slim:1.4.0` node during development (L9 exchange, causal
ordering, episode abort, durable inbox, connector wake, human mention, aligner converge,
plan+memory sync, cross-machine reindex).

**NOT proven (your job):** the **full product stack via docker compose** (slim node +
backend + frontend together), a **real `claude` agent** cold-spawned by the daemon actually
waking and replying over SLIM, and the **UI** showing it. The CI job that would run the live
suite (`integration-slim`) has **never executed**. So: **expect rough edges. Finding and
fixing them is the point.** Move in small steps; confirm each green light with Julia before
the next.

## Orient (do this first)

1. `cd /Users/juliavalenti/Documents/GitHub/mycelium`
2. Make sure you're on the integrated branch: `git checkout slim-native-rewrite && git pull`.
   (Everything below assumes this branch — `main` does NOT have the rewrite.)
3. Skim `docs/START_HERE.md`, then `docs/cross-machine.md` — it has a **"Watching it in the
   browser"** section that is essentially the manual acceptance script; lean on it.
4. **Trust the code, not old docs for exact commands.** `CLAUDE.md` is stale on architecture
   (it still describes CFN/AgensGraph). Verify CLI flags with `mycelium --help` /
   `mycelium <cmd> --help`, and read the *current* compose at
   `mycelium-cli/src/mycelium/docker/compose.yml` + `compose-dev.yml`.

## Prereqs to confirm with Julia

- **Docker** running.
- **The `claude` CLI installed and authenticated** on this machine with **API credits** —
  the daemon cold-spawns `claude -p` for a Claude Code agent's turn, so a real agent reply
  **costs tokens**. (Check `which claude`.)
- **LLM config** for the backend: the plan compiler (and any LLM stage) needs a model +
  key. Set via `mycelium config set llm.model/llm.api_key/llm.base_url` then
  `mycelium config apply`. (The aligner's *base* verdict is deterministic math and needs no
  LLM, but plan compilation does.)
- **`mas_id` / `workspace_id` are gone** — removed in the rewrite. Don't chase old config
  errors about them. Identity is now a dev shared secret over SLIM (fine for single-host).

## The smoke-test ladder (climb it; stop and debug where it breaks)

**Rung 1 — Stack comes up.** Bring up the dev stack (builds backend from source):
```
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml up -d --build
```
Confirm: the **`slim` node** container is healthy (listening on `:46357`), the **backend**
answers `GET /health`, and (if you start the `ui` profile) the **frontend** serves on `:3000`.
The one non-obvious trap: the slim **node image `1.4.0` must match `slim-bindings 1.4.x`** or
you'll see `public key length is invalid` — do not bump one without the other. *If this rung
fails, that alone is a valuable finding (the compose/install post-rewrite is untested).*

**Rung 2 — Memory works with no database.** The foundation:
```
mycelium room create smoke
mycelium memory set smoke status/hello "it works" && mycelium memory get smoke status/hello
mycelium memory ls smoke && mycelium memory search smoke "works"
```
Confirm files under `~/.mycelium/rooms/smoke/` (markdown) + a `.search-index.jsonl`, and that
search returns the hit. No DB anywhere.

**Rung 3 — One Claude Code agent rides the fabric (the dogfood).** Register an agent, run the
daemon, and wake it:
- `mycelium agent create/add …` (check `--help`) to register a `claude_code` agent in `smoke`
  with a `cwd`.
- Start the daemon (`mycelium daemon …` — check `--help`; it must be running for cold-spawn).
- Confirm the daemon's **connector joins the room's SLIM channel** (logs: "connector joined").
- Post a message that `@`-mentions the agent into the room; confirm it **wakes, a `claude -p`
  turn spawns, and its reply lands back in the room.** This is Step 5 — the core proof that an
  agent coordinates over SLIM. Watch daemon logs closely; this is the most likely place to hit
  a real bug.

**Rung 4 — Converge → plan → memory.** Get positions into the room (two agents, or seed
exchange messages), then `@`-summon the **aligner** (default handle `aligner`). Confirm it
emits `commit:converged`/`rejected` with MPC/GAR/SCR, the backend compiles **`plan/tasks.md`**,
and the converged content **syncs as a `knowledge` write** into the local store. (The
`persona-before-and-after` or `demo` flows, if present/working, may help seed a realistic
multi-agent scenario — but they may be stale; prefer a hand-driven minimal case first.)

**Rung 5 — See it in the browser.** Open the frontend, open the `smoke` room, and use the
**L9 protocol inspector** (an "L9" tab) to watch the L9 frames stream (kind/subkind, episode,
metrics) and the episode causal chain; trigger a **consent prompt** (an `@`-invite of an agent
not in the room) and accept/decline it. This is the AOP showcase and the visible payoff.

## Known gotchas (save yourself time)

- **Version pin:** slim node `1.4.0` ↔ `slim-bindings 1.4.x` (Rung 1).
- **Daemon must be running** for `claude_code`/`cursor` (cold-spawn) agents; `openclaw`/`hermes`
  adapters are **known-broken** post-rewrite (debt D11) — don't test them.
- **A member host still needs a backend** for search/reindex (the CLI has no embedder).
- **MLS is on** for room channels; the dev shared secret is consistent on one host, so
  single-machine "just works." Cross-machine is a later exercise (`docs/cross-machine.md`).
- **Costs tokens:** every real agent turn is a `claude -p` call.
- **Open debts** that may bite are catalogued in the bible **Part IV (register D1–D12)** — e.g.
  silent best-effort degradation (D3/D6): if "nothing happens," check backend + daemon logs,
  because a lot of SLIM failures degrade quietly to "no channel."

## How to work with Julia

Go rung by rung. After each, **show her the concrete evidence** (the file, the log line, the
message in the room, the frame in the inspector) so she can see it with her own eyes. When
something breaks — and something will, this is the first real run — diagnose it together,
fix the smallest thing, and re-run that rung. The deliverable is Julia watching a real agent
coordinate over SLIM and a plan appear, not a passing test count.

If you fix real bugs along the way, they belong on the `slim-native-rewrite` branch (or a
small PR into it); note anything you defer against the bible's debt register.
