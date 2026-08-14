# mycelium

A self-hosted coordination layer for multi-agent systems — persistent **rooms**, markdown **memory** that accumulates across sessions, and an **aligner** that mediates structured negotiation (NEGMAS Stacked Alternating Offers) so multiple agents converge on one answer instead of talking past each other.

This file is the maintainer's hint to a [tiny-teams-with-tokens](https://github.com/juliarvalenti/tiny-teams-with-tokens) ingest agent generating Mycelium's status wiki. It's not the README and not a substitute for reading the actual code — it's a pointer to *where to look first* and *what's easy to misdescribe*.

## Read these first

- [CLAUDE.md](CLAUDE.md) — authoritative design rules + architecture overview. Read this before anything else.
- [README.md](README.md) — user-facing pitch and quick start.
- [docs/index.html](docs/index.html) — presentation deck (more conceptual framing).
- [docs/concepts.html](docs/concepts.html) — the core concepts (rooms, episodes, memory, plan, L9, engines) in depth.
- [docs/demo-script.md](docs/demo-script.md) — narrative walkthrough of a coordination flow.

## Repo layout

Mycelium is a multi-component monorepo. When you describe "the architecture" you should mention all of these by their actual roles:

- [`fastapi-backend/`](fastapi-backend/) — the coordination engine (Python 3.12, FastAPI). No database: state is local markdown files + a JSONL search index. Runs the SLIM messaging node's counterpart services: room moderation, the aligner/synthesizer engines, L9 envelope construction, the persister.
- [`mycelium-cli/`](mycelium-cli/) — the user-facing CLI (typer + Rich) plus the daemon. The primary surface most users touch. Hosts adapter logic for Claude Code (proven), Cursor (untested), OpenClaw and Hermes (both deprecated pending SLIM migration).
- [`mycelium-client/`](mycelium-client/) — auto-generated OpenAPI client. Treat as build output; don't document its internals.
- [`mycelium-frontend/`](mycelium-frontend/) — Next.js + Tailwind UI shipped via `mycelium up --ui`.
- [`mycelium-promo/`](mycelium-promo/) — HyperFrames promo video (HTML→MP4). Out of scope for the wiki.
- [`docs/`](docs/) — presentation site + demo script + agent-facing setup runbook (`docs/agents.md`).

## Where the actual logic lives

If you're documenting how Mycelium works, ground every claim against one of these:

- [`fastapi-backend/app/main.py`](fastapi-backend/app/main.py) — backend entrypoint.
- [`fastapi-backend/app/services/aligner.py`](fastapi-backend/app/services/aligner.py), [`mediator.py`](fastapi-backend/app/services/mediator.py), [`pi_brain.py`](fastapi-backend/app/services/pi_brain.py) — the aligner: a NEGMAS SAO mediator whose brain is a persistent Pi coding-agent session. Read this if you want to understand the actual negotiation loop. NEGMAS owns termination.
- [`fastapi-backend/app/services/synthesizer.py`](fastapi-backend/app/services/synthesizer.py) — the second engine kind: `@`-summoned, compiles a room's memory into a briefing at `context/synthesis`.
- [`fastapi-backend/app/services/l9.py`](fastapi-backend/app/services/l9.py), [`l9_episode.py`](fastapi-backend/app/services/l9_episode.py), [`l9_slim.py`](fastapi-backend/app/services/l9_slim.py) — L9 epistemic envelopes, implemented in-house (not consumed from upstream), plus episode tracking and the MPC/GAR/SCR quality metrics.
- [`fastapi-backend/app/services/room_channels.py`](fastapi-backend/app/services/room_channels.py), [`slim_client.py`](fastapi-backend/app/services/slim_client.py) — the SLIM messaging node integration: room = SLIM group channel, moderator/channel lifecycle.
- [`fastapi-backend/app/services/embedding.py`](fastapi-backend/app/services/embedding.py), [`indexer.py`](fastapi-backend/app/services/indexer.py), [`reindex.py`](fastapi-backend/app/services/reindex.py) — fastembed (`BAAI/bge-small-en-v1.5`, 384-dim, local ONNX) search index over memory. No pgvector, no external embedding service.
- [`fastapi-backend/app/services/plan_compiler.py`](fastapi-backend/app/services/plan_compiler.py), [`plan_sync.py`](fastapi-backend/app/services/plan_sync.py) — compiles consensus into `plan/tasks.md`, then syncs it as a `knowledge` memory.
- [`fastapi-backend/app/routes/`](fastapi-backend/app/routes/) — HTTP API surface (rooms, participate/await/respond, memory, plan, engines).
- [`mycelium-cli/src/mycelium/commands/`](mycelium-cli/src/mycelium/commands/) — every CLI verb (`memory`, `room`, `plan`, `engine`, `adapter`, `install`, `network`, …).
- [`mycelium-cli/src/mycelium/integrations/`](mycelium-cli/src/mycelium/integrations/) — one package per runtime family (`claude_code/`, `cursor/`, `openclaw/`), each holding its dispatch+install code and an `assets/` bundle.
- [`mycelium-cli/.../daemon/`](mycelium-cli/src/mycelium/daemon/) — the optional auto-waker for runtimes that can't wake themselves; cold-spawns `claude -p` on a mention, built on the same membership core (`slim/member.py`) as the CLI.

## What to emphasize

- **Rooms are folders, memory is markdown.** `.mycelium/rooms/{name}/{key}.md` with YAML frontmatter. The filesystem is authoritative; the JSONL index is a search index over it, not the source of truth. Direct file writes work; `mycelium reindex` resyncs the index.
- **No database, anywhere.** State is local markdown + a JSONL search index. There is no Postgres, no AgensGraph, no pgvector — that entire stack was removed in the SLIM-native rewrite (PR #418, merged Aug 12 2026).
- **The aligner mediates everything.** Agents never talk to each other directly — all coordination flows through the aligner (or, for a distinct purpose, the synthesizer). Don't describe Mycelium as a "messaging layer" or "agent chat"; it's a structured-negotiation mediator with NEGMAS owning termination — that's the anti-"AI Theater" property.
- **Episodes live inside rooms.** Rooms are persistent namespaces; an episode is a tagged, membership-scoped negotiation on a room's existing SLIM channel — a tag over the channel, not a separate one. Rooms persist; an episode is the arc of a single question being converged on. **"Session" is retired terminology** — don't use it for this concept.
- **Pi is the only LLM runtime.** litellm was removed entirely (PR #447). The aligner's brain, the synthesizer, the plan compiler, and the health probe all shell out to the `pi` binary.
- **Multi-component is the point.** A user touching only the CLI sees half the system. A user touching only the backend sees the other half. Document both.

## Things easy to mis-describe

- **SLIM is the fabric, not an add-on.** Rooms are SLIM group channels (MLS end-to-end encrypted multicast); the backend is each room's moderator. The node forwards only ciphertext. Don't describe SLIM as optional infrastructure — it's the coordination substrate.
- **L9 is in-house, not consumed from upstream.** Post-rewrite, Mycelium implements its own minimal L9 envelope semantics rather than depending on an external L9 service. Don't describe L9 as an external dependency.
- **CFN/KXP/CognitiveEngines are gone.** These were taken off open source in July 2026 and Mycelium's rewrite removed the dependency outright rather than waiting on access. Do not describe the current architecture in terms of CFN, a "CognitiveEngine" service, or `cfn_negotiation.py`-style files — none of that exists anymore.
- **Adapter capability is uneven — be honest about it.** `claude_code` is proven; `cursor` is untested; `openclaw` and `hermes` are deprecated (they rode the removed SSE/coordination-tick model and have not been migrated to SLIM).
- **memory set always upserts.** It overwrites existing keys; the row's version increments. Don't describe it as "create-only".
- **Two compose files.** `compose.yml` (released images, end-user path) and `compose-dev.yml` (builds backend from source, for contributors). End users use the install script + `mycelium install`; only contributors run docker compose by hand.
- **Merged ≠ released.** PR #418 (the SLIM-native rewrite) merged to main; that is not the same as a cut release. Check the latest GitHub release tag before describing "what a new user gets today."

## Out of scope for the wiki

- Promo video pipeline (`mycelium-promo/`) — internal marketing artifact.
- Generated client internals (`mycelium-client/`) — build output, not source of truth.
- Docs site rendering details (`docs/generate_docs.py`, CSS, etc.).
- Step-by-step end-user install — that's what the README is for.
