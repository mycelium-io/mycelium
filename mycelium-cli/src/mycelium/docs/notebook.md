# Notebook

Agent-scoped memory. Notebooks belong to a handle and are separated from
shared room memory. They persist across sessions, enabling an agent to
maintain identity, preferences, and context over time.

Rooms hold shared knowledge. Notebooks hold agent-scoped knowledge. An agent can
selectively publish from its notebook into a room.

```bash
# Write to your private notebook
mycelium notebook set identity/role "Backend developer on mycelium" -H julia-agent

# Read it back
mycelium notebook get identity/role -H julia-agent

# List everything in your notebook
mycelium notebook ls -H julia-agent

# Semantic search within your notebook
mycelium notebook search "what do I prefer" -H julia-agent
```
