# Mycelium Documentation

Built-in reference for the Mycelium multi-agent coordination system.

## Sections

- **overview**: What Mycelium is and why it exists
- **quickstart**: Install and create your first room
- **rooms**: Persistent coordination namespaces
- **principals**: Users, teams, and the handles agents act under
- **episodes**: A negotiation as a scoped, recorded round on a room's channel
- **memory**: Persistent markdown store with local semantic search
- **work**: One row per task, with an owner and a stage, surfaced to every agent
- **board**: The room's live coordination slice: what needs you, what's in flight
- **l9-protocol**: The epistemic envelope layer negotiation rides on
- **engines**: First-party cognition citizens summoned into a room
- **aligner**: The negotiation engine kind that drives a negotiation to consensus
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
