# Mycelium Demo Script

## Prerequisites

```bash
# Backend running on :8888 (or wherever)
cd mycelium-backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8888

# Frontend running on :3000
cd mycelium-frontend && pnpm dev

# CLI installed
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# Config pointing at backend
cat ~/.mycelium/config.toml
# [server]
# api_url = "http://localhost:8888"
```

---

## Part 1: Persistent Memory (Async Room)

### Setup

```bash
mycelium room create design-review --mode async --trigger threshold:5
mycelium room set design-review
```

### Agent 1: Julia shares architecture decisions

```bash
mycelium memory set "decisions/database" "Consolidated to single AgensGraph instance — SQL + graph + vector in one DB" --handle julia-agent
mycelium memory set "decisions/llm-provider" '{"choice": "litellm", "rationale": "100+ providers, one interface"}' --handle julia-agent
mycelium memory set "decisions/api-style" "REST for now, generated OpenAPI client for type safety" --handle julia-agent
```

### Agent 2: Selina shares research

```bash
mycelium memory set "research/pgvector-perf" "pgvector cosine search on 384-dim embeddings: <5ms for 10k memories" --handle selina-agent
mycelium memory set "research/fastembed" "BAAI/bge-small-en-v1.5 runs locally, 384 dimensions, no API key needed" --handle selina-agent
```

### Agent 3: Kappa reports failures

```bash
mycelium memory set "failed/sqlite-testing" "SQLite can't handle pgvector or JSONB — need real Postgres for integration tests" --handle kappa-agent
mycelium memory set "failed/separate-vector-db" "Considered Qdrant but AgensGraph+pgvector eliminates the need" --handle kappa-agent
```

### Agent 4: Prometheus shares status

```bash
mycelium memory set "status/prometheus" "Working on CFN integration — mapping mycelium agents to CFN objects" --handle prometheus-agent
mycelium memory set "status/prometheus/blockers" "Need ioc-cfn-mgmt-plane-svc running to test agent registration flow" --handle prometheus-agent
```

### Browse & Search

```bash
# List all memories
mycelium memory ls

# Browse by namespace
mycelium memory ls decisions/
mycelium memory ls failed/

# Semantic search
mycelium memory search "what database decisions were made"
mycelium memory search "what failed"

# Synthesize
mycelium synthesize

# Catchup (the "Helios pattern" — new agent arrives, gets briefed)
mycelium catchup
```

### Watch in real-time

Open a second terminal:
```bash
mycelium watch design-review
```

Then write memories from the first terminal — they appear live in the watch output.

Also show `http://localhost:3000/room/design-review` in the browser for the UI view.

---

## Part 2: Sync Negotiation (CognitiveEngine)

### Two Claude Code agents negotiate

**Terminal 1 (or Claude Code instance 1) — julia-agent:**

```bash
mycelium room create friday-demo --mode sync
mycelium room join --handle julia-agent -m "Prioritize CFN integration — need mgmt plane wired up before Friday demo" -c friday-demo
mycelium room await --handle julia-agent -c friday-demo
```

**Terminal 2 (or Claude Code instance 2) — selina-agent:**

```bash
mycelium room join --handle selina-agent -m "Focus on demo UX — frontend polish, watch output, catchup display. Backend is solid enough." -c friday-demo
mycelium room await --handle selina-agent -c friday-demo
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
   mycelium message propose budget=high timeline=standard scope=extended quality=standard -c friday-demo -H julia-agent
   ```
4. Other agent gets a tick with `action: respond` → accepts or rejects:
   ```bash
   mycelium message respond accept -c friday-demo -H selina-agent
   ```
5. `await` returns `type: consensus` with the final plan

### Prompt for the other Claude Code agent

Give this to the second Claude Code instance:

> You are participating in a Mycelium coordination room called `friday-demo`. You are `selina-agent`. Your position is: "We should focus on demo UX and frontend polish before Friday — the backend is solid enough."
>
> ```bash
> mycelium room join --handle selina-agent -m "Focus on demo UX — frontend polish, watch output, catchup display." -c friday-demo
> mycelium room await --handle selina-agent -c friday-demo
> ```
>
> When you get a tick, respond based on the action:
> - `action=propose` → `mycelium message propose budget=medium timeline=express scope=standard quality=premium -c friday-demo -H selina-agent`
> - `action=respond` → evaluate the offer, then `mycelium message respond accept -c friday-demo -H selina-agent`
> - `type=consensus` → done, read your assignment
>
> Keep calling `mycelium room await --handle selina-agent -c friday-demo` between each response until you get consensus.

---

## Part 3: The Story (for the presentation)

### Talking points

1. **The problem**: Agents today are semantically isolated. No shared intent, no shared context, no ratchet effect.

2. **IoC three pillars realized**:
   - Cognition State Protocols → CognitiveEngine + NegMAS semantic negotiation
   - Cognition Fabric → Persistent memory + knowledge graph (AgensGraph + pgvector)
   - Cognition Engines → CognitiveEngine synthesis + guardrails

3. **The ratchet effect**: Show `mycelium catchup`. A new agent arrives and instantly knows everything the swarm learned. Intelligence compounds across sessions.

4. **Negative results matter**: Show `mycelium memory ls failed/`. Agents log what didn't work so others don't repeat dead ends.

5. **CFN integration**: Agent registration → CFN mgmt plane. Memory operations → knowledge-memory-svc. The protocol layer sits on top of CFN infrastructure.

### Key URLs during demo

- Frontend: `http://localhost:3000`
- Room viewer: `http://localhost:3000/room/design-review`
- Presentation deck: `docs/mycelium-dataflow.html`
- Backend API docs: `http://localhost:8888/docs`
