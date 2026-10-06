# CLAUDE.md

## Project

Mycelium: multi-agent coordination + persistent memory over a secure messaging
fabric. Agents coordinate as members of end-to-end-encrypted rooms. The unit of
work is a **task**: a row on the room's board and a thread on its channel. A
human drops a task and never picks a protocol; agents claim it, decompose it, and
coordinate inside it. A mediated negotiation is one optional phase inside a task,
not the reason the task exists.

## Structure

```
.mycelium/              Memory storage (rooms are folders, memories are markdown files)
├── rooms/{name}/       Room directories with standard namespace subdirs
│   └── skills/         Skills = memories in this namespace, promoted (SKILL.md-style)
└── config.toml         Project-local configuration

fastapi-backend/    FastAPI backend, room moderator + persister (Python 3.12).
                    No database: state is local markdown + a JSONL search index.
mycelium-cli/       CLI tool (typer, Rich, typed OpenAPI client)
mycelium-client/    Generated OpenAPI client (openapi-python-client)
mycelium-frontend/  Next.js frontend (TypeScript, Tailwind)
mycelium-desktop/   Mycelium for Mac: a Tauri 2 shell over `mycelium desktop
                    serve`, with the hub, UI, SLIM node (slimctl), herdr, Node,
                    Pi and the search model inside
                    (`scripts/stage-sidecars.sh`). Released as
                    Mycelium-macos-arm64.dmg, signed with a Developer ID and
                    notarized (`scripts/package-mac.sh`), and updated in
                    place from the release's `latest.json`.
docs/               Docs site (generated from mycelium-cli/src/mycelium/docs/),
                    demo script, design notes
shotkit/            The repo's camera: fast screenshots of the running app and of
                    CLI output, for coding agents. A daemon holds a browser open,
                    so a shot is ~150ms rather than ~2s. `node shotkit/bin/shot.mjs`
                    — `app` (a route, with --mock booting dev:mock), `term` (a
                    command under a pty, so Rich keeps its colors, rendered as a
                    Carbon-style card), `code`, plus --responsive/--sheet for
                    breakpoints and open/do/shoot for driving a held page. `video`
                    records the same `--do` flow as a short clip with a drawn
                    cursor, click rings and a camera that pushes in (--auto-zoom),
                    encoded by whatever ffmpeg is on the machine — mp4 with a full
                    one, webm off the build Playwright ships. `--demo`/`--tilt`
                    stage a shot or a take on a tilted window, over the docs'
                    glass droplets with `--backdrop glass` (`docs/glass.js`),
                    with flat captions and `--intro`/`--outro` title cards in the
                    docs' type (`shotkit.config.json`). `--sound` gives a take
                    its clicks and keystrokes as sound, placed on the frames
                    that show them, over an optional bed (`shotkit/src/audio`).
                    See the `screenshot` skill. Captures land in gitignored
                    `.shotkit/`; the committed docs assets are still
                    `pnpm screenshots`, which now runs on this engine.
                    Vendored from github.com/juliarvalenti/shotkit: change it
                    there and bring it here with `scripts/sync-shotkit.sh`
                    (`shotkit/UPSTREAM` is the commit it came from).
mycelium-promo/     The product demo: one shotkit take of the real app
                    (`mycelium-demo.mp4`), a coffee shop's checkout room — you
                    name yourself and add @builder from your machine → hand it a
                    task → a review flow runs in its thread → two agents
                    disagree on a decision and the aligner brokers it → it
                    lands on the board. `demo.json` is the take (shotkit
                    options + its `--do` actions); `node mycelium-promo/record.mjs`
                    boots the frontend in its demo scenario
                    (`MYCELIUM_UI_MOCK_SCENARIO=demo`, `src/mocks/demo.ts`: the
                    room before the story, and a director that plays the
                    agents' side) and records it, staged over the docs' glass,
                    with its sound: the drone in `audio/score.mjs` under the
                    take's clicks and keys, mixed by shotkit (`--quick` for the
                    flat, silent flow alone; `audio/build.mjs` re-mixes).
                    The docs site plays it from `docs/demo/mycelium-demo.mp4`,
                    committed through Git LFS like every video under `docs/`
                    (`.gitattributes`); copy a new take there. The README is
                    the one embed that can't use it: GitHub plays a README
                    video inline only from a `user-attachments/assets/...` URL,
                    minted by dragging the MP4 into a PR comment in the browser
                    (gh CLI has no equivalent), so swap that URL in by hand.
                    `learn/` records the Learn videos the same way, one take
                    per course section (`learn/takes/`, over the frontend's
                    `learn:<take>` scenario, `src/mocks/learn.ts`), into
                    `docs/learn/video/` (LFS too).
mycelium-deck/      The slide template for talks and workshops: plain HTML on a
                    1920x1080 stage (`index.html`, no build), the docs' palette
                    and type, over one WebGL glass lens moving across a growing
                    mycelial network (`lens.js`). Each slide places the lens
                    with `data-lens`; keys, steps, overview, speaker view and
                    timers are `deck.js`. `uv run mycelium-deck/serve.py` serves
                    it on 127.0.0.1 with live terminals: each `data-term` pane a
                    real shell (`term.js`, xterm.js), token-gated, and each → runs
                    the pane's next scripted command. A `data-app` pane frames the
                    real app (`app.js`, found at `?app=`, :8080 or :3717), its
                    screenshot until the app answers, zooming smoothly at the
                    pointer. D draws over any slide (`ink.js`). Scene slides show rather
                    than tell: living diagrams moved on by the clicker
                    (`scenes.js`). See its README.
```

## Development

```bash
# Backend (no database; unit tests run against local files + temp dirs)
cd fastapi-backend && uv sync --group dev
uv run pytest tests/ -x -q
uv run ruff check . && uv run ruff format . && uv run ty check .

# The live-node integration slices need a running SLIM node; they skip without one:
MYCELIUM_SLIM_ENDPOINT=http://127.0.0.1:46357 uv run pytest tests/test_slim_roundtrip.py -q

# Generate the OpenAPI client (NOT committed — a build artifact, #613). From
# the committed openapi.json, no backend needed. Run once after a fresh clone
# and whenever the backend API changes (then `snapshot-openapi.sh` to refresh
# the spec). CI + the wheel/binary builds run this themselves.
SPEC_FILE=openapi.json ./scripts/gen-mycelium-client.sh

# Regenerate the docs site (docs/*.html + docs/search-index.js + docs/llms-full.txt)
# from the markdown under mycelium-cli/src/mycelium/docs/ (concepts/, guides/,
# reference/), the @doc_ref decorators, and the config schema. Needs the OpenAPI client above. Run it in any PR that touches those
# sources — CI fails on drift.
cd mycelium-cli && uv run python ../docs/generate_docs.py

# CLI (install globally)
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# CLI quality gate (matches CI); run before pushing
cd mycelium-cli && uv run ruff check . && uv run ruff format --check . \
  && uv run ty check . && uv run pytest tests/ -x -q

# Frontend
cd mycelium-frontend && pnpm install && pnpm dev

# Screenshots (see shotkit/README.md; `shot doctor` checks the machine)
node shotkit/bin/shot.mjs app /room/checkout --mock --offline
node shotkit/bin/shot.mjs term --cols 84 -- mycelium memory --help
```

## Architecture

Mycelium is **SLIM-native**: one SLIM messaging node, a thin FastAPI backend, and
local files. There is **no database**.

**Rooms are SLIM group channels.** Each room is one durable AGNTCY SLIM group
channel (MLS-encrypted multicast; the node forwards only ciphertext). The always-on
backend is each room's **moderator**; agents (and the human, by proxy) are members.
`app/services/room_channels.py` owns the moderator/channel lifecycle;
`app/services/slim_client.py` wraps the `slim-bindings` client.

**State is files on the hub.** Memories are markdown with YAML frontmatter at
`.mycelium/rooms/{room}/{key}.md`. Search is a **local embedding index** (fastembed
ONNX, `BAAI/bge-small-en-v1.5`, 384-dim, no external service) persisted as JSONL
per room. `memory set` writes the markdown and updates the index. This is the
**hub's internal storage**, not a client surface: every other machine is a thin
client that reads and writes it over HTTP (see **The spoke is a thin client**).
Git can version or back up the files, but it is **not** the sharing path — see
**Sharing is the live channel** below.

**L9 rides SLIM.** Coordination messages carry additive IOC **L9** JSON envelopes:
`exchange` (ticks/replies), `commit:converged|resolved|rejected`, `knowledge`.
Agents never need to speak L9; the backend synthesizes reply envelopes from parsed
agent replies. Modules: `app/services/l9.py` (envelope construction + the subkind
table), `l9_episode.py` (episode tracking + quality metrics MPC/GAR/SCR +
`log/episodes/{short_id}.md` records), `l9_slim.py` (L9-over-SLIM channel),
`l9_models.py` (pydantic bindings vendored from outshift-open/ioc-protocols-models).

**Participation is a CLI primitive.** Any awake caller joins a room and coordinates
with two stateless HTTP calls (`app/routes/participate.py`): `mycelium await` (a
long-poll; the server holds membership via a presence lease + durable transcript
cursor, so a tick is never missed between turns) and `mycelium respond` (posts a
reply the backend records as an L9 exchange). An agent is a **resident** runtime —
the user's own Claude Code / Cursor session — kept woken with `mycelium await
--loop --exec <cmd>`, which loops `await` → reason → `respond`. The loop *is* the
wake; there is no cold-spawn. Cold-start-on-demand, waking a handle when nothing is
resident, is served by herdr plus per-agent identity (`mycelium herdr sync`).
A herdr doorbell rings on a text mention, on a turn put to the handle as an L9
recipient (`herdr_wake_addressed`), and on a row filed for it
(`herdr_wake_assigned`), each carrying a `reason`. What the agent is told is a
digest the hub builds when the wake is delivered (`app/services/wake_digest.py`):
why it woke, what changed since its last turn, its tasks and the board, the
messages that asked for it (cut, with the rest counted), then `await` first and
a reply line that names the task's thread. Delivering a wake raises
`responding`, so the room sees the agent on it whatever host typed the prompt.

**Tasks are the surface.** A board row is a markdown memory (body + frontmatter)
and, through a store-owned episode binding, a thread on the room's channel
(`app/services/tasks.py`, `routes/tasks.py`). The binding is minted at the
memory-upsert chokepoint for every board namespace (`work/`, `decisions/`,
`status/`, `failed/`), so every row is threaded and no two rows share one.
`board send`/`messages` are the room's chat verbs scoped to one row
(`mycelium/chat.py`, one call, not a second implementation); `board coordinate`
puts an engine to work inside a task. The channel is the room's **timeline**: a
**ping** says a thread moved, a **notice** says the board did (`filed`, `claimed`,
`released`, `resolved`), and thread prose is filtered out of it, so the channel
stays legible while agents argue inside a row. The app still shows a thread's
headline there: a run of pings from one thread reads as one line quoting the first
line of its newest loaded message.

**The aligner is the mediator.** Negotiation is driven by a first-party cognition
engine, the **aligner** (`app/services/aligner.py`), summoned by `@`-mention. It
runs a real **NEGMAS Stacked Alternating Offers** mechanism (`mediator.py`); its
cognition runs on a persistent **Pi** session (`pi_session.py`) so it keeps memory
across rounds. It checks the opening positions for a term the agents are using in
different senses (one clarifying round if so, none otherwise), discovers issues from
those positions, brokers each round, `@`-addresses one agent at a time over SLIM,
interprets each reply into an SAO move (`offer_snap.py` snaps near-misses / nearest
numeric grid point), and **NEGMAS owns termination**: it stops the instant the agents agree.

**Episodes.** An episode is a tagged, membership-scoped slice of the room's channel
(a tag over the existing channel, not a separate one). Two things are episodes: a
task's own **thread**, minted with the task and bound to it for life, and a
**coordination phase** inside one, opened by a summon and 1:1 with an L9 episode
record (unique id, recorded at `log/episodes/{id}.md`, `within` the thread it was
summoned in). A phase is held in that thread rather than a thread of its own, so
an agent answers it the way it answers anything there (`respond --task <row>`, or
a bare `respond` in the room).
The container outlives what runs inside it: a coordination phase that converges or
aborts writes neither the task's status nor its assignment.

LLM: **Pi everywhere** (provider/model format, e.g. `anthropic/claude-sonnet-4-6`).
The aligner's LLM session, the task compiler, and the `mycelium doctor` / `/health`
completion probe all shell out to the `pi` binary the backend image ships; there
is no litellm dependency.

## Key design decisions

- **A task is a board row and a thread, one to one.** The row and the conversation
  about it are one object. The episode binding is store-owned: minted at the
  memory-upsert chokepoint for every board namespace, carried across every write,
  write-once, absent from `meta`, so no `memory set` and no board verb can point a
  row at a conversation it was not part of, and a compiler cannot stamp two rows
  with one negotiation's episode. That is why creation has its own route (`POST /rooms/{room}/tasks`) rather
  than a wire form on the memory routes. Thread fields fold onto the row as
  read-only columns and are excluded from the axes a board can pivot on: grouping
  tasks by the state of the negotiation inside them inverts the containment on the
  surface it shows most.
- **The channel is the room's timeline, and carries no prose from a thread on
  the wire.** What a person sees is not that strict (#1147): the app draws a run
  of pings from one thread as one line, who and which task plus the first line of
  the newest of their messages it has loaded, and leaves a ping it can't quote to
  the activity rail; `filed` and `resolved` notices read in the chat, `claimed`
  stays on the rail. Two
  control payloads reach `live` and neither wakes anyone (both are excluded from
  `_addressed_to`): a **ping** carries the episode, sender and message id when a
  thread moves; a **notice** carries the task, who moved it and the thread to open
  when the board moves. `NOTICE_SUBKINDS` is a closed set (`filed`, `claimed`,
  `released`, `resolved`, `blocked`, `unblocked`, `expired`, `floor`) frozen in
  `contracts/slim-l9-wire.json` and asserted on both sides; `floor` is the one
  notice about a thread rather than a task, raised when whose turn it is
  changes. Room-wide events stay
  unfiltered: a task moving is the room's business however deep inside a task it
  happened. Two honest gaps: a ping is live-only in the conversational read
  (`stored_message_from_record` promotes prose and raise-up kinds only), so the app
  merges pings in from the transcript replay, and widening the projection would
  print raw envelopes at `mycelium room messages`; and a notice carries no
  `content`, so `mycelium room watch` drops it and the terminal draws no timeline
  line.
- **A thread's floor is held by code, never chosen by a writer.** Two things
  narrow who may write into a thread, and both are enforced at the one gate
  `/messages` and `/reply` share (`tasks.thread_write_refusal`): a frozen
  negotiation admits only the roster it froze on (403), and a **floor**
  (`app/services/floor.py`, held per episode on the managed channel via
  `manager.hold_floor`/`release_floor`) admits only the handles its holder gave
  it to (409, naming whose turn it is). A refused write never reaches the
  transcript, so it wakes nobody and `await` needs no change. The room itself
  (`live`) never holds a floor. A floor that moves raises a `floor` notice
  and the members read (`/sessions/members`) lists every floor held, so the
  rail marks whose turn it is (`lib/floors.ts`) whether or not that member
  is present. `app/services/turns.py` is the one-agent turn the aligner
  brokers with, lifted out so a protocol step asks the same way.
- **A persona is a member played by a model, in character.** Engine kind
  `persona` (`app/services/persona_engine.py`): the `agents/<handle>/notes`
  memory is its system prompt, its Pi session is kept per (room, handle) so it
  remembers, and it answers on two seams — a text mention (the summon hook)
  and an **addressed turn** (`persister.on_addressed`, fired once per L9
  recipient of an exchange that mentioned nobody in its text, which is how the
  aligner and the conductor address one member). The persona and the worker
  answer on the addressed seam (and it rings a herdr member's doorbell); the
  other engines act on mentions alone. A stance marker
  in its answer is lifted onto the payload like `/reply` does, and every `@` in
  what it says is neutralized, so personas cannot summon anything or each
  other, and it never posts into a thread whose floor was not given to it.
  Not a roster member: the aligner negotiates with one only when the
  summon names it.
- **A floor notice and the members' floors name the task, not the thread.**
  `tasks.row_of_episode` is the reverse lookup from a thread to the row that
  carries it; the `floor` notice and `/sessions/members` `floors` carry that
  row's `key` and `title`, and the GUI shows the title, falling back to the
  thread id only for a thread no row carries.
- **The conductor walks a flow inside a task's thread, in code.** A fourth
  engine kind (`app/services/conductor.py`) with no model of its own.
  Summoned as `board coordinate <row> conductor "gated @a @b: …"`, it walks
  a `protocols.Protocol` (seven built in: `gated`, `fan-out`, `round-robin`,
  `swarm`, `review`, and IoC L9's `concord` and `accord`; a step's prompt can
  name the row as `{task}`;
  a room's `protocols/<name>` memory overrides or adds one; `show <name>`
  prints one as YAML to save there) **in the thread it was summoned in**,
  holding that thread's floor for whoever each step addresses, asking through
  `turns.addressed_turn` as a `message` the thread shows, and following the
  edge the reply's stance takes (`markers.stance_of`). A task is one row and
  one thread, so a run never opens a thread of its own; a summon from the
  room is refused and told to use a task (`list`/`show` answer anywhere).
  **The run's record is a nested episode carrying its flow:** it reads the
  task thread's slice (`episode`), names it as `within`, and carries
  `EpisodeState.flow` (the graph plus who was bound to each role) and
  `EpisodeState.trace` (one entry per step taken), written onto
  `log/episodes/{id}.md` at the opening and after every step;
  `episode_records` parses them back (`flow`, `trace`, `within`,
  `current_step` on the episode read), tolerating an empty fence. The app
  draws the latest run's graph at the top of the task's thread
  (`flow-panel.tsx`, `flow-graph.tsx`, laid out by `lib/flow-graph.ts`),
  with the current step, the edges taken and the member holding the floor,
  and reaches earlier runs from their records. The floor is taken
  synchronously in `handle_summon`; the members named beside the conductor
  are role bindings, so a persona there does not answer the summon and a
  resident agent that replies early is refused. An `@`-mention of any engine
  is a summon, never a SLIM invite. A run opens no negotiation. A model in the
  nodes, code on the edges, and on the picks: a `kind: select` step asks
  nobody, and `app/services/select.py` picks among the options members
  suggested (`collect: options`) by the 0-100 ratings they gave in the marker
  (`[[mycelium: A=82 B=41]]`, `collect: scores`), leximin with a missing
  rating counted as 0 for ranking and never recorded as 0; the least happy
  rater is `to: bottleneck` for a fix, bounded by `max_repairs`, and the
  step branches `feasible` / `infeasible` / `stuck`. A step's `require`
  (stance or scores) re-asks a reply that lacks it once; an unmarked stance
  after that counts as reject. **A run ending on a pick's `feasible` edge is
  the one conductor path that commits `converged`**, with the decision as
  `assignments` and the task as `within`, so `task_sync` compiles rows filed
  `part-of` that task; every other flow ends `resolved` / `rejected` and
  compiles nothing. Every post it makes carries a structured line in
  its payload under `conductor` (`open`, `turn`, `edge`, `select`, `close`) beside the
  prose its members read; the history read copies it into the message's
  `metadata`, and the app (`task/conductor-row.tsx`) and `swarm`'s view draw
  the line, keeping the prompt behind a toggle. A run ending `resolved` is a
  success (the channel reads it "Done"), only `rejected` a failure.
- **A worker is a teammate the hub runs, a coding agent in its own checkout.**
  Engine kind `worker` (`app/services/worker_engine.py`), on the persona's
  machinery (notes as character, a Pi session per (room, handle)), but the one
  Pi session that keeps Pi's tools: each turn runs in its own git worktree
  (`app/services/workspace.py`) of the room's repository at
  `<data dir>/workspaces/<room>/repo`, on branch `swarm/<handle>`, committing
  as itself. The repository is a clone of the swarm's `repo` (cloned before
  anything else is set up, so an unreachable one starts nothing; a room keeps
  the repository it started on) or an empty one. Its commands run in the
  backend container as its user, so running on the hub is not what limits a
  worker; `WORKER_TOOLS=false` makes it write-only, and so does
  `ALIGNER_PI_OPENSHELL`, whose sandbox cannot see the checkout. A turn is
  bounded (`WORKER_PI_TIMEOUT_S`) and nothing runs between turns. It acts on
  four things: a mention, an addressed turn, a `filed` notice naming it (it
  claims the row and works it in the row's thread), and a `resolved` notice
  that left a parent with nothing open (`assignments.parent_completed`; the
  author of the children writes the combined result into the parent and
  resolves it, once per parent, from each part's final version
  (`_parts_of`), not from memory). What it does to the board it writes as
  action lines (`[[new: title -> @member]]`, `[[done]]`), lifted out of the
  prose and carried out against the row its thread belongs to through the
  same services every writer uses. A `done` on a settled row changes nothing,
  and a part's holder cannot resolve it before a teammate has spoken in its
  thread. Unlike a persona it keeps `@` for teammates (asking for review is
  the collaboration) and neutralizes every other mention, so it can never
  summon an engine. A reply on someone else's row that neither resolves it
  nor names a teammate goes back to the row's holder (`_hand_back`), so a
  review cannot go quiet because a model forgot a mention. Turns are serial
  per worker and capped per room (`WORKER_MAX_TURNS_PER_ROOM`). Board events
  reach it through the manager's `on_notice` hook, fired after every notice;
  a notice still wakes no `await`.
- **`mycelium swarm` is the one-argument path to a working team, in a room
  you already work in.** A swarm is a task with a team on it, never a room of
  its own: it runs in `--room` or the shell's active room, refuses a room that
  does not exist rather than making one, and its work stays in the task's
  thread and its parts' threads, where the rest of the room can see and join
  it. It registers a conductor, files the task, and summons the
  conductor's `swarm` flow (each member checks in, then the lead splits the
  task into a child row per member) in the task's thread. The members are the
  user's own agent CLI in a new herdr workspace by default: `--kind`, else
  `swarm.agent` in config, else asked once and saved there, never guessed
  from what is installed (copy never names a harness). Each pane's env
  set to its handle and room (`MYCELIUM_AGENT_HANDLE`, `MYCELIUM_ROOM_ID`,
  plus `MYCELIUM_API_URL` when set) and handed a brief as its
  `agents/<handle>/notes` memory, read with `mycelium memory get` (a file
  outside the checkout would stop Claude Code at a permission prompt). Claude
  is started with `--allowedTools Bash(mycelium:*)` for that session only,
  never by editing the user's settings. `--server` makes the members workers
  instead, set up through the hub's `POST /rooms/{room}/swarms` (the one setup path the
  app's Swarm dialog uses too; the CLI passes `kickoff: false` and posts the
  kickoff once its view is listening), with `--repo` for the hub to clone. The invoking terminal is the live view (thread prose and notices
  across the task and its children, which `room watch` deliberately hides;
  agent text is escaped, long messages cut to a few lines, and the finished
  result printed in full) and, locally when no runner is running, runs the
  herdr sync pass on a thread (`commands/herdr.sync_pass`) with `wait=False`,
  so woken members work at once rather than one turn after another.
- **The app starts agents on a machine through its runner, on the runner's
  host.** `mycelium runner` (`mycelium/runner/`) runs on the user's machine
  and only dials out: it says hello with its scan (agent CLIs found on `PATH`,
  launchable when its host says it can start their kind), its
  roots and its agents, heartbeats, and long-polls `GET
  /api/runners/{id}/jobs/next` for `launch`, `stop`, `scan`, `swarm` and `restart` jobs
  (`app/services/runners.py`, in memory like presence; `routes/runners.py`).
  The pattern is LangGraph Studio's (a hosted UI driving a local server),
  turned around so the hub never reaches into the machine. A job names a
  framework id from the runner's scan and a folder inside its roots, never a
  command. The hub writes the agent (manifest with `runner` and `framework`,
  instructions as its notes) before queuing the launch, so a failed start
  leaves an agent that can be started again. Where it runs is an `AgentHost`
  (`runner/hosts.py`, picked by `runner.host`): the runner decides what to
  start and asks first, the host opens somewhere for it, starts it, reports
  its status, delivers its wakes and stops it. Every agent a runner starts is
  an interactive session, prompted to read its notes; there is no headless or
  one-shot mode, and a machine whose host isn't up starts nothing. herdr is
  the default host: a runner-started agent's pane mapping is not `managed`,
  so a closed pane stops it without deleting it from the room. A host that
  can't pass an agent an environment (`joins`) gets a join code in the
  agent's introduction instead; see the next point. A swarm with `runner` set has the hub
  register the conductor, write the members and file the task, and the runner
  runs `swarm.start_local`/`brief_local`/`kick_off` exactly as the CLI does.
  A swarm starts in herdr whatever the runner's host. **The runner is what
  keeps a machine's agents synced**: its host's sync pass, for herdr over
  every workspace bound to a room on the machine (the ones it opened and any
  a person bound). Binding a workspace (`mycelium herdr sync --workspace w
  --room r`) is the choice to sync it; that command runs one pass and says
  whether the runner is up, and there is no terminal loop.
- **`mycelium machine` is every herdr agent on this machine, and what to do
  about it.** `mycelium/machine.py` reads herdr's registry and herdr itself
  into one report: per agent a state (`working|idle|blocked`, `stopped` = pane
  open with no agent, `gone` = pane closed), kind, folder and whether herdr
  restores it; whether the runner is running; and problems, each with the
  command that fixes it. The CLI prints it (`restart`, `rename`, `unbind`,
  `integrations`); the runner sends it with every heartbeat
  (`RunnerHello.machine`) for the Machines page, whose one action is Restart
  (`POST /api/runners/{id}/restart`, a `restart` job that asks on the machine
  like a launch). **An agent's own session is herdr's, never Mycelium's**:
  with herdr's integration for its CLI installed, herdr reopens each agent in
  its own conversation after its server restarts. Installing one edits that
  CLI's settings, so it happens only on a yes (`mycelium machine integrations
  --install`; the Mac app asks once, in the first-run wizard or as a dialog
  on first launch, and the answer is kept in `~/.mycelium/herdr/restore.json`).
  Restart is the same for every CLI: the same kind in its folder and pane, as
  itself, told to catch up from the room, with its workspace bound again so
  the runner syncs it. Mycelium needs herdr `MIN_VERSION` (0.9.3,
  `integrations/herdr/bridge.py`) or newer; the Mac app ships it. A herdr
  server restart leaves every pane a bare shell, so sync retires a managed
  member only when its pane is closed, and retires nothing when the pane list
  can't be read.
- **"Who am I" has one answer, from ordered sources, and a folder can join a
  room.** Every command needs the hub, the handle, the room and a credential;
  `mycelium/caller.py` answers all four from the same order: a flag, the
  environment, the herdr pane (`HERDR_PANE_ID` through herdr's registry, which
  is how an agent herdr restored without its environment is still itself),
  this folder's membership, this machine's setup, a default. A folder
  config keeps only the `identity` keys it set itself.
  `resolve_actor`, `_resolve_room`, `client.auth_headers` and
  `MyceliumConfig.load` call into it, so a new way of running agents adds a
  source there, once; `mycelium whoami --sources` shows each answer and where
  it came from. A membership is what `mycelium join <code>` saved in
  `.mycelium/member.json` (0600, git-ignored beside it), found by walking up
  from the cwd; it is how an agent on a machine that says nothing about it
  (no environment, no login) acts as its member. Codes come from `POST
  /api/rooms/{room}/joins`, which needs the right to act as the handle
  (owner/allow_from), and are redeemed at `POST /api/joins/redeem`, the one
  `/api` path open when the gate is on (`app/services/joins.py`: single-use,
  ten minutes, in memory, stored hashed). A gated hub signs the member its own
  token (`app/services/member_tokens.py`: ES256, key in the data dir, 30
  days) and trusts its own issuer beside the configured ones with no key
  fetch; with auth off the membership carries no token. One member per folder.
- **A runner starts nothing a hub sent it without a yes on its machine.**
  Anyone who can reach a hub can queue a job for any runner on it, and the
  hub can't prove who asked, so the machine is the only place the check can
  live. A `launch` or `swarm` job waits (reported `waiting`) until it is
  answered in `mycelium/runner/approvals.py`: a question file under the
  runner's folder and a `.yes`/`.no` beside it, written by the Mac app's
  dialog (the supervisor emits a `request` event) or by `mycelium runner
  approve|decline`. Nothing over the network can write that file; a job id
  that isn't the hub's hex never becomes a file name. `scan` and `stop` don't
  ask. The one exception is a hub the runner may trust: the Mac app's own,
  and only when its supervisor started it (it listens on 127.0.0.1 alone; a
  hub already on the port, like a Docker one publishing to the network, does
  not count), or `--trust-hub` said by the person. A machine with no one
  there to approve can use a **pairing** instead (`mycelium/runner/pairing.py`): `mycelium runner
  pair` there prints a code, the app sends its device key (WebCrypto P-256,
  non-extractable, in IndexedDB: `lib/device-key.ts`) with an HMAC keyed by
  the code, and a launch, swarm or restart that key signs (over the job's
  fields, a time and a nonce) starts without asking, within the folders,
  agent CLIs, teams and expiry written on the machine. The hub routes the
  pair request by the code's public first four characters and only carries
  signatures; a refused one asks as an unsigned job does, and the job's
  `pairing` says why. The UI lists only your own
  machines (`lib/my-machines.ts`: the one the app names with `?machine=`, ones
  added by the code the runner prints, or ones owned by your principal), and
  with a verified token the hub shows and serves a caller only runners it
  owns. That listing is tidiness; the question on the machine is the security.
- **The Mac app is a window over a supervisor the CLI owns, and needs no
  Docker.** `mycelium desktop serve` (`mycelium/desktop/supervisor.py`) runs
  herdr's server, a native SLIM node (`slimctl slim start`, pinned 2.1.x to
  match `slim-bindings`), the hub, the UI and the runner, each once the one
  before answers; `--mode client` runs only herdr and the runner against a
  hub elsewhere. It restarts what crashes with backoff, says why from the
  program's own last output, treats a port something else already answers as
  running (so it sits beside a Docker stack), except the hub's: a hub it
  didn't start on its port is never used without saying so. Before starting
  anything it lists every hub on the machine (`mycelium/hubs.py`: Docker
  containers, hub processes, the port; each with its version and store, told
  apart by the `.store-id` `/health` reports), warns when there is more than
  one, and uses the hub on its port while reporting it (`existing_hub` in its
  status: owner, version, data folder), which the app shows with the command
  to stop it. It never stops another hub itself: that one may be someone's on
  purpose, so the person decides. It leaves herdr running on stop
  (agents live in it), and writes everything to
  `~/.mycelium/logs/desktop.log`. Programs are found in the app bundle, then
  a checkout, then PATH. `mycelium-desktop/` (Tauri 2) adds first run, the
  menu bar, `mycelium://join|terminal|settings` links and an agents terminal that can
  start only herdr; the hub's pages get no IPC and reach the app only by
  those links. The web UI knows it is inside the app by the
  `MyceliumDesktop/` user agent. `doctor --mode desktop`
  (`mycelium/desktop/checks.py`) checks what the app runs, and the app shows
  it as its health check.
- **The aligner mediates, inside a task.** Agents never talk to each other directly;
  all coordination flows through the aligner. It's a first-party engine registered
  as a room citizen (`mycelium engine create aligner --kind aligner`) and summoned
  (`board coordinate <row> aligner "…"`, or `engine invoke` when the question
  belongs to no row), not auto-run on a join window. Like the conductor, it
  negotiates **in the thread it was summoned in** (`AlignerEngine.mediate`'s
  `episode`): its questions, the replies and the verdict land in the task's thread
  (or the room), whose roster it freezes for the run. Its record is a nested episode
  with `within` set to that thread, and its commit carries the row as `within`, so
  an agreement reached in a task compiles rows `part-of` it.
- **The aligner's LLM session is Pi (only).** The SAO mediator runs on a persistent
  Pi session; there is no litellm fallback. Pi ships in the backend image;
  OpenShell sandboxing (`ALIGNER_PI_OPENSHELL`) is an optional command-prefix seam,
  off by default. See `pi_session.py`.
- **NEGMAS owns termination.** The mechanism stops at unanimity; the mediator never
  loops to the step cap (the anti-theater property). A failed negotiation commits as
  `rejected`.
- **Faithful interpretation, never fabricated.** An unreadable proposer holds its
  own last line, never the standing offer (no phantom convergence); numeric offers
  snap to the nearest real grid point or refuse, never to a fabricated value
  (`offer_snap.py`).
- **Rooms are folders on the hub.** `.mycelium/rooms/{name}/` with standard subdirs:
  `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`.
  `work/` holds one row per task. The room's display title is the room's own
  (the `.room.json` sidecar, `PATCH /rooms/{name}`), not a memory: it names the
  room rather than describing work in it. Direct file writes still
  work — that's a hub-operator escape hatch (run `mycelium memory reindex` after),
  not the client model.
- **The spoke is a thin client.** Any non-hub machine keeps **no local `.mycelium/`
  replica**; there is one store, the hub's. `memory get`/`ls`/`search`, the
  category views, the roster reads (`agent ls`/`show`/`invoke`/`rm`,
  `engine ls`/`invoke`) and the global user store (`user create`/`ls`/`show`,
  `iam`, `whoami` over `/api/users`) all resolve against the backend, so a spoke
  with no files still reads the room — and an unreachable hub is reported plainly rather
  than silently answered from something stale (`commands/memory.py:_hub_session`).
  The backend is the only writer of `users/`, so the CLI half of
  `contracts/user-store.json` covers just the slug rules and the wire fields.
  `mycelium iam` is the one split command: the identity it sets is this machine's
  config, the user record is the hub's, and the local half lands either way.
- **Rooms are always persistent.** Rooms are persistent namespaces for memory and
  coordination; a task is work that resolves, and a negotiation inside a task is an
  ephemeral, recorded episode.
- **The CLI skill is a protocol.** Take a task off the board → work it in its own
  thread → resolve it, with a mediated negotiation available inside a task when
  agents genuinely disagree. This is the value add; don't change it to an
  augmentation layer.
- **memory set always upserts.** `memory set` overwrites existing keys automatically
  (version increments). Frontmatter the store doesn't manage is user data: it
  survives a rewrite rather than being dropped, `MemoryCreate.meta` (CLI:
  `--meta k=v`, `--expandable`) writes it, and `MemoryRead.meta` reads it back —
  every frontmatter key outside `MANAGED_META` (`services/filesystem.py`).
- **Memories interlink; the link index is derived.** `myc://key` (canonical) and
  `[[key]]` (shorthand) are the same edge, plus `![[key]]` transclusions and typed
  frontmatter relations (`supersedes`, `depends-on`, `part-of`, `relates-to`).
  `app/services/links.py` parses them into `.link-index.jsonl` beside the embedding
  index — same contract: derived from the markdown, rebuildable, upserted on every
  write. It's persisted rather than derived-on-read because backlinks are the whole
  point (the blast radius of changing a leaf) and deriving them means reparsing every
  file on every memory open. Links are room-local; `myc://rooms/{other}/{key}` parses
  but resolves to a `cross_room` error.
- **Transclusion is opt-in on the target, and depth 1.** `![[key]]` embeds a memory
  only when its frontmatter says `expandable: true`; anything else is an integrity
  error, never a silent inclusion. Expanded text is inserted verbatim, so a marker
  inside it stays literal — cycles are structurally impossible and expansion size is
  bounded, with no depth cap to tune. A marker that can't expand is left exactly as
  written and reported, so a refused embed never reads as an empty definition.
- **Skills are memories, promoted.** A skill is just a memory under a room's
  `skills/` namespace (SKILL.md-style markdown + frontmatter, with the one-line
  `description` in frontmatter). The same way `agents/<handle>` memories are
  promoted into a members panel and `decisions/` into a category view, `skills/` is
  promoted into a thin skills surface — `mycelium skill …` and
  `/api/rooms/{room}/skills` (`app/services/skills.py`, `app/routes/skills.py`).
  Room-scoped, like memory; no separate store, and a skill is reachable as a memory
  too (writes go through the memory upsert path, so they're indexed/linked/broadcast
  like any memory). **In the GUI there is deliberately no dedicated skills rail** —
  a skill shows up in the Memory list like any `skills/…` memory, with a small
  "skill" tag in the detail view (`memory-detail.tsx`); the frontend's only
  skill-specific call is the composer's `/` autocomplete. The surface keeps prose;
  it does not execute skills — that's the participation/engine layer's concern.
- **Patterns are scenarios the hub loads, from a pack the operator provides.** A
  scenario (`app/services/patterns.py`, `routes/patterns.py`) is a room ready to
  run: a cast, some context, a task and the flow that sets them working, loaded
  by `POST /api/patterns/{name}/load` as the writes any client can already make
  (room, engines, memories, task), through the routes that own them. It loads
  **paused**; `run` posts the summon. The room name is claimed atomically (a
  directory made exclusively, since creating a room that exists is otherwise a
  quiet no-op that would put two callers in one room), and a failed step removes
  the room. A pack is data (`yaml.safe_load` into strict models, never run), and
  **the hub never fetches what a caller names**: `patterns.dir` is a folder the
  operator provides (`PATTERNS_DIR` in `.env`; compose mounts it read-only and
  points the backend at the mount), and a caller names a pattern in it, never a
  location. A trusted caller may send a scenario in the request
  (`patterns.allow_inline`, what `mycelium pattern use --from` does; the CLI
  clones a URL itself, with the caller's git credentials), and
  `patterns.personas_only` refuses any member that is not a persona or a person,
  so a public hub never starts a worker (Pi with tools). A scenario can also say
  how a run reads to someone watching it (`before`, `after.track`, and a `guide`
  of steps pointed at parts of the screen); loading writes none of that to the
  room. A loaded room's sidecar records `pattern` and `pattern_task`, and after
  every conductor step (`ConductorEngine.on_step`) a room whose scenario has
  `after` gets a one-shot Pi restatement of where the run stands, written as
  `context/standing` (`app/services/standing.py`, one call per room at a time,
  later steps folded in). The app's **/patterns** explorer
  (`components/patterns/pattern-explorer.tsx`) is a plain client of these: the
  pack, a pattern's newest room, before and now, the flow, the thread, and the
  person's turn as Approve/Block. The flow is parsed with the hub's own `Protocol` model before anything
  is written, because the hub does not check a `protocols/<name>` memory on save:
  a bad one is silently left out of the room's flows.
- **A room's messages are searched by any field, with counts to narrow by.**
  `GET /rooms/{room}/messages/search` reads the whole history (not a page)
  with one grammar: words, `"phrases"`, `-word`, `field:value` (`from:` `to:`
  `mentions:` `task:` `in:` `stance:` `has:` `is:` `type:` `kind:` `step:`
  `day:` `thread:`), `after:`/`before:`/`on:` and `sort:`. The grammar and the
  engine are document-agnostic (`app/services/facet_query.py`); messages
  declare their fields in `message_search.py`, and memories can declare
  theirs on the same engine. Facet counts are disjunctive (a field's counts
  ignore its own clauses). `contracts/message-search.json` freezes the
  fields and closed values; the hub, the CLI's copy (`search_grammar.py`,
  behind `mycelium room search`) and the frontend's (`lib/message-search.ts`)
  assert against it, and `cli_prose` checks every search query written in
  the docs and prompts against it. The channel's ⌘F speaks the same grammar
  with the composer's hints (`composer-hints.tsx`), and its History panel
  lists every hit with the counts as switches. The wake digest names the
  command in one line.
- **Three composer sigils, one mechanism.** The chat composer
  (`room-chat-box.tsx`) autocompletes `@` → agents, `[[` → room memories (inserts
  `[[key]]`, which resolves to `myc://` and is clickable in chat), and `/` → the
  room's skills (inserts `/name`). One cursor-prefix detector feeds one candidate
  popover; `[[` is matched before `/` and `@` since a memory key can contain
  slashes. Skills insert a reference token — the resident agent/engine interprets
  it; the composer never runs the skill. **Commands** are the one `/` that runs:
  `/task`, `/swarm`, `/memory`, `/agent` and `/engine`, only as a message's
  first word, listed ahead of the skills. Each declares its arguments in
  `lib/composer-commands.ts` (one parser for all of them), so the composer
  draws the signature over the box with the argument under the cursor lit,
  offers that argument's values (a machine's harnesses and folders, engine
  kinds, memory folders and keys) and Tab completes them; a missing argument
  is named before anything runs. `/task` files a task with the board capture's
  grammar through the same `lib/board/file-capture.ts` the board's File button
  uses (the tasks route, then ordinary fields); `/swarm` opens the swarm
  dialog, since a swarm spends model turns; `/agent` queues the same runner
  launch the Add member dialog does; `/memory <key> <text>` writes inline,
  replacing a taken key only at the version it saw, and with no text opens
  the new-memory dialog (`new-memory-dialog.tsx`, also behind the memory
  pane's Add and the composer's +) where the key points. A message that
  starts by mentioning a conductor gets the same help without being a
  command: its flow completes from `GET /rooms/{room}/protocols` (the room's
  own flows, then the built-ins it leaves alone) and the flow's roles fill
  the member slots in the order they bind (`parseSummon`); it is still sent
  as the message typed. A skill that shares a command's name is still
  reachable by picking it from the list.
- **One keycap, sized by where it sits.** Every surface that names a key draws it
  through `ui/kbd.tsx` — `Kbd` for a literal, `KbdChord` for a chord the keymap
  owns (platform-spelled, and silent when nothing binds the action). Three sizes,
  picked by context rather than emphasis: `xs` is the one that fits the 24px
  status rail, `sm` for palettes and hint rows, `md` for the `?` cheatsheet. The
  rail is where this matters most: it is the only strip every screen shows, so a
  cell a key already reaches names that key (in its tooltip, via `action=`) and
  the way in teaches the way past. `key-badge.tsx` stays separate — that is the
  ⌥-reveal badge drawn *on* a target, not a cap set in copy.
- **The synthesizer distills messages into memory (#808).** Its input is the
  room's transcript — the ephemeral half, where a decision is argued and settled
  and nothing indexes it for meaning — and its output is a `knowledge` memory at
  `context/synthesis`. Summarizing memory back into memory is a different
  feature, kept behind `SYNTHESIZER_SOURCE=memory` rather than as the default.
  Three properties carry the direction: it reads **by message type**
  (`schemas.PROSE_MESSAGE_TYPES` → `persister.prose_messages`) so a serialized
  L9 envelope never reaches the prompt; it is **incremental**, with the cursor
  living in the written memory's own frontmatter so position and text land in
  one write (`--all` in the summon text re-reads everything); and it **excludes
  its own posts** by sender, since it speaks its briefing into the room it reads.
- **Consensus compiles into rows, but rows do not need consensus.** Work is
  created board-first (`board new`, `--parent` landing a real `part-of` relation,
  refused rather than dangling when the parent is absent). A negotiation is one way
  a row arrives, not the way. On convergence the aligner hands the agreed
  `{issue: value}` map to `task_compiler.py`, an LLM stage that turns it into
  tasks, and `task_sync.py` writes each one as a `work/` memory through the
  canonical upsert. It runs off `on_converged`, which fires once the commit is
  recorded, in the background: the rows land just after the consensus is
  announced, and each raises its own `filed` notice, which is what wakes the
  agent it is for. A converged commit that names a task in `within` files its
  rows `part-of` it (and loose if that row is gone). The model still writes `- [ ] text @handle` lines because
  that is the shape it is good at; parsing them into rows is the compiler's job
  and the line format never leaves it. A task carries `assignee`, never `owner`
  — `assignee` is who the task is *for*, the `assignment` field is who is
  *holding* it, and a stage that cannot take one must not write one. Fail-soft: a compiler
  outage falls back to the raw `issue=value` agreement. The compiler is
  deliberately a distinct consumer stage across an explicit seam, not part of
  the negotiation engine. It runs a one-shot `pi` turn
  (a throwaway session, off the event loop via `asyncio.to_thread`), like every
  other mycelium cognition call.
- **A row waits on its dependencies, derived and never stored.** A `work/`
  row whose `depends-on` names a live board row that is not settled reads as
  waiting on it: `assignments.waiting_on` on the hub (in every assignment read
  and in the lease watcher's signature, so `await --lease` wakes when a row
  becomes claimable), and a `waiting_on` fold in both board projections, frozen
  in `contracts/board-vocabulary.json` under `task`. Resolving a row raises an
  `unblocked` notice for each dependent that now waits on nothing. Refusing a
  claim on a waiting row is `BOARD_DEPENDENCY_GATE`, off by default; `force`
  on the claim overrides it. A target outside the live namespaces or that
  names no memory is a reference, not a prerequisite.
- **Server-held membership.** A turn-based agent (Claude, a subagent, a shell) can't
  hold a SLIM socket between turns, so the backend holds membership: `await`
  long-polls off a durable transcript cursor and refreshes a presence lease;
  `members()` is the union of live SLIM members and lease holders. This is why
  turn-based agents never miss a tick. The **durable inbox** (`persister.py`)
  re-serves missed point-to-point messages on rejoin (SLIM has no offline replay).
- **Sharing is the live channel.** Cross-machine sharing is the same SLIM channel over a
  shared node (`mycelium hub host` / `mycelium connect`), plus
  `mycelium room clone --from <api-url>` for a point-in-time HTTP snapshot. Git can back
  up or version the `.mycelium/` files but is **not** a sharing mechanism — no room flow
  pushes or pulls over git.
- **No Ensue references in code.** We took inspiration from their API design but the
  implementation is independent.
- **L9 envelopes are additive, never required of agents.** Ticks are `exchange`,
  consensus is `commit:converged|rejected`, with episode URNs and causal
  `message.parents`. The subkind table lives in `app/services/l9.py:VALID_SUBKINDS`
  and is SLIM-native (`converged|resolved|rejected`).
- **CLI/backend SLIM+L9 duplication is guarded by a contract test.** The thin `uv
  tool` CLI can't import the backend, so `mycelium/slim/` copies the SLIM+L9
  primitives. `contracts/slim-l9-wire.json` freezes the shared wire constants;
  both `fastapi-backend/tests/test_slim_l9_wire.py` and
  `mycelium-cli/tests/test_slim_l9_wire.py` assert against it, so neither copy can
  drift without a red unit gate.
- **The HTTP-API JWT gate is opt-in and off by default.** `app/services/auth.py`
  validates a bearer JWT against configured issuers + JWKS (`[auth]` in
  config.toml → `AUTH_*` env). It's an app-wide FastAPI dependency, so a new route
  is gated by default; health/docs stay public. Trust is a list of issuers matched
  by exact `iss`, each with its own keys and default role — that's how a workload
  trust root slots in later without issuer-specific code. Off by default is a
  hard requirement, not a default worth revisiting: auth must never block the
  try-it path. The localhost bypass reads the request's peer address, so it does
  **not** fire for a containerized backend (published-port traffic looks like LAN
  traffic) — the local tier is served by leaving auth off.
- **SLIM channel identity is a two-rung ladder, and it starts off.** `slim.identity` /
  `SLIM_IDENTITY` selects the tier; both are implemented (`slim_identity.py` + its
  CLI mirror), and the constants are frozen in `contracts/slim-l9-wire.json`.
  - `psk` (**default**, #567) — the group key derives from
    `MYCELIUM_SLIM_MASTER_SECRET`, set the same on every host that shares rooms. Zero
    infra, no per-member identity. `MYCELIUM_SLIM_REQUIRE_SECRET=1` makes a host fail
    closed rather than fall back to the public dev literal.
  - `signerjwt` (#476) — the floor: each member mints its own self-signed ES256
    credential and registers its public JWK on the room roster, so members are
    cryptographically distinct MLS participants with no external infra.

  Selecting `signerjwt` with no resolvable material degrades to `psk` with a one-time
  warning unless `MYCELIUM_SLIM_IDENTITY_REQUIRE=1` fails closed. Per-member
  revocation (#590 — drop the JWK, no room-wide re-key) ships. What still gates
  anything hosted / multi-user is turning identity on at all — not a missing
  capability.
- **The SPIRE tier is gone, not deprecated (#668).** `slim.identity=spire`, the
  `spire_registry` module, the `spire` compose profile and its server/node-daemon
  services were removed outright, matching the openclaw/hermes precedent (#503).
  It attested the backend to itself on one box — SPIRE server and node daemon
  co-located with the workload they vouched for — so it bought short-lived
  process-bound credentials, not the cross-trust-domain attestation the name
  signals, and it was the stack's biggest source of operational breakage
  (recreating the backend orphaned the daemon's PID-namespace link). Don't
  reintroduce it as an identity option; the conditions for reviving it are #669,
  and they start with a real client-held multi-party topology (#662) for it to
  attest across.
- **Custodial sessions are server-side, and off by default (#666).** Under an
  identity tier (`signerjwt`) the backend stops impersonating actors and
  becomes the **custodian of N per-actor MLS sessions** — one genuine MLS member per
  `(room, actor)`, keyed by handle (`app/services/custody.py`). The name is the term
  of art: *custodial* (the custodian holds your keys for you, like a custodial
  wallet); server-side is the custodial rung, client-held is the non-custodial one.
  `respond(@alice, …)` sends through @alice's session, so attribution is cryptographic
  on the wire (not a backend-stamped L9 field) and room access is MLS group
  membership, not app logic. All sessions live in the backend process, so the
  moderator App + aligner/memory/L9 still read plaintext — cognition is
  preserved. **Under the PSK default nothing changes** (byte-for-byte;
  `MYCELIUM_CUSTODY_DISABLE=1` forces the single-moderator path even under identity),
  and persistence structurally requires the identity provider/verifier pair anyway (a
  custodial session cannot run on PSK). Per-session MLS state persists in an encrypted
  SQLite store (passphrase = `HMAC(MYCELIUM_CUSTODY_STORE_SECRET, ws/room/handle)`);
  on restart `restore_sessions` revives every session with **no re-invite** (proven
  across a real two-process kill/restart). **Honest scope boundary (keep it honest in
  code + the user-facing guides):** custodial means the hub still holds
  every key + plaintext; this hardens the wire + attribution + access-by-membership,
  and it is **NOT** E2E-from-the-hub.
- **The UI is part of the stack, not an opt-in profile.** `mycelium-frontend` has
  no compose profile: `mycelium install` and `mycelium up` bring it up alongside
  the SLIM node and the backend, and `mycelium down` / `logs` / `status` see it
  without any profile plumbing. The app *is* the product surface — the CLI is the
  agent-facing protocol, the browser is where a human works — so there is no
  `--ui` / `--no-ui` flag and no install prompt to decline it. The collector
  (`profiles: [metrics]`) is still the one opt-in service.
- **Usage is counted by the task, recorded on the hub, and shared only with
  consent.** The product's KPIs come from usage events the hub records
  itself (`app/services/analytics.py`): `hub_started`, `task_filed` and
  `task_resolved` (off the board's notices, in `main.py`'s notice
  dispatcher), `flow_completed` (the conductor's close),
  `negotiation_completed` (the aligner) and `agent_joined` (an
  `agents/<handle>` manifest appearing). They follow the unit of work, not
  one engine, so every way the app starts work lands in them. They are
  appended to `usage/events.jsonl` in the data dir, always, and
  `GET /api/observability/usage` adds them up for the Metrics page. They
  carry kinds and outcomes, never a name, handle, room or text
  (`PROHIBITED_FIELDS`, and a room's own flow counts as `custom`).
  Sending them to `telemetry.analytics_destination` is
  `telemetry.send_product_analytics`, off by default, asked at
  `mycelium install` and on the Mac app's first screen, whose answer wins
  for the hub it starts (`desktop serve --share-usage`). This is separate
  from the OTel export (`telemetry.enabled`), which is the backend's own
  operational metrics.
- **Room folders are a person's, not a room's.** How someone files their
  rooms list is kept on the hub under their handle
  (`GET`/`PUT /api/users/{handle}/room-folders`,
  `app/services/room_folders.py`, one JSON file at
  `preferences/<handle>/room-folders.json`), so it follows them across
  browsers and into the app. It sits beside the user store rather than in it,
  because `contracts/user-store.json` freezes the record the CLI mirrors, and a
  preference is not identity. On a gated hub only your own is readable or
  writable. A room knows nothing about the folders it is in; a room sits in at
  most one of a person's folders; before a name is chosen, the layout lives in
  the browser (`useRoomFolders`, `lib/room-folders.ts`).
- **GUI server state is one SWR cache; client state stays local.** Every room
  read in the frontend goes through `mycelium-frontend/src/lib/room-data.ts` —
  typed SWR hooks keyed `["room", name, resource]`, so N panels reading the same
  resource make one request and share one cache entry (the composer's `@`
  popover and the Members rail are two views of one `useRoomRoster`). SWR owns
  polling, refocus and dedup, so components hold no `setInterval` and no
  fetched-data `useState`; a pushed SSE event calls `useRoomRevalidate(room)`
  rather than threading a refresh counter down as a prop. A store (Zustand) is
  reserved for genuine client state — which rail is open, what's selected — not
  for anything the hub owns.
- **A2A bridge is proxied, not an MLS member (be honest).** The A2A bridge (epic
  #719) makes a room speak Agent2Agent both ways: `adapter: a2a` registers a
  remote endpoint as a room member (`a2a_bridge.py` answers its `@`-mentions by
  calling it — event-driven off the summon seam, chat-first, not negotiation-
  scoped), and `a2a_server.py` exposes a room *as* an A2A agent via the a2a-sdk
  server (card + JSON-RPC). **Honest boundary:** a bridged A2A agent is **not** a
  member of the room's MLS group — it's proxied by a backend seat that reads
  plaintext and calls the remote out-of-band. **The hop is plain HTTPS (decided
  default, #726):** `slima2a` (SLIMRPC transport) pins `a2a-sdk==1.1.0` exactly
  while the backend tracks `1.1.2`, so adopting it would pull SQLAlchemy,
  aiosqlite, and OpenTelemetry into the image — cost not justified yet. Reopen
  #726 when the pin relaxes and a live SLIMRPC round-trip is proven. Even
  SLIMRPC would be point-to-point RPC to a SLIM identity, still not room-group
  membership. Either way the hub sees plaintext, so it is **NOT** E2E-from-the-hub.
  Remote auth is a bearer token named by `a2a_auth_env` and resolved from the
  backend env — the secret never lands in room memory.
- **CI is fast on purpose; timing is reported, never enforced.** A PR run's
  critical path is ~95s, and that is a property worth defending — it erodes
  twenty seconds at a time, invisibly. The `timing` job reads the run's own job
  durations back from the Actions API, writes them into the run summary, and
  warns against the budgets in `.github/ci-budgets.json`. It cannot fail a run:
  a slow PR should merge and say it was slow. Raise a budget deliberately, in
  the PR that makes the job slower. `scripts/check_workflows.py` (the `hygiene`
  job) keeps the budgets naming real jobs, every `uses:` pinned to a commit SHA,
  and every workflow declaring its own `permissions:`.
- **CI is tiered, and the tier is the design decision.** Tier 0 is per-PR and
  must stay parallel and under ~60s (the contract tests below all live inside
  jobs that already run). Tier 1 is per-PR but path-filtered — the three image
  smoke builds, and the docs link check. Tier 2 is `nightly.yml`: the full
  install path and the live-LLM cognition slice, too slow and too paid for the
  PR path, where a failure opens one issue rather than blocking a person.
  Putting a good check in the wrong tier is how the ~95s baseline gets spent.
- **The CLI takes its shared flags one way, and two audits hold it there.**
  Agents type a CLI the way they type every other one, so `--room`, `--as`,
  `--json`, `--limit` and `--yes` are decorators in `mycelium/cli_options.py`
  (`in_room`, `acts_as`, `emits_json`, `paged`, `confirms`; text an agent writes
  is `text_input.takes_text`: the argument, `--body` or `--file`) that spell,
  default and resolve them the same everywhere. A new command uses them rather
  than declaring the flags itself. `mycelium.cli_audit` walks the built CLI and
  fails on drift (a read with no `--json`, a required `--as`, a `--room`
  without `-r`); `mycelium.cli_prose` parses every `mycelium …` command written
  in the docs, skills, prompts and frontend strings against the same CLI, so a
  renamed flag can't survive in what agents are told. Both run as tests; an
  exemption names its reason, and a stale one is a finding.
- **The checks are derivations, not lists.** Every gate added here recomputes
  something and fails on the drift, rather than asserting against a copy that
  has to be maintained: `openapi.json` vs the live app, `docs/*.html` vs its
  markdown, the frontend's `/api/*` fetches and its mock fixture *shapes* vs the
  spec, `compose.yml`'s services vs the container names the CLI addresses,
  `MyceliumConfig`'s fields vs what `generate_env_file` renders. Where a thing
  legitimately can't be derived, it is declared with its reason next to the code
  that owns it (`docker_utils.LOCAL_ONLY_FIELDS`, `ENVIRONMENT_SUPPLIED_VARS`)
  and the check asserts the declaration is still true — a stale exemption is a
  failure too.
- **A config field that reaches no container is a bug, not a feature.** `.env`
  is the only transport from `config.toml` into the stack, so a field nothing
  renders is a setting a user writes and watches do nothing. Both directions are
  gated (`tests/test_config_env_coverage.py`): every config leaf renders or is
  declared local-only, and every `${VAR}` compose substitutes has something that
  writes it — otherwise `config apply` silently drops a hand-set value.
- **Screenshots are captured and committed by hand.** `pnpm screenshots`
  (in `mycelium-frontend/`) shoots the mock app and writes the PNGs into
  `docs/` and a sibling splash checkout (`MYCELIUM_SPLASH_DIR`); a person
  looks at them and opens the PRs. There is no workflow that opens pull
  requests on its own.
- **The docs site is the latest stable release's, not main's.** Pages
  publishes `docs/` from a workflow (`pages.yml`) that `release.yml` calls
  once a stable release is out, at its tag, so the site never documents what
  no user can install yet (and `install.sh`, served from it, matches the
  release it installs). A docs change merged to main goes live with the next
  release; `gh workflow run pages.yml -f ref=<ref>` redeploys by hand for a
  fix that can't wait. Videos under `docs/` are Git LFS objects, which is
  why it is a workflow: Pages serves a branch's LFS pointers, not the files.

## Local development

> **This section is for contributors iterating on the backend source.** End users
> follow the normal install path:
> `curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash`, which on
> an Apple silicon Mac installs and opens Mycelium for Mac (no Docker) and
> elsewhere installs the CLI for `mycelium install` (`--docker` picks that on a
> Mac, `--client-only` the CLI alone).

### Starting the stack

The `mycelium up` / `mycelium install` flow uses `compose.yml` with
`pull_policy: always` (released images), the correct Docker path for end users. For dev,
add `compose-dev.yml`, which builds `mycelium-backend` from local source and wires
`~/.mycelium/.env` into the containers. The stack is a SLIM node + the backend (+
the frontend, plus an optional collector), with **no database**. Always run
from the repo root.

```bash
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --build
```

On subsequent runs, drop `--build` unless you've changed backend code. The
frontend comes up with the stack; add `--profile metrics` for the collector.

### LLM config

All containers get their LLM settings from `~/.mycelium/.env`, generated from
`config.toml`. Set these once (the aligner's Pi session uses them):

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "<key>"
mycelium config set llm.base_url "<base-url>"
mycelium config apply
```

Then recreate the backend to pick up the new env:

```bash
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --force-recreate mycelium-backend
```

**Important:** `mycelium config apply` regenerates `.env` from `config.toml`. If you
edit `.env` directly, those changes are overwritten. Always use `mycelium config set`.

### Running the backend outside Docker (hot-reload)

```bash
cd fastapi-backend
uv run uvicorn app.main:app --reload --port 8000
```

No DB is needed. The SLIM node still must be running (`mycelium hub host`, or the
`slim` compose service). The aligner's Pi mediator needs `pi` on PATH when the
backend runs on the host (the image ships it; `mycelium doctor` warns if it's
missing). Update `config.toml` if you change the backend port:

```bash
mycelium config set server.api_url "http://localhost:8000"
mycelium config apply
```

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: unit tests run against local files + temp `.mycelium/` dirs (conftest.py
  sets `MYCELIUM_DATA_DIR`); the live-node SLIM slices are guarded by a reachable
  node (`MYCELIUM_SLIM_ENDPOINT`) and skip without one
- Live-LLM tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
- **No design or planning documents in git.** Plans, design briefs, RFCs,
  proposals, implementation write-ups and per-issue notes do not belong in this
  repo — not under `docs/`, not beside the code they describe. They are stale the
  week after they are written, and a reader who finds one cannot tell whether it
  describes the code, a path not taken, or a plan nobody executed. The code, its
  tests, and the PR that changed it are the record; anything that needs to argue
  for a decision belongs in the PR body or the issue, where it stays attached to
  the change it justifies. Don't open a PR that adds one, and don't create one as
  a step toward doing the work — do the work.

  What *does* belong here: current-state documentation (`mycelium-cli/src/mycelium/docs/`,
  the READMEs, this file), runbooks, and the contracts under `contracts/`.
