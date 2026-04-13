# Mycelium Demo Script

## Prerequisites

```bash
# Install the CLI
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# Spin up the full stack (backend + AgensGraph + frontend)
mycelium install

# Verify
mycelium --help
```

---

## Part 1: Filesystem-Native Memory

### Setup

```bash
mycelium room create design-review --trigger threshold:5
mycelium room use design-review

# Room is a folder now:
ls .mycelium/rooms/design-review/
# decisions/  failed/  status/  context/  work/  procedures/  log/
```

### Agent 1: Julia shares architecture decisions

```bash
# Category keys (work/, decisions/, context/, status/) get auto-validated
# CLI syntax: mycelium memory set KEY VALUE [--handle AGENT]
mycelium memory set decisions/database "Consolidated to single AgensGraph instance — SQL + graph + vector in one DB" --handle julia-agent
mycelium memory set decisions/llm-provider "litellm — 100+ providers, one interface" --handle julia-agent
mycelium memory set decisions/api-style "REST for now, generated OpenAPI client for type safety" --handle julia-agent

# These are just markdown files:
cat .mycelium/rooms/design-review/decisions/database.md
# ---
# key: decisions/database
# created_by: julia-agent
# version: 1
# ---
# Consolidated to single AgensGraph instance — SQL + graph + vector in one DB
```

### Agent 2: Selina shares research

```bash
cat > .mycelium/rooms/design-review/research/pgvector-perf.md << 'EOF'
---
key: research/pgvector-perf
created_by: selina-agent
version: 1
---
pgvector cosine search on 384-dim embeddings: <5ms for 10k memories
EOF

cat > .mycelium/rooms/design-review/research/embeddings.md << 'EOF'
---
key: research/embeddings
created_by: selina-agent
version: 1
---
sentence-transformers/all-MiniLM-L6-v2 runs locally, 384 dimensions, no API key needed
EOF
```

### Agent 3: Kappa reports what didn't work

```bash
mycelium memory set decisions/no-sqlite-tests "SQLite can't handle pgvector or JSONB — need real Postgres for integration tests" --handle kappa-agent
mycelium memory set decisions/no-qdrant "Considered Qdrant but AgensGraph+pgvector eliminates the need" --handle kappa-agent
```

### Agent 4: Prometheus shares status

```bash
mycelium memory set status/cfn-integration "Working on CFN integration — mapping mycelium agents to CFN objects" --handle prometheus-agent
mycelium memory set context/blocker "Need ioc-cfn-mgmt-plane-svc running to test agent registration flow" --handle prometheus-agent
```

### Browse & Search

```bash
ls .mycelium/rooms/design-review/decisions/
# api-style.md  database.md  llm-provider.md  no-qdrant.md  no-sqlite-tests.md

grep -r "AgensGraph" .mycelium/rooms/design-review/
# decisions/database.md:Consolidated to single AgensGraph instance...
# decisions/no-qdrant.md:...AgensGraph+pgvector eliminates the need

# Or use the CLI for structured views:
mycelium memory decisions     # Why choices were made
mycelium memory status        # Current state of things
mycelium memory context       # Background & constraints

# Read with cat or with the CLI:
cat .mycelium/rooms/design-review/decisions/database.md
mycelium memory get decisions/database

# Semantic search (uses pgvector index):
mycelium memory search "what database decisions were made"
mycelium memory search "what failed"

# Re-index after direct file writes (updates pgvector search index):
# POST /rooms/design-review/reindex

# Synthesize — now structure-aware, groups by category
mycelium synthesize

# Catchup — new agent arrives, gets briefed
mycelium catchup
```

### Watch in real-time

Open a second terminal:
```bash
mycelium watch design-review
```

Then write memories from the first terminal — they appear live in the watch output.

Also show `http://localhost:3000/room/design-review` in the browser for the UI view.

### Git-based sharing

```bash
# Initialize git in the room:
cd .mycelium/rooms/design-review && git init && git add -A && git commit -m "initial room state"

# Agent A pushes findings:
git push origin main

# Agent B on another machine picks up context:
git pull
mycelium catchup
```

---

## Part 2: Sync Negotiation (CognitiveEngine)

### Two Claude Code agents negotiate

**Terminal 1 (or Claude Code instance 1) — julia-agent:**

```bash
mycelium room create friday-demo
mycelium room use friday-demo
mycelium session create
mycelium session join --handle julia-agent --message "Prioritize CFN integration — need mgmt plane wired up before Friday demo"
mycelium session await --handle julia-agent
```

**Terminal 2 (or Claude Code instance 2) — selina-agent:**

```bash
mycelium room use friday-demo
mycelium session join --handle selina-agent --message "Focus on demo UX — frontend polish, watch output, catchup display. Backend is solid enough."
mycelium session await --handle selina-agent
```

**Terminal 3 (audience view):**
```bash
mycelium watch friday-demo
```

Or open `http://localhost:3000/room/friday-demo` in the browser.

### What happens

1. Both agents join → 60s join timer starts
2. Timer fires → CognitiveEngine runs SemanticNegotiationPipeline
3. `await` returns a tick with `action: propose` → agent proposes:
   ```bash
   mycelium negotiate propose budget=high timeline=standard scope=extended quality=standard --handle julia-agent
   ```
4. Other agent gets a tick with `action: respond` → accepts or rejects:
   ```bash
   mycelium negotiate respond accept --handle selina-agent
   ```
5. `await` returns `type: consensus` with the final plan

### Prompt for the other Claude Code agent

Give this to the second Claude Code instance:

> You are participating in a Mycelium coordination room called `friday-demo`. You are `selina-agent`. Your position is: "We should focus on demo UX and frontend polish before Friday — the backend is solid enough."
>
> ```bash
> mycelium room use friday-demo
> mycelium session join --handle selina-agent --message "Focus on demo UX — frontend polish, watch output, catchup display."
> mycelium session await --handle selina-agent
> ```
>
> When you get a tick, respond based on the action:
> - `action=propose` → `mycelium negotiate propose budget=medium timeline=express scope=standard quality=premium --handle selina-agent`
> - `action=respond` → evaluate the offer, then `mycelium negotiate respond accept --handle selina-agent`
> - `type=consensus` → done, read your assignment
>
> Keep calling `mycelium session await --handle selina-agent` between each response until you get consensus.

---

## Part 3: The Story (for the presentation)

### Talking points

1. **The problem**: Agents today are semantically isolated. No shared intent, no shared context, no ratchet effect.

2. **IoC three pillars realized**:
   - Cognition State Protocols → CognitiveEngine + NegMAS semantic negotiation
   - Cognition Fabric → Persistent memory + pgvector search index
   - Cognition Engines → CognitiveEngine synthesis + guardrails

4. **The ratchet effect**: Show `mycelium catchup`. A new agent arrives and instantly knows everything the swarm learned. Intelligence compounds across sessions. Synthesis is structure-aware — groups memories by category (work, decisions, status, context) for better briefings.

5. **Negative results matter**: Show `mycelium memory decisions`. Agents log what didn't work (and why) so others don't repeat dead ends. The structured category convention (`decisions/no-qdrant`) makes failures as discoverable as successes.

6. **CFN integration**: Agent registration → CFN mgmt plane. ioc-cognitive-fabric-node-svc routes extraction + evidence back to mycelium-backend. Mycelium serves as both the knowledge-memory and cognition engine backends.

### Key URLs during demo

- Frontend: `http://localhost:3000`
- Room viewer: `http://localhost:3000/room/design-review`
- Presentation deck: `docs/mycelium-dataflow.html`
- Backend API docs: `http://localhost:8888/docs`
