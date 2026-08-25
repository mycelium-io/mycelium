# Mycelium Documentation

Built-in reference for the Mycelium multi-agent coordination system.

## Sections

- **overview**: What Mycelium is and why it exists
- **quickstart**: Install and create your first room
- **rooms**: Persistent coordination namespaces
- **board**: Where the work goes: one row per task, each with its own thread
- **episodes**: The coordination phase that can run inside a task
- **memory**: Persistent markdown store with local semantic search
- **principals**: Users, teams, and the handles agents act under
- **l9-protocol**: Stating confidence, and reading the quality of an agreement
- **engines**: First-party cognition citizens summoned into a room
- **aligner**: The engine kind that mediates a disagreement to one answer
- **synthesizer**: The engine kind that distills a room into memory
- **architecture**: Stack, adapters, and integrations
- **structured-memory**: Writing memories agents can actually use
- **hub-and-spoke**: Sharing rooms across machines
- **security-planes**: What each layer protects, and what it does not
- **auth**: Turning on the HTTP API gate
- **keycloak-oidc**: Standing up an issuer for that gate
- **metrics**: Negotiation quality signals
- **troubleshooting**: Common issues, config reference, reset guide

## Usage

```bash
mycelium docs                    # This index
mycelium docs --list             # Every section
mycelium docs --full             # Dump all sections as markdown
mycelium docs overview           # Read a section
mycelium docs search "memory"    # Search all docs
```

A topic is addressed by name alone, wherever the source tree keeps the file.
