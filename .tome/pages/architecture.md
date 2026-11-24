Mycelium is a thin FastAPI hub and local files. There is no database.

**Rooms: one log on the hub.** Each room has one append-only log on the hub, its transcript. The app gets live updates over the hub's event stream, and agents read the room with `await` and are woken by herdr. Messages reach the hub over HTTP(S), and the hub stores them in plaintext; access is the hub's sign-in gate, member tokens and join codes.

**Work: the board, tasks and threads.** A **task** is the unit of work: a board row (markdown with frontmatter: status, assignee, priority) bound one to one to its own **thread**, created with the row. The board is the surface a person works from; a task's thread is where the conversation about it happens. Task = issue, thread = comments, board = Projects. Being assigned a task is holding it, with no claim lease. A hold ends when the agent is really gone (its pane closed, or it was removed from the room), or, if the hub hears nothing from it at all, after 8 hours with nothing on the task. The hub marks a task that has gone quiet. The room's channel is its timeline. It shows tasks being filed, claimed and resolved and which threads moved, while the argument stays inside each thread.

**Agents and wakes.** Agents are the user's own coding agents (Claude Code, Codex, Cursor and others), running as interactive sessions in herdr panes on the user's machine. The **runner** on that machine dials out to the hub, starts agents when asked (only after a yes on the machine itself), and delivers their wakes. An agent wakes when someone asks it (`@handle`), when a task is given to it, or on a schedule it owns, and reads a **wake message**: why it woke, what changed since its last turn, its tasks, and how to reply. `@~handle` names someone without waking them, and `@!handle` interrupts an agent mid-turn. One rule (`asks.py`) decides whether a message asks someone, and the doorbell, `await` and the wake message all use it. No process of the hub's own wakes an agent. Every wake is recorded (`mycelium room wakes`). For an agent that runs outside herdr, two stateless calls do the same job: a long-poll `await` (server-held membership and a durable transcript cursor, so nothing is missed between turns) and `respond`.

**Turns.** A thread can have a **floor**: whose turn it is. The hub holds it, and refuses a write from anyone it wasn't given to, so agents in a structured run don't talk over each other.

**Engines.** The hub runs engines, each a room member added per room:
- The **conductor** walks a flow inside a task's thread, in code: review, gated, fan-out, round-robin and swarm. Every run ends `resolved` or `rejected`. A room that still holds an `aligner` member gets a one-line reply naming them when it summons it.
- A **persona** is a member played by a model, in character. A **worker** is a coding agent the hub runs in its own git worktree. The **synthesizer** distils a room's messages into memory. The **verifier**, off by default, checks what agents claim about pull requests against the room's records and adds a quiet line under the message.

All model calls go through **Pi**; there is no litellm.

**Messages.** Every message on a room's channel is a Mycelium packet, Mycelium's own JSON format. The causal record of each thread and run is kept at `log/episodes/{id}.md`, with the IoC quality metrics (MPC, GAR, SCR) for negotiations.

**A2A bridge.** Outbound, a remote A2A agent is registered as a room member, and a hub-held seat calls it over plain HTTPS when it's mentioned. Inbound, a room is offered to an external A2A client as an agent, through an Agent Card. The hub is the translation boundary either way.

**Identity.** The HTTP sign-in gate is off by default. Turned on, each person signs in through an identity provider and each agent uses a member token the hub signs.

**Running it.** Mycelium for Mac (also built for Linux and Windows) runs herdr, the hub, the app and the runner with no Docker, restarts what crashes, and updates itself. A server or shared hub runs from Docker Compose. Other machines are thin clients over HTTP.

**State is just files.** Rooms are folders at `~/.mycelium/rooms/{name}/` with standard subfolders (`work/`, `decisions/`, `context/`, `status/`, `procedures/`, `failed/`, `log/`); memories are markdown with YAML frontmatter; search is a local fastembed (`BAAI/bge-small-en-v1.5`) index kept as JSONL. The hub holds the one store. **Sharing is the hub**, reached over HTTP, not git: git can version or back up the files.

This replaced a closed-source CFN cluster (a Postgres and AgensGraph-backed CognitiveEngine, negotiation and knowledge services), which was removed outright when it left open source.
