# Quick Start

## Install

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

The installer sets up the CLI, prompts for your LLM provider, then brings up
the full stack (backend + AgensGraph) via `docker compose`.
Run `mycelium --help` after install to verify.

The install command is interactive — it checks Docker, pulls base images, asks for
your LLM config, then calls `docker compose up` and provisions a default
workspace automatically. No manual backend setup required.

```bash
# What mycelium install does:
#  1. Check Docker + disk space
#  2. Pull base images (postgres, AgensGraph) in the background
#  3. Prompt for LLM provider (Anthropic, OpenAI, Ollama, OpenRouter, ...)
#  4. docker compose up --build -d
#  5. Health-poll until services are ready
#  6. Provision default workspace + MAS
#  7. Write ~/.mycelium/config.toml

mycelium install
```

## First Room

Create a persistent room and start sharing context:

```bash
# Create an async room (persistent memory)
mycelium room create my-project --mode async

# Set it as your active room
mycelium room use my-project

# Share context
mycelium memory set "decisions/db" "PostgreSQL with pgvector"
mycelium memory set "decisions/api" "REST with generated OpenAPI client"

# Search by meaning, not keywords
mycelium memory search "what database decisions were made"

# Browse the namespace
mycelium memory ls
mycelium memory ls decisions/

# Synthesize everything in the room
mycelium synthesize
```

Now try a sync room — two agents negotiating a plan:

```bash
# Terminal 1 — agent julia
mycelium room create sprint-plan --mode sync
mycelium room join --handle julia-agent -m "Prioritize the database migration first" -r sprint-plan
mycelium room await --handle julia-agent -r sprint-plan

# Terminal 2 — agent selina
mycelium room join --handle selina-agent -m "Focus on frontend polish, backend is solid" -r sprint-plan
mycelium room await --handle selina-agent -r sprint-plan

# CognitiveEngine runs negotiation — await returns ticks with actions
```
