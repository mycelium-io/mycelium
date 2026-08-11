# Mycelium Documentation

Built-in reference for the Mycelium multi-agent coordination system.

## Sections

- **overview** — What Mycelium is and why it exists
- **quickstart** — Install and create your first room
- **rooms** — Persistent coordination namespaces
- **episodes** — A negotiation as a scoped, recorded round on a room's channel
- **memory** — Persistent markdown store with local semantic search
- **plan** — Title + markdown files + checklist tasks surfaced to every agent
- **aligner** — The mediator that drives a negotiation to consensus
- **l9-protocol** — The epistemic envelope layer negotiation rides on
- **cli-reference** — All CLI commands (generated from source)
- **architecture** — Stack, adapters, and integrations
- **troubleshooting** — Common issues, config reference, reset guide

## Usage

```bash
mycelium docs                    # This index
mycelium docs --full             # Dump all sections as markdown
mycelium docs overview           # Read a section
mycelium docs cli-reference      # CLI command reference
mycelium docs search "memory"    # Search all docs
```
