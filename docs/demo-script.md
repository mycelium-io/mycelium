# Mycelium Demo Script

## Prerequisites

```bash
# Install Mycelium. On an Apple silicon Mac this installs and opens the Mac
# app: choose On this Mac, then Start Mycelium. Elsewhere it installs the CLI.
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# Off a Mac (or after --docker): bring up the stack, a thin backend + the UI
mycelium install

# Verify
mycelium --help
mycelium doctor
```

The app (or `mycelium install`, in Docker) starts an always-on thin FastAPI
backend that keeps each room's log, and the UI (`http://127.0.0.1:3717` in the app,
`http://localhost:3000` in Docker). There is no database: rooms are folders, memories are
markdown, and search runs against a local embedding index. Pick an LLM during
install; the members the hub runs itself, such as personas and the synthesizer,
use it.

---

## Part 1: Filesystem-Native Memory

### Setup

```bash
mycelium room create design-review
mycelium room use design-review

# A room is just a folder:
ls .mycelium/rooms/design-review/
# decisions/  failed/  status/  context/  work/  procedures/  log/  plan/
```

### Agent 1: Avery shares architecture decisions

```bash
# CLI syntax: mycelium memory set KEY VALUE [--handle AGENT]
mycelium memory set decisions/scope "Ship the reduced-scope Q3 spec first" --handle avery-agent
mycelium memory set decisions/llm-provider "litellm: provider/model format, one interface" --handle avery-agent
mycelium memory set decisions/api-style "REST for now, generated OpenAPI client for type safety" --handle avery-agent

# These are just markdown files:
cat .mycelium/rooms/design-review/decisions/scope.md
# ---
# key: decisions/scope
# created_by: avery-agent
# version: 1
# ---
# Ship the reduced-scope Q3 spec first
```

### Agent 2: Rowan shares research

```bash
cat > .mycelium/rooms/design-review/context/staging.md << 'EOF'
---
key: context/staging
created_by: rowan-agent
version: 1
---
Staging environment provisions in ~4 min from the base image; safe to stand up per-launch
EOF
```

### Agent 3: Kappa reports what didn't work

```bash
mycelium memory set failed/big-bang-launch "Tried a single all-features launch last quarter and slipped twice. Reduced scope ships on time." --handle kappa-agent
```

### Browse & Search

```bash
ls .mycelium/rooms/design-review/decisions/
# api-style.md  llm-provider.md  scope.md

grep -r "reduced-scope" .mycelium/rooms/design-review/

# Or use the CLI for structured views:
mycelium memory decisions     # Why choices were made
mycelium memory status        # Current state of things
mycelium memory context       # Background & constraints

# Read with cat or with the CLI:
cat .mycelium/rooms/design-review/decisions/scope.md
mycelium memory get decisions/scope

# Semantic search over the local embedding index:
mycelium memory search "what scope decisions were made"
mycelium memory search "what failed"

# Re-index after direct file writes (cat/editor/agent file I/O):
mycelium memory reindex
```

### Watch in real-time

Open a second terminal:
```bash
mycelium watch design-review
```

Then write memories from the first terminal; they appear live in the watch output.
The UI room view is at `http://localhost:3000/room/design-review`, and
`/room/design-review/graph` draws the room's memories as a link graph — worth showing
once a few memories reference each other, since it makes the shape of what the agents
have built visible at a glance (and flags anything broken or orphaned).

### Sharing across machines

Sharing is the **hub**, not a file sync. The hub holds the one copy of the room;
every other machine is a thin client that reads and writes it over HTTP:

```bash
# On another machine, point at the hub and use the same room:
mycelium init --api-url http://<hub-ip>:8000
mycelium room use design-review
mycelium memory search "what scope decisions were made"
```

A spoke keeps no local `.mycelium/` replica, so there is nothing to reconcile and no
window in which two machines disagree. For a point-in-time copy instead of live
participation, `mycelium room clone design-review --from <api-url>` takes an HTTP
snapshot.

Git can still version or back up the hub's `.mycelium/` files, but it is **not** a
sharing path — no room flow pushes or pulls over git. See the Hub & Spoke guide.

---

## Part 2: A Flow Inside a Task

A flow is a set sequence of turns the **conductor** runs inside a task. The
conductor is an engine the hub runs, registered in the room and summoned by
`@`-mention. It has no model of its own: it decides who speaks next, and the
members do all the thinking. Its `gated` flow has one member propose and
another approve or reject, until the plan is approved.

### Register the conductor (once per room)

```bash
mycelium engine create conductor --kind conductor --room design-review
```

### Put the question on the board

```bash
mycelium board new "Settle the Q3 launch scope"
```

The task arrives with its own thread, and the argument happens there.

### Each participant posts an opening position

**Terminal 1 (or Claude Code instance 1), avery-agent:**
```bash
mycelium room use design-review
mycelium iam avery-agent
mycelium board send work/settle-the-q3-launch-scope \
  "Prioritize the reduced-scope Q3 spec; we've slipped on big-bang launches before."
```

**Terminal 2 (or Claude Code instance 2), rowan-agent:**
```bash
mycelium iam rowan-agent
mycelium board send work/settle-the-q3-launch-scope \
  "Focus on demo UX and frontend polish. Staging is cheap to stand up per-launch."
```

**Terminal 3 (audience view):**
```bash
mycelium watch design-review
```
Or open `http://localhost:3000/room/design-review`.

### Run a gated flow

A human (or an agent) puts the conductor on the task with the `gated` flow,
naming the proposer and then the guardian:

```bash
mycelium board coordinate work/settle-the-q3-launch-scope conductor \
  "gated @~avery-agent @~rowan-agent: what do we ship in Q3, and when?"
```

This opens an **episode** inside the task, with its own record at
`log/episodes/{id}.md` that shows the flow and each step it took. The proposer
says what it plans, and the guardian approves or rejects it with a reason. A
rejection goes back to the proposer, until the guardian approves or the step
limit is reached.

### Participants loop: await → respond

Each participant long-polls for the conductor's prompts and replies in prose:

```bash
# Blocks until a message is addressed to the handle:
mycelium await --room design-review --handle avery-agent --json
# → read the conductor's prompt, then answer it in the thread:
mycelium respond --room design-review --handle avery-agent \
  "Reduced scope, launch in August. Big-bang launches slipped twice last quarter."
```

Repeat `await` → `respond` until the conductor closes the run. Agents only use
the CLI; two stateless HTTP calls carry the whole loop.

### Outcome → memory → work

When the run closes, the conductor commits `commit:resolved` (the guardian
approved) or `commit:rejected` (it gave up or hit its step limit). Keep what
was decided where later work will find it:

```bash
mycelium memory set decisions/q3-launch-scope "Reduced scope, launch in August."
```

### Prompt for the other Claude Code agent

Give this to the second Claude Code instance:

> You are participating in a Mycelium coordination room called `design-review`. You
> are `rowan-agent`. Your position: "Focus on demo UX and frontend polish; staging
> is cheap to stand up per-launch."
>
> ```bash
> mycelium room use design-review
> mycelium iam rowan-agent
> mycelium board send work/settle-the-q3-launch-scope \
>   "Focus on demo UX and frontend polish. Staging is cheap to stand up per-launch."
> ```
>
> Then loop until the conductor closes the run:
> ```bash
> mycelium await --room design-review --handle rowan-agent --json
> # read the conductor's prompt, then answer it in prose, ending with
> # [[mycelium: stance=accept]] or [[mycelium: stance=reject]]:
> mycelium respond --room design-review --handle rowan-agent "<your reply>"
> ```
>
> When it closes, read the decision with
> `mycelium memory get decisions/q3-launch-scope` and work the task from there.

---

## Part 3: The Story (for the presentation)

### Talking points

1. **The problem**: Agents today are semantically isolated. No shared intent, no
   shared context, no ratchet effect.

2. **The substrate**:
   - **Transport** → one log per room on the hub; agents read it with `await` and
     the app follows it live.
   - **Memory** → rooms are folders, memories are markdown, search is a local
     embedding index. Sharing is the hub, not a file sync.
   - **Flows** → the conductor runs a flow such as `gated` or `review` inside the
     task, giving each member its turn.

3. **The ratchet effect**: A new agent arrives in a room and reads
   `.mycelium/rooms/{room}/` to instantly inherit decisions, failures, and the open
   plan. Intelligence compounds across sessions instead of resetting.

4. **Negative results matter**: Show `mycelium memory decisions` and the `failed/`
   namespace. Agents log what didn't work (and why) so others don't repeat dead ends.

5. **Decisions are kept**: A decision doesn't end in a scrolled-away thread. It is
   saved as a memory under `decisions/`, where every later agent finds it.

### Key URLs during demo

- Frontend: `http://localhost:3000`
- Room view: `http://localhost:3000/room/design-review`
- Link graph: `http://localhost:3000/room/design-review/graph`
- Backend API docs: `http://localhost:8000/docs`
