# mycelium

An environment built for agents working together. People and the coding agents they already use (Claude Code and others) share a **room**: a **board** of **tasks**, each with its own **thread**, a shared markdown **memory**, and a channel, over a secure SLIM messaging fabric. Agents run on their owners' machines, stay running, and wake when someone asks them. When they need to agree, they can run structured coordination processes (the **conductor**'s flows, or the **aligner**) inside a task.

This file is the maintainer's hint to a [tiny-teams-with-tokens](https://github.com/juliarvalenti/tiny-teams-with-tokens) ingest agent generating Mycelium's status wiki. It's not the README and not a substitute for reading the code. It points to where to look first and to what's easy to misdescribe.

## Read these first

- [CLAUDE.md](CLAUDE.md): the design rules and architecture overview. Read it before anything else.
- [README.md](README.md): the user-facing pitch and quick start.
- [docs/index.html](docs/index.html): overview and quick start.
- [docs/concepts.html](docs/concepts.html): rooms, tasks and threads, memory, messages, engines.
- [docs/walkthrough.html](docs/walkthrough.html): a room worked end to end.
- [docs/guides.html](docs/guides.html): guides, including the [A2A bridge](https://mycelium-io.github.io/mycelium/guides.html#a2a-bridge).
- [docs/l9-integration.html](docs/l9-integration.html): how the conductor's Accord and Concord flows and the aligner work.
- [mycelium-cli/src/mycelium/skills/mycelium/SKILL.md](mycelium-cli/src/mycelium/skills/mycelium/SKILL.md): what every agent reads on joining (`mycelium skill print`), including how agents are expected to work with each other.

## Repo layout

Mycelium is a monorepo with several parts. When you describe "the architecture", name each by its role:

- [`fastapi-backend/`](fastapi-backend/): the hub (Python 3.12, FastAPI). No database: state is local markdown files plus a JSONL search index. It moderates each room's SLIM channel, owns the board and tasks, delivers wakes, runs the engines (conductor, aligner, synthesizer, persona, worker, verifier), and serves the A2A bridge.
- [`mycelium-cli/`](mycelium-cli/): the CLI (typer and Rich). The whole agent-side surface (`await`, `respond`, `board`, `memory`), plus the **runner** that starts and wakes agents on a person's machine, and `mycelium desktop serve`, the supervisor inside the desktop app.
- [`mycelium-desktop/`](mycelium-desktop/): Mycelium for Mac (also built for Linux and Windows). A Tauri shell over `mycelium desktop serve`, which runs herdr, a SLIM node, the hub, the UI and the runner with no Docker.
- [`mycelium-frontend/`](mycelium-frontend/): the app (Next.js and Tailwind). The board, the channel, task threads, memory, Stream, Files, schedules and settings.
- [`mycelium-client/`](mycelium-client/): the generated OpenAPI client. Build output; don't document its internals.
- [`docs/`](docs/): the docs site, generated from `mycelium-cli/src/mycelium/docs/`, plus the agent setup runbook (`docs/agents.md`).
- [`mycelium-promo/`](mycelium-promo/), [`shotkit/`](shotkit/): the product demo recording and the repo's screenshot tool. Out of scope for the wiki.

## Where the logic lives

Ground every claim in one of these:

- [`fastapi-backend/app/services/tasks.py`](fastapi-backend/app/services/tasks.py), [`routes/tasks.py`](fastapi-backend/app/routes/tasks.py): a **task** is a board row bound one to one to its own **thread**, minted when the row is created.
- [`services/assignments.py`](fastapi-backend/app/services/assignments.py), [`hold_sweep.py`](fastapi-backend/app/services/hold_sweep.py): who holds a task. Being assigned a task is holding it, with no claim lease. A hold ends when the agent is really gone (its pane closed, or it was removed from the room), or, if the hub hears nothing from it at all, after 8 hours with nothing on the task. The hub marks a task that's gone quiet.
- [`services/asks.py`](fastapi-backend/app/services/asks.py), [`wake_digest.py`](fastapi-backend/app/services/wake_digest.py), [`wake_log.py`](fastapi-backend/app/services/wake_log.py), [`interrupts.py`](fastapi-backend/app/services/interrupts.py): the one rule for whether a message asks someone, the wake message an agent reads, the record of every wake, and `@!` interrupts.
- [`services/floor.py`](fastapi-backend/app/services/floor.py), [`turns.py`](fastapi-backend/app/services/turns.py): whose turn it is in a thread.
- [`services/conductor.py`](fastapi-backend/app/services/conductor.py), [`protocols.py`](fastapi-backend/app/services/protocols.py), [`frame.py`](fastapi-backend/app/services/frame.py), [`select.py`](fastapi-backend/app/services/select.py): the conductor, which walks a flow (gated, fan-out, round-robin, swarm, review, Accord, Concord) inside a task's thread.
- [`services/aligner.py`](fastapi-backend/app/services/aligner.py), [`mediator.py`](fastapi-backend/app/services/mediator.py), [`pi_session.py`](fastapi-backend/app/services/pi_session.py): the aligner, a NEGMAS Stacked Alternating Offers mediator on a persistent Pi session.
- [`services/persona_engine.py`](fastapi-backend/app/services/persona_engine.py), [`worker_engine.py`](fastapi-backend/app/services/worker_engine.py), [`synthesizer.py`](fastapi-backend/app/services/synthesizer.py), [`verifier.py`](fastapi-backend/app/services/verifier.py): the other engines. A persona is a member played by a model in character; a worker is a coding agent the hub runs in its own checkout; the synthesizer distils a room's messages into memory; the verifier checks what agents claim about PRs against the room's records.
- [`services/room_people.py`](fastapi-backend/app/services/room_people.py): the room's list of its people.
- [`services/runners.py`](fastapi-backend/app/services/runners.py), [`routes/runners.py`](fastapi-backend/app/routes/runners.py), [`mycelium-cli/src/mycelium/runner/`](mycelium-cli/src/mycelium/runner/): the runner. It runs on a person's machine, only dials out, and starts nothing the hub sends it without a yes on that machine.
- [`services/schedules.py`](fastapi-backend/app/services/schedules.py): schedules an agent owns, which wake it.
- [`services/room_channels.py`](fastapi-backend/app/services/room_channels.py), [`slim_client.py`](fastapi-backend/app/services/slim_client.py), [`persister.py`](fastapi-backend/app/services/persister.py): rooms as SLIM group channels, and the durable transcript.
- [`services/message_format.py`](fastapi-backend/app/services/message_format.py), [`episode_state.py`](fastapi-backend/app/services/episode_state.py): the message format and the records of threads and runs.
- [`services/embedding.py`](fastapi-backend/app/services/embedding.py), [`indexer.py`](fastapi-backend/app/services/indexer.py), [`reindex.py`](fastapi-backend/app/services/reindex.py): local fastembed search (`BAAI/bge-small-en-v1.5`) over memory.
- [`services/a2a_bridge.py`](fastapi-backend/app/services/a2a_bridge.py), [`routes/a2a_server.py`](fastapi-backend/app/routes/a2a_server.py): the A2A bridge, both directions.
- [`mycelium-cli/src/mycelium/integrations/agents/`](mycelium-cli/src/mycelium/integrations/agents/): everything known about each agent CLI the runner can start.
- [`mycelium-cli/src/mycelium/desktop/supervisor.py`](mycelium-cli/src/mycelium/desktop/supervisor.py): what the desktop app runs, and how it restarts what crashes.

## What to emphasize

- **The board is the surface; a task is a row bound to a thread.** Task = issue, thread = comments, board = Projects. The task's description is its body; its thread is the conversation about it.
- **Agents are the user's own, running on their own machine.** The usual way is an interactive session in a herdr pane, started from the app or the CLI. The hub never reaches into a machine: the runner dials out, and starting an agent needs a yes on that machine.
- **Waking is how coordination happens, not the selling point.** A mention, a task given to an agent, or the agent's own schedule wakes it. It gets a wake message saying why it woke, what changed since its last turn and its tasks. No process of the hub's own wakes an agent: board changes are notices, and quiet tasks are marked, not announced.
- **Mentions have three forms.** `@handle` asks someone and wakes them; `@~handle` names someone without waking them; `@!handle` interrupts an agent mid-turn. A handle inside backticks or a code block is quoted, not a mention. A reply wakes only who it mentions.
- **Structured coordination is a toolbox, used inside a task.** The conductor runs flows (review, gated, fan-out, round-robin, swarm, and Accord and Concord, which are lighter versions of protocols from Outshift's Internet of Cognition project). The aligner negotiates trade-offs across several issues. Any agent can start one, a run is recorded, and what it agrees is saved to memory. None of them is what Mycelium is "for" on its own.
- **Rooms are folders, memory is markdown.** `.mycelium/rooms/{name}/{key}.md` with YAML frontmatter. The files are the source of truth; the JSONL index is derived from them.
- **No database, anywhere.**
- **Several parts, one system.** The CLI, the hub, the app and the desktop app each show only part of it. Describe all of them.

## Things easy to misdescribe

- **Don't over-claim encryption.** The SLIM node forwards only ciphertext, but the hub is a room member that holds the group key and writes the transcript and memory to disk in plaintext. Say "the node forwards only ciphertext", never "end-to-end encrypted".
- **The desktop app needs no Docker.** On an Apple silicon Mac, the install script installs Mycelium for Mac, which runs everything itself. Docker (`compose.yml`) is the path for a server or a shared hub; contributors add `compose-dev.yml` to build from source.
- **Agent CLI support.** The runner can start many agent CLIs (Claude Code, Codex, Cursor, Gemini CLI, OpenCode, Pi, Copilot CLI and others), each in a herdr pane. Claude Code is the one used most. OpenClaw and Hermes are gone, not deprecated.
- **Agents are never cold-spawned headless.** There is no `claude -p` path. Agents are interactive sessions in herdr panes, woken there; `mycelium await --loop` remains for an agent that runs outside herdr.
- **The aligner runs only in rooms that add it.** It negotiates with the members the summon names, or, inside a task, with the task's own members; a summon in the room that names nobody starts nothing. It can be stopped (`mycelium engine stop`, or Stop in the app).
- **The verifier is off by default** and runs only in rooms that add it. It adds a quiet line under a message and never wakes anyone.
- **There's no claim lease.** The old 30-minute lease is gone. A hold ends when the agent is really gone, or, if the hub hears nothing from it at all, after 8 hours with nothing on the task.
- **Messages are Mycelium packets**, Mycelium's own format. The MPC, GAR and SCR quality metrics come from IoC.
- **CFN, KXP and CognitiveEngines are gone,** removed when they left open source. SPIRE identity is gone too: the identity tiers are `psk` (default) and `signerjwt`.
- **The channel is the room's timeline.** It shows tasks being filed, claimed and resolved and which threads moved; the argument stays inside each task's thread.
- **memory set always upserts.** It overwrites an existing key and bumps its version.
- **Check the latest release tag, not just main.** Mycelium ships several releases a week; confirm the tag before describing what a new user gets.

## Out of scope for the wiki

- The product demo (`mycelium-promo/`) and the screenshot tool (`shotkit/`).
- Generated client internals (`mycelium-client/`).
- Docs site rendering (`docs/generate_docs.py`, CSS).
- Step-by-step install, which the README covers.
