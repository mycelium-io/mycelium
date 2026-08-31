# mycelium

A self-hosted coordination layer for multi-agent systems: a **board** of **tasks**, each bound to its own **thread**, over a secure SLIM messaging fabric. Agents claim tasks and coordinate inside their threads; negotiation (via the **aligner**) is one optional activity that can happen inside a thread, not the container work is born from.

This file is the maintainer's hint to a [tiny-teams-with-tokens](https://github.com/juliarvalenti/tiny-teams-with-tokens) ingest agent generating Mycelium's status wiki. It's not the README and not a substitute for reading the actual code — it's a pointer to *where to look first* and *what's easy to misdescribe*.

## Read these first

- [CLAUDE.md](CLAUDE.md) — authoritative design rules + architecture overview. Read this before anything else.
- [README.md](README.md) — user-facing pitch and quick start.
- [docs/index.html](docs/index.html) — presentation deck (more conceptual framing), including the [Board](https://mycelium-io.github.io/mycelium/index.html#board) section.
- [docs/concepts.html](docs/concepts.html) — the core concepts (rooms, tasks & threads, memory, L9, engines) in depth.
- [docs/adapters.html](docs/adapters.html) — adapters, including the [A2A bridge](https://mycelium-io.github.io/mycelium/adapters.html#adapter-a2a).
- [docs/demo-script.md](docs/demo-script.md) — narrative walkthrough of a coordination flow.

## Repo layout

Mycelium is a multi-component monorepo. When you describe "the architecture" you should mention all of these by their actual roles:

- [`fastapi-backend/`](fastapi-backend/) — the coordination engine (Python 3.12, FastAPI). No database: state is local markdown files + a JSONL search index. Runs the SLIM messaging node's counterpart services: room moderation, the board/task projection, the aligner/synthesizer engines, the A2A bridge, L9 envelope construction, the persister.
- [`mycelium-cli/`](mycelium-cli/) — the user-facing CLI (typer + Rich). The primary surface most users touch, and the whole agent-side participation surface (`await`/`respond`, `board`). Hosts adapter logic for Claude Code (proven) and Cursor (untested).
- [`mycelium-client/`](mycelium-client/) — auto-generated OpenAPI client. Treat as build output; don't document its internals.
- [`mycelium-frontend/`](mycelium-frontend/) — Next.js + Tailwind UI, part of the stack `mycelium up` brings up. The board is the primary screen; there is no separate Negotiate pane or Episodes rail.
- [`mycelium-promo/`](mycelium-promo/) — HyperFrames promo video (HTML→MP4), redone around the board. Out of scope for the wiki.
- [`docs/`](docs/) — presentation site + demo script + agent-facing setup runbook (`docs/agents.md`).

## Where the actual logic lives

If you're documenting how Mycelium works, ground every claim against one of these:

- [`fastapi-backend/app/main.py`](fastapi-backend/app/main.py) — backend entrypoint.
- [`fastapi-backend/app/services/tasks.py`](fastapi-backend/app/services/tasks.py) — a **task**: a board row bound one-to-one to its own **thread** (an episode URN), minted the moment the row is created. The primary unit of work; supersedes the old `plan/` store, which is retired.
- [`fastapi-backend/app/services/board/`](fastapi-backend/app/services/board/) — the board projection: rows fold in their episode context; cockpit/kanban/table/timeline views are the same filter/sort/group pipeline over any namespace with `status`/`assignee`/`priority`-shaped frontmatter.
- [`fastapi-backend/app/services/aligner.py`](fastapi-backend/app/services/aligner.py), [`mediator.py`](fastapi-backend/app/services/mediator.py), [`pi_brain.py`](fastapi-backend/app/services/pi_brain.py) / [`pi_session.py`](fastapi-backend/app/services/pi_session.py) — the aligner: a NEGMAS SAO mediator, summoned *inside a task's thread*, whose brain is a persistent Pi coding-agent session. NEGMAS owns termination. Not the container tasks are born from — one optional activity inside one.
- [`fastapi-backend/app/services/synthesizer.py`](fastapi-backend/app/services/synthesizer.py) — the second engine kind: `@`-summoned, compiles a room's memory into a briefing at `context/synthesis`.
- [`fastapi-backend/app/services/a2a_bridge.py`](fastapi-backend/app/services/a2a_bridge.py), [`a2a_server.py`](fastapi-backend/app/services/a2a_server.py) — the A2A bridge: any agent that speaks the open Agent2Agent protocol can join a room (outbound, via a backend-held seat) or a room can be exposed as an A2A agent to an external client (inbound). Plain HTTPS, not SLIMRPC; the aligner never learns a member is remote.
- [`fastapi-backend/app/services/l9.py`](fastapi-backend/app/services/l9.py), [`l9_episode.py`](fastapi-backend/app/services/l9_episode.py), [`l9_slim.py`](fastapi-backend/app/services/l9_slim.py) — L9 epistemic envelopes, implemented in-house (not consumed from upstream), plus episode/thread tracking and the MPC/GAR/SCR quality metrics.
- [`fastapi-backend/app/services/room_channels.py`](fastapi-backend/app/services/room_channels.py), [`slim_client.py`](fastapi-backend/app/services/slim_client.py) — the SLIM messaging node integration: room = SLIM group channel, moderator/channel lifecycle.
- [`fastapi-backend/app/services/embedding.py`](fastapi-backend/app/services/embedding.py), [`indexer.py`](fastapi-backend/app/services/indexer.py), [`reindex.py`](fastapi-backend/app/services/reindex.py) — fastembed (`BAAI/bge-small-en-v1.5`, 384-dim, local ONNX) search index over memory. No pgvector, no external embedding service.
- [`fastapi-backend/app/routes/`](fastapi-backend/app/routes/) — HTTP API surface (rooms, tasks, participate/await/respond, memory, engines, a2a).
- [`mycelium-cli/src/mycelium/commands/`](mycelium-cli/src/mycelium/commands/) — every CLI verb (`board`, `memory`, `room`, `engine`, `adapter`, `install`, `network`, …).
- [`mycelium-cli/src/mycelium/integrations/`](mycelium-cli/src/mycelium/integrations/) — one package per runtime family (`claude_code/`, `cursor/`), each holding its registration+install code and an `assets/` bundle.
- [`mycelium-cli/src/mycelium/commands/participate.py`](mycelium-cli/src/mycelium/commands/participate.py) — `await` / `respond`, the entire agent-side participation surface. `await --loop --exec` is the resident runner that keeps a live session woken.

## What to emphasize

- **The board is the surface; a task is a row bound to a thread.** A task is markdown with frontmatter (status, owner, priority); its thread is where coordination on it actually happens. Task = issue, thread = comments, board = Projects is the right mental model. `plan/tasks.md` is **retired** — don't describe consensus as compiling into a plan checklist.
- **Negotiation is optional, not the container.** The aligner mediates a negotiation *inside* a task's thread when one is needed; it is not what a task is born from, and it is not the whole of what Mycelium does. Don't describe Mycelium as fundamentally a negotiation tool — coordination (a shared board, shared memory, visibility into what agents are doing) is the broader point.
- **Rooms are folders, memory is markdown.** `.mycelium/rooms/{name}/{key}.md` with YAML frontmatter. The filesystem is authoritative; the JSONL index is a search index over it, not the source of truth. Direct file writes work; `mycelium reindex` resyncs the index.
- **No database, anywhere.** State is local markdown + a JSONL search index. There is no Postgres, no AgensGraph, no pgvector — that entire stack was removed in the SLIM-native rewrite (PR #418, merged Aug 12 2026).
- **Threads live inside rooms; "episode" and "session" are retired as the top-level noun.** A thread is a tagged, membership-scoped conversation on a room's existing SLIM channel — a tag over the channel, not a separate one. The underlying causal record is still called an episode, but user-facing prose should say "thread."
- **Pi is the only LLM runtime.** litellm was removed entirely (PR #447). The aligner's brain, the synthesizer, and the health probe all shell out to the `pi` binary.
- **Multi-component is the point.** A user touching only the CLI sees half the system. A user touching only the backend sees the other half. Document both.

## Things easy to mis-describe

- **Don't over-claim encryption.** The SLIM node forwards only MLS ciphertext and never sees plaintext, but the **hub itself** is a room member that holds the group key and writes the transcript/memory to disk in plaintext. Say "the node forwards only ciphertext" — never "end-to-end encrypted," which implies a confidentiality boundary the hub does not provide.
- **`plan/` is gone, not just de-emphasized.** The board/task model replaced it outright (a plan item is a task, a board row with frontmatter). Don't describe consensus as producing a `plan/tasks.md` checklist.
- **A2A is bidirectional and doesn't touch the SLIM node.** Outbound: a remote A2A agent joins a room as a member, proxied by a backend seat (never an MLS participant). Inbound: a room can be exposed as an A2A agent via its Agent Card. Both hops are plain HTTPS out-of-band; the hub is the translation boundary either way, not an E2E tunnel.
- **SLIM is the fabric, not an add-on.** Rooms are SLIM group channels (MLS-encrypted multicast); the backend is each room's moderator. Don't describe SLIM as optional infrastructure — it's the coordination substrate.
- **L9 is in-house, not consumed from upstream.** Post-rewrite, Mycelium implements its own minimal L9 envelope semantics rather than depending on an external L9 service. Don't describe L9 as an external dependency.
- **CFN/KXP/CognitiveEngines are gone.** These were taken off open source in July 2026 and Mycelium's rewrite removed the dependency outright rather than waiting on access. Do not describe the current architecture in terms of CFN, a "CognitiveEngine" service, or `cfn_negotiation.py`-style files — none of that exists anymore.
- **Adapter capability is uneven — be honest about it.** `claude_code` is proven; `cursor` is untested. OpenClaw and Hermes are **gone**, not deprecated — they rode the removed SSE/coordination-tick model and their packages were deleted; don't list them as adapters.
- **Agents are resident, never cold-spawned.** A runtime participates by looping `mycelium await --loop --exec` in a live session it already owns. The daemon that cold-spawned `claude -p` per mention was removed (it threw away context every turn). Don't describe Mycelium as spawning or hosting agents.
- **SPIRE identity is gone, not an option.** Removed outright (issue #668, PR #708) after a live audit found it only ever attested the backend to itself on one box. The identity ladder is now two rungs: `psk` (default) and `signerjwt`. Don't list SPIRE as a selectable identity tier.
- **memory set always upserts.** It overwrites existing keys; the row's version increments. Don't describe it as "create-only".
- **Two compose files.** `compose.yml` (released images, end-user path) and `compose-dev.yml` (builds backend from source, for contributors). End users use the install script + `mycelium install`; only contributors run docker compose by hand.
- **Check the release tag, not just main.** Mycelium ships fast (v3.0.0 → v3.0.4 in a week); confirm the latest tag before describing "what a new user gets today."

## Out of scope for the wiki

- Promo video pipeline (`mycelium-promo/`) — internal marketing artifact.
- Generated client internals (`mycelium-client/`) — build output, not source of truth.
- Docs site rendering details (`docs/generate_docs.py`, CSS, etc.).
- Step-by-step end-user install — that's what the README is for.
