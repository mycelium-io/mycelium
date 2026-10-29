# Mycelium Demo Script

## Prerequisites

```bash
# Install Mycelium. On an Apple silicon Mac this installs and opens the Mac
# app: choose On this Mac, then Start Mycelium. Elsewhere it installs the CLI.
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# Off a Mac (or after --docker): bring up the stack, one SLIM node + a thin backend
mycelium install

# Verify
mycelium --help
mycelium doctor
```

The app (or `mycelium install`, in Docker) starts a SLIM node (the encrypted
group-channel transport), an always-on thin FastAPI backend that acts as each
room's moderator, and the UI (`http://127.0.0.1:3717` in the app,
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

Sharing is the **live channel**, not a file sync. The hub runs the SLIM node and holds
the one copy of the room; every other machine is a thin client that reads and writes it
over that channel:

```bash
# On the hub — serves the SLIM node + backend, prints its LAN address:
mycelium hub host

# On another machine — point at the hub and use the same room:
mycelium connect http://<hub-ip>:46357
mycelium room use design-review
mycelium memory search "what scope decisions were made"
```

A spoke keeps no local `.mycelium/` replica, so there is nothing to reconcile and no
window in which two machines disagree. For a point-in-time copy instead of live
participation, `mycelium room clone design-review --from <api-url>` takes an HTTP
snapshot.

Git can still version or back up the hub's `.mycelium/` files, but it is **not** a
sharing path — no room flow pushes or pulls over git. See `cross-machine.md`.

---

## Part 2: Negotiating Inside a Task

Negotiation is a flow the **conductor** runs inside a task. The conductor is an
engine the hub runs, registered in the room and summoned by `@`-mention. It has
no model of its own: it decides who speaks next, and the members do all the
thinking. Its `concord` flow helps members agree on one option, and its
`accord` flow gets them on the same page about what the task is before work
starts.

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

### Run a concord

A human (or an agent) puts the conductor on the task with the `concord` flow:

```bash
mycelium board coordinate work/settle-the-q3-launch-scope conductor \
  "concord: what do we ship in Q3, and when?"
```

This opens an **episode** inside the task, with its own record at
`log/episodes/{id}.md` that shows the flow and each step it took.

1. Everyone rates the same two reference outcomes (no agreement, and their own
   pick), so each member's later ratings are read on their own scale.
2. Everyone proposes one option, with a `why:` line.
3. Everyone rates every option, one line each, with a reason.
4. The hub picks the option the least happy member is best off with. If someone
   is still short of the bar, that member proposes something new that answers
   the objections, and everyone rates it. This repeats until everyone meets the
   bar or the fixes run out and the best option found stands.

### Participants loop: await → respond

Each participant long-polls for the conductor's prompts and replies in prose:

```bash
# Blocks until a message is addressed to the handle:
mycelium await --room design-review --handle avery-agent --json
# → read the conductor's prompt, then answer it in the thread:
mycelium respond --room design-review --handle avery-agent \
  "Reduced scope, launch in August.
why: big-bang launches slipped twice last quarter."
```

Repeat `await` → `respond` until the conductor closes the run. Agents only use
the CLI; two stateless HTTP calls carry the whole loop.

### Agreement → memory → work

When the run closes, the conductor commits `commit:converged` (everyone met the
bar), `commit:resolved` (the best option found stands) or `commit:rejected`
(nothing workable), and saves the decision under `context/decision/`, named
after the task. Later work in the task is shown what was saved.

```bash
mycelium memory get context/decision/settle-the-q3-launch-scope
```

To get everyone on the same page before the work starts, run `accord` on the
same task: everyone states what the task is, what each key term means and which
checks they own, and the hub merges it into one shared summary under
`context/summary/`, with anything that doesn't line up flagged.

```bash
mycelium board coordinate work/settle-the-q3-launch-scope conductor \
  "accord: agree what the Q3 launch is terms: launch, scope"
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
> # read the conductor's prompt, then answer it in prose, in the format it asks for:
> mycelium respond --room design-review --handle rowan-agent "<your reply>"
> ```
>
> When it closes, read the decision with
> `mycelium memory get context/decision/settle-the-q3-launch-scope` and work the
> task from there.

---

## Part 3: The Story (for the presentation)

### Talking points

1. **The problem**: Agents today are semantically isolated. No shared intent, no
   shared context, no ratchet effect.

2. **The substrate**:
   - **Transport** → one SLIM node; agents coordinate over an MLS-encrypted group
     channel per room.
   - **Memory** → rooms are folders, memories are markdown, search is a local
     embedding index. Sharing is the live SLIM channel, not a file sync.
   - **Negotiation** → the conductor runs `concord` or `accord` inside the task,
     and saves what the members agree to the room's memory.

3. **The ratchet effect**: A new agent arrives in a room and reads
   `.mycelium/rooms/{room}/` to instantly inherit decisions, failures, and the open
   plan. Intelligence compounds across sessions instead of resetting.

4. **Negative results matter**: Show `mycelium memory decisions` and the `failed/`
   namespace. Agents log what didn't work (and why) so others don't repeat dead ends.

5. **Agreement is kept**: The negotiation doesn't end in a scrolled-away thread. The
   decision is saved as a memory for the task, with who is short of the bar and why,
   and every later step of the work in that task is shown it.

### Key URLs during demo

- Frontend: `http://localhost:3000`
- Room view: `http://localhost:3000/room/design-review`
- Link graph: `http://localhost:3000/room/design-review/graph`
- Backend API docs: `http://localhost:8000/docs`
