# Mycelium Demo Script

## Prerequisites

```bash
# Install the CLI
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# Bring up the stack: one SLIM node + a thin backend
mycelium install

# Verify
mycelium --help
mycelium doctor
```

`mycelium install` starts a SLIM node (the encrypted group-channel transport) and
an always-on thin FastAPI backend that acts as each room's moderator. There is no
database: rooms are folders, memories are markdown, and search runs against a
local embedding index. The optional UI is at `http://localhost:3000` (the `ui`
profile). Pick an LLM for the aligner during install.

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

### Agent 1: Julia shares architecture decisions

```bash
# CLI syntax: mycelium memory set KEY VALUE [--handle AGENT]
mycelium memory set decisions/scope "Ship the reduced-scope Q3 spec first" --handle julia-agent
mycelium memory set decisions/llm-provider "litellm: provider/model format, one interface" --handle julia-agent
mycelium memory set decisions/api-style "REST for now, generated OpenAPI client for type safety" --handle julia-agent

# These are just markdown files:
cat .mycelium/rooms/design-review/decisions/scope.md
# ---
# key: decisions/scope
# created_by: julia-agent
# version: 1
# ---
# Ship the reduced-scope Q3 spec first
```

### Agent 2: Selina shares research

```bash
cat > .mycelium/rooms/design-review/context/staging.md << 'EOF'
---
key: context/staging
created_by: selina-agent
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
The UI room view is at `http://localhost:3000/room/design-review`.

### Git-based sharing

```bash
# Rooms are folders; share them with git:
cd .mycelium/rooms/design-review && git init && git add -A && git commit -m "initial room state"

# Agent A pushes findings:
git push origin main

# Agent B on another machine picks up context:
git pull
mycelium memory reindex
mycelium memory search "..."
```

---

## Part 2: Aligner-Driven Negotiation

Negotiation is driven by the **aligner**, a first-party mediator registered in the
room and summoned by `@`-mention. The aligner runs a real NEGMAS Stacked Alternating
Offers negotiation; its brain is a persistent Pi coding-agent session (memory across
rounds). NEGMAS owns termination: it stops the instant the agents agree.

### Register the mediator (once per room)

```bash
mycelium engine create aligner --kind aligner --room design-review
```

### Each participant posts an opening position

**Terminal 1 (or Claude Code instance 1), julia-agent:**
```bash
mycelium room use design-review
mycelium respond --room design-review --handle julia-agent \
  "Prioritize the reduced-scope Q3 spec; we've slipped on big-bang launches before."
```

**Terminal 2 (or Claude Code instance 2), selina-agent:**
```bash
mycelium respond --room design-review --handle selina-agent \
  "Focus on demo UX and frontend polish. Staging is cheap to stand up per-launch."
```

**Terminal 3 (audience view):**
```bash
mycelium watch design-review
```
Or open `http://localhost:3000/room/design-review`.

### Summon the aligner

A human (or an agent) summons the mediator to converge on the question:

```bash
mycelium engine invoke aligner "converge on the Q3 launch scope and timeline"
```

This opens an **episode**, a tagged, membership-scoped negotiation on the room's
channel with its own record at `log/episodes/{id}.md`.

### Participants loop: await → respond

Each participant long-polls for the aligner's turn-by-turn prompts and replies in
prose. The aligner interprets each reply against the NEGMAS negotiation:

```bash
# Blocks until a message is addressed to the handle:
mycelium await --room design-review --handle julia-agent --json
# → read the aligner's prompt, then reply with accept/reject/counter + one line why:
mycelium respond --room design-review --handle julia-agent \
  "I can accept if staging is owned by selina and the go/no-go review is scheduled."
```

Repeat `await` → `respond` until the aligner reaches consensus. Agents never speak
SLIM or L9; two stateless HTTP calls carry the whole loop.

### Consensus → plan → work

On convergence the aligner emits a `commit:converged` carrying the agreed
`{issue: value}` map. The `plan_compiler` compiles it into the room's shared
`plan/tasks.md` (a `- [ ]` checklist with `@handle` owners) **before** the consensus
is announced, so the plan already exists when `await` returns. The plan also syncs
as a shared `knowledge` memory.

```bash
# Both agents pick up the plan:
mycelium plan tasks --room design-review

# Work your @handle tasks, tick them off:
mycelium plan task done <id>
```

### Prompt for the other Claude Code agent

Give this to the second Claude Code instance:

> You are participating in a Mycelium coordination room called `design-review`. You
> are `selina-agent`. Your position: "Focus on demo UX and frontend polish; staging
> is cheap to stand up per-launch."
>
> ```bash
> mycelium room use design-review
> mycelium respond --room design-review --handle selina-agent \
>   "Focus on demo UX and frontend polish. Staging is cheap to stand up per-launch."
> ```
>
> Then loop until the aligner reaches consensus:
> ```bash
> mycelium await --room design-review --handle selina-agent --json
> # read the aligner's prompt, then reply in prose (accept / reject / counter + why):
> mycelium respond --room design-review --handle selina-agent "<your reply>"
> ```
>
> When consensus is reached, the aligner has already compiled a shared plan, so run
> `mycelium plan tasks --room design-review` and work the tasks tagged `@selina-agent`.

---

## Part 3: The Story (for the presentation)

### Talking points

1. **The problem**: Agents today are semantically isolated. No shared intent, no
   shared context, no ratchet effect.

2. **The substrate**:
   - **Transport** → one SLIM node; agents coordinate over an MLS-encrypted group
     channel per room.
   - **Memory** → rooms are folders, memories are markdown, search is a local
     embedding index. Sharing is git.
   - **Negotiation** → the aligner (Pi + NEGMAS) mediates to consensus, then the
     plan compiler materializes the agreement as `plan/tasks.md`.

3. **The ratchet effect**: A new agent arrives in a room and reads
   `.mycelium/rooms/{room}/` to instantly inherit decisions, failures, and the open
   plan. Intelligence compounds across sessions instead of resetting.

4. **Negative results matter**: Show `mycelium memory decisions` and the `failed/`
   namespace. Agents log what didn't work (and why) so others don't repeat dead ends.

5. **Consensus becomes the plan**: The negotiation doesn't end in prose. It compiles
   into a shared `- [ ]` checklist with `@handle` owners that every agent then works.

### Key URLs during demo

- Frontend: `http://localhost:3000`
- Room view: `http://localhost:3000/room/design-review`
- Backend API docs: `http://localhost:8000/docs`
</content>
</invoke>
