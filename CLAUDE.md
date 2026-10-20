# CLAUDE.md

A short orientation for agents working in this repo. The detail behind each
part lives next to its code: a module's docstring, a folder's README, or the
user docs under `mycelium-cli/src/mycelium/docs/`. Read those when you work
there. This file is what you need before you start, and the rules that stop
the mistakes people have actually made.

## What Mycelium is

Multi-agent coordination and shared memory over a secure messaging layer.
Agents are members of rooms. The unit of work is a **task**: a row on the
room's board and a thread on its channel. A person files a task and never picks
a protocol; agents claim it, split it up and work it in its thread. A mediated
negotiation is one optional step inside a task, not the reason the task exists.

## The repo

```
fastapi-backend/    The hub: FastAPI, Python 3.12. No database; state is
                    markdown files plus a JSONL search index.
mycelium-cli/       The CLI agents use (typer, Rich, a typed OpenAPI client),
                    the desktop supervisor, the runner, and the docs' source.
mycelium-client/    The generated OpenAPI client. Not committed; generate it.
mycelium-frontend/  The app: Next.js, TypeScript, Tailwind.
mycelium-desktop/   The desktop app, a Tauri 2 shell over `mycelium desktop
                    serve`. See its README.
contracts/          JSON files that freeze values two or three copies share,
                    each asserted by tests on every side.
docs/               The published docs site (mostly generated) and runbooks.
shotkit/            Screenshots and short videos of the app and the CLI, for
                    agents. Vendored; see its README and the screenshot skill.
mycelium-promo/     The product demo and the Learn videos. See its README.
```

Talk and workshop slides live in their own repo, `mycelium-io/slides`
(published at mycelium-io.github.io/slides).

## Development

```bash
# Backend (no database; unit tests run against local files + temp dirs)
cd fastapi-backend && uv sync --group dev
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .

# The live-node integration slices need a running SLIM node; they skip without one:
MYCELIUM_SLIM_ENDPOINT=http://127.0.0.1:46357 uv run pytest tests/test_slim_roundtrip.py -q

# Generate the OpenAPI client from the committed openapi.json (once after a
# fresh clone, and whenever the API changes). After changing the API, refresh
# the spec first with ./scripts/snapshot-openapi.sh.
SPEC_FILE=openapi.json ./scripts/gen-mycelium-client.sh

# Regenerate the docs site from mycelium-cli/src/mycelium/docs/. Needs the
# client above. Run it in any PR that touches the docs' sources; CI fails on drift.
cd mycelium-cli && uv run python ../docs/generate_docs.py

# CLI (install globally)
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# CLI quality gate (matches CI); run before pushing
cd mycelium-cli && uv run ruff check . && uv run ruff format --check . \
  && uv run ty check . && uv run pytest tests/ -x -q

# Frontend
cd mycelium-frontend && pnpm install && pnpm dev
pnpm lint && pnpm test   # tsc + eslint, then vitest

# Screenshots (see shotkit/README.md; `shot doctor` checks the machine)
node shotkit/bin/shot.mjs app /room/checkout --mock --offline
node shotkit/bin/shot.mjs term --cols 84 -- mycelium memory --help
```

`pnpm dev:mock` runs the app against a mock hub (`src/mocks/`), which is how
screenshots and most UI work are done.

## How it fits together

**The hub is the one store.** Memories are markdown with YAML frontmatter at
`.mycelium/rooms/{room}/{key}.md`, searched through a local embedding index
(fastembed, `BAAI/bge-small-en-v1.5`). Every other machine is a thin client
that reads and writes over HTTP. A room is a folder with standard subfolders
(`work/`, `decisions/`, `status/`, `failed/`, `context/`, `log/`).

**Rooms are SLIM group channels.** Each room is one MLS-encrypted SLIM channel;
the hub is its moderator (`app/services/room_channels.py`). Every message is a
JSON envelope of one kind (`exchange`, `commit:converged|resolved|rejected`,
`knowledge`; `app/services/message_format.py`). Some stored names carry
`l9`/`ioc`/`SSTP`; they are part of the stored format, so leave them.

**Tasks are the surface.** A board row is a `work/` memory, and the hub binds it
to a thread when it is created (`app/services/tasks.py`). The room's channel is
its timeline: a **ping** says a thread moved, a **notice** says the board did
(`filed`, `claimed`, `resolved`, …), and thread prose stays in the thread.

**Agents take part with two calls.** `mycelium await` long-polls; the hub holds
the agent's place with a presence lease and a cursor, so nothing is missed
between turns. `mycelium respond` posts. An agent is the person's own Claude
Code or Cursor session; herdr wakes one that isn't running
(`mycelium herdr sync`), and the hub builds each wake's digest
(`app/services/wake_digest.py`) and records it (`log/wakes.jsonl`,
`mycelium room wakes`). A wake covers what the agent hasn't read (after its
inbox cursor, not its last post), and a mention wake with nothing unread left
by the time it's due is recorded as `skipped` rather than handed over
(`routes/sessions.py`).

**Engines are members the hub runs.** Each is a kind under `app/services/`:
the **aligner** brokers a negotiation between named members (NEGMAS);
the **conductor** walks a flow (a `Protocol`) through a task's thread, holding
the thread's floor for whoever a step addresses; a **persona** is a member a
model plays in character; a **worker** is a coding agent in its own git
worktree; the **verifier** flags claims it can't find in the room's records;
the **synthesizer** distills messages into `context/synthesis`. An engine is
summoned by `@`-mention, and every model call shells out to `pi`
(provider/model, e.g. `anthropic/claude-sonnet-4-6`); there is no litellm.
`mycelium swarm` files a task with a team on it, in a room that already exists,
never a room of its own. A **schedule** is an agent's own check-in, fired by the
hub (`app/services/schedules.py`); its pre-check is one of a closed set the
hub answers in code, never a script.

**Machines.** `mycelium runner` runs on a person's machine, dials out to the
hub, and starts agents there in herdr when asked (`mycelium/runner/`).
`mycelium machine` reports every agent on the machine. The desktop app runs
the whole stack without Docker through `mycelium desktop serve`
(`mycelium/desktop/supervisor.py`).

**The app** is part of the stack, not an option. It reads all hub state through
SWR hooks in `lib/room-data.ts`, so components hold no polling or fetched
state of their own, and keeps a store only for client state. A room is laid
out as tabs (`components/room-dock.tsx`); a new view is a new kind of tab, not
a new pane. Every key shown in the UI goes through `ui/kbd.tsx`.

## Rules

Each of these stops a mistake that has been made. The why is in the named
module; read it before changing what a rule protects.

**Tasks, threads and wakes**

- **A task is one row and one thread.** The hub mints the binding when the
  memory is created and no write can change it. Create tasks through
  `POST /rooms/{room}/tasks` (or `mycelium board new`), never a raw memory write.
- **No process of the hub's own wakes an agent.** A wake comes from a person,
  another agent, or a schedule or subscription the agent set up itself
  (`app/services/subscriptions.py`). What the hub notices itself (a quiet
  task, a pull request changing, a verifier flag) is a notice, and notices
  and pings wake nobody, except an agent that subscribed to that notice. The verifier never blocks a message either. The notice kinds are a closed set (`message_format.NOTICE_SUBKINDS`,
  frozen as `notice.subkinds` in `contracts/slim-wire.json`).
- **Who may write in a thread is decided in code**, at
  `tasks.thread_write_refusal`: a frozen negotiation's roster and a floor's
  holder. A refused write never reaches the transcript.
- **Who a message asks is one rule, the same for everyone**, in
  `app/services/asks.py`: people, agents and engines, as sender or as the one
  asked. Everything that reacts reads it: the herdr doorbell, `await`, the wake
  digest, a schedule's mention check, an engine's summon and a persona's or
  worker's answer. The doorbell rings from the persister's ingest, so every
  write path rings the same way. An exchange with text asks (signals and
  commits don't); nobody asks themselves; a mention asks (`@!` interrupts); a
  non-reply asks its recipients (a turn); a reply asks only whoever it
  mentions, since its recipient is just whoever the replier last heard from.
  Don't add sender- or kind-specific cases, and don't strip `@` from what
  anyone posts: a member that names someone without asking writes `@~name`,
  and hub-run members are told so in their prompts (`MENTION_ETIQUETTE`). A
  conductor summon written `@~a @~b` binds roles without waking anyone. An
  `@`-mention of an engine is a summon, never a SLIM invite. Cases in
  `contracts/asks.json`, held through every path by
  `tests/test_wake_paths_table.py`.
- **Mentions have three forms**, `@foo`, `@~foo` (silent) and `@!foo`
  (interrupt), and a handle in code is quoted, not a mention. Frozen in
  `contracts/mentions.json`.
- **A held row has no timer.** Being assigned is holding; a hold ends on real
  signals (`app/services/hold_sweep.py`). A row's dependencies are derived,
  never stored (`assignments.waiting_on`).
- **Epics and "waiting on you" are worked out on the hub, on read**
  (`services/board.py`, `services/waiting.py`; `GET /rooms/{room}/board`,
  `/waiting?for=`). An epic is a row with `part-of` children, never a stored
  kind. The app and the CLI draw what these return rather than projecting
  them, frozen under `epic` in `contracts/board-vocabulary.json`. The app's
  board is for people and has no row actions; agents move work from the CLI.
- **`assignee` is who a task is for, the `assignment` field is who holds it.**
  Never write `owner`. Rows compiled from an agreement go through
  `task_compiler.py` and `task_sync.py`, and only a commit that carries
  `assignments` (the aligner's) is compiled into rows; a conductor's agreement
  is saved to memory instead.
- **The CLI skill is a protocol**: take a task, work it in its thread, resolve
  it. Don't turn it into an augmentation layer.
- **A room's people are recorded, never guessed from who posted**
  (`app/services/room_people.py`). A person's room folders are theirs, not the
  room's (`room_folders.py`).

**Negotiation**

- **The aligner negotiates inside the task it was summoned in, with the members
  named** (or the task's own members). A summon in the room that names nobody
  starts nothing.
- **NEGMAS owns termination.** The aligner stops when the parties agree and
  never loops to its step cap. A failed negotiation commits `rejected`.
- **Never fabricate an offer.** An unreadable reply keeps the agent's own last
  position; a number snaps to a real grid point or is refused
  (`offer_snap.py`).
- **The conductor's picks and merges are code** (`select.py`, `frame.py`). A
  model writes in the nodes, never on the edges.

**Store and memory**

- **The spoke is a thin client.** No machine but the hub keeps a `.mycelium/`
  copy, and an unreachable hub is reported, never answered from something
  stale. Git can back the files up but is never how rooms are shared; sharing
  is the live channel (`mycelium hub host` / `mycelium connect`).
- **`memory set` always upserts**, and frontmatter the store doesn't manage is
  kept on every write.
- **Links are derived** (`.link-index.jsonl`, `app/services/links.py`);
  `![[key]]` embeds only a memory marked `expandable: true`, one level deep.
- **Skills and uploads are memories, promoted.** No separate store, and no
  skills rail in the app. An upload's type comes from the service's table,
  never the record, and text is always served as `text/plain`
  (`app/services/uploads.py`).
- **Rooms are always persistent.** A task resolves; a negotiation inside it is
  a recorded episode.

**Machines and identity**

- **"Who am I" has one answer**, from `mycelium/caller.py`. A new way of
  running agents adds a source there, once.
- **Everything known about an agent CLI lives in `integrations/agents/`.**
  Nothing outside it names a CLI (`tests/test_agent_kinds.py`).
- **A runner starts nothing a hub sent it without a yes on its machine**
  (`runner/approvals.py`), except from the desktop app's own hub or a paired
  device (`runner/pairing.py`). The machine is the only place that check can
  live.
- **An agent's own session is herdr's.** Installing herdr's integration for a
  CLI edits that CLI's settings, so it happens only on a yes.
- **The desktop supervisor never stops another hub.** It reports one it finds
  and the person decides.

**Security**

- **The HTTP auth gate is off by default, and that is a hard requirement.**
  Auth must never block trying Mycelium out. A new route is gated by default
  when it's on (`app/services/auth.py`).
- **SLIM identity has two tiers**: `psk` (default, a shared secret) and
  `signerjwt` (each member signs). SPIRE was removed (#668); don't bring it
  back.
- **The SLIM node and `slim-bindings` must be the same minor version** (2.1
  today: `slim-bindings>=2.1,<2.2`, the compose image `slim:2.1.0`, and
  `slimctl` 2.1.x in the desktop app). A mismatch has broken the stack before.
- **The hub sees plaintext.** Custodial sessions (`custody.py`) and the A2A
  bridge (`a2a_bridge.py`) harden the wire and attribution, but are never
  end-to-end from the hub. Say so honestly in code and docs. The A2A hop stays
  plain HTTPS until `slima2a` stops pinning an older `a2a-sdk` (#726).
- **The hub never fetches what a caller names.** Patterns load from a folder
  the operator provides (`app/services/patterns.py`).
- **A person's sign-in is the normal flow, kept in the system keychain.**
  `mycelium login` keeps the session, refresh token included, and commands
  renew it quietly, like `gh` (`session_store.py`). It lives in the system
  keychain, one entry per hub, and in a `0600` file only where there's no
  keychain. Agents are treated as relatively trusted, so there's no prompt
  before use. Two guard rails: an agent's pane never uses the person's sign-in
  or acts as anyone else (`caller.in_agent_pane`), and a credential goes only
  to the hub that issued it (`client.hub_client`).
- **The UI server answers only its own pages** (`src/proxy.ts`,
  `lib/ui-guard.ts`): a name it serves (loopback, an IP, `ui.public_host`),
  its own origin, JSON bodies, and in the desktop app a per-launch token the
  app hands its window in the URL fragment. The token travels app → supervisor
  → UI server on stdin, never in an environment (`ps` shows those to every
  program as the user); media and download URLs carry a short-lived signature
  for one path instead of it; and the UI proxy strips both before the hub.
  The supervisor never adopts a UI it didn't start: a taken port moves the UI
  to another, and the window opens only once the server answering proves it
  holds the token (`supervisor.proves_token`, an HMAC of a fresh nonce).
- **Usage counts carry kinds and outcomes, never a name, handle, room or
  text**, and sending them is off by default (`app/services/analytics.py`).
- **Voice is opt-in**, and the hub never loads the speech model in its own
  process (`voice_worker.py`).

**Checks and CI**

- **Duplicated constants are frozen in `contracts/`** and asserted by every
  copy. Change the contract and every copy together.
- **The checks are derivations, not lists.** A gate recomputes what it checks
  (`openapi.json` against the app, the docs against their markdown, the mocks'
  shapes against the spec). What can't be derived is declared, with its
  reason, next to the code that owns it, and a stale declaration fails too.
- **A config field that reaches no container is a bug, not a feature.** `.env`
  is the only path from `config.toml` into the stack, and
  `tests/test_config_env_coverage.py` gates both directions.
- **The CLI takes its shared flags one way.** `--room`, `--as`, `--json`,
  `--limit` and `--yes` come from `mycelium/cli_options.py`. `cli_audit` checks
  the CLI, and `cli_prose` checks every `mycelium …` command written in the
  docs, skills, prompts, app strings and this file.
- **CLI tests run with `HOME` in a temp folder** (`mycelium-cli/tests/conftest.py`),
  and one that changes the real `~/.mycelium/config.toml` fails by name. Never
  point a test at the real home.
- **CI is fast on purpose** (about 100s on a PR). Timing is reported against
  `.github/ci-budgets.json`, never enforced; raise a budget in the PR that
  makes a job slower. Slow or paid checks go in `nightly.yml`, not the PR path.

**Docs and assets**

- **The docs site is the latest stable release's, not main's.** It publishes
  at a release's tag (`pages.yml`); a docs change on main goes live with the
  next release.
- **Videos under `docs/` are Git LFS objects** (`.gitattributes`). Images
  stay in git, compressed losslessly with oxipng (`npm run optimize-png`),
  and `scripts/check_file_sizes.py` fails a file over 400 KiB outside LFS or
  a PNG oxipng would still shrink by more than 10%. Screenshots are taken and committed by hand (`pnpm screenshots`); no
  workflow opens pull requests on its own.
- **No Ensue references in code.** The API design was inspired by theirs; the
  implementation is independent.

## Running the stack locally

End users install with
`curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` (the
desktop app on an Apple silicon Mac, the CLI elsewhere). For backend work, add
`compose-dev.yml`, which builds the backend from source, and run from the repo
root:

```bash
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --build
```

Settings go through `config.toml`, never `.env` by hand: `mycelium config apply`
rewrites `.env`.

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "<key>"
mycelium config apply
```

Then recreate the backend (`up -d --force-recreate mycelium-backend` with the
same two files). To run the backend outside Docker with reload,
`cd fastapi-backend && uv run uvicorn app.main:app --reload --port 8000`, with a
SLIM node running (`mycelium hub host`) and `pi` on `PATH`.

## Conventions

- Use `uv run` for Python and `uv add` for dependencies; never bare `python` or
  `pip install`. Ruff lints and formats (`select = ["ALL"]`).
- Unit tests run against temp folders. Live-node SLIM tests skip without
  `MYCELIUM_SLIM_ENDPOINT`; live-LLM tests run only with `MYCELIUM_LLM_TESTS=1`.
- Commit messages are imperative and short, with a body when it helps.
- **PR titles and descriptions are plain English.** A title is one ordinary
  sentence saying what changes, in words someone outside the room knows: no
  shorthand from the discussion, no slogans, no fragments joined with commas or
  colons. It becomes the commit on `main` and the changelog line. A description
  opens with what changes for the person using it, then why and how, then what
  was and wasn't tested. The `prose-edit` skill has the rules and examples, and
  a title that fails them holds the PR.
- **A PR an agent opens is signed in its description's footer**, naming the
  agent and room in backticks, never with `@` (a room handle can be a real
  GitHub user, and GitHub would notify them):

  ```markdown
  ---
  <sub>🤖 Opened by the Mycelium agent `mycelium-coder` from the room `mycelium-general`.</sub>
  ```
- **No design or planning documents in git**: no plans, briefs, RFCs, proposals
  or per-issue notes, in `docs/` or beside the code. They go stale within a
  week, and a reader can't tell whether one describes the code or a plan nobody
  carried out. The code, its tests and the PR are the record; an argument for a
  decision goes in the PR or the issue. What does belong: current-state docs
  (`mycelium-cli/src/mycelium/docs/`), READMEs, this file, runbooks, and
  `contracts/`.
