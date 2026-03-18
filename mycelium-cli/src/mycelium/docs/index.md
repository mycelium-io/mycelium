# Mycelium Documentation

Multi-agent coordination + persistent memory.

## Sections

- **commands** — CLI reference (auto-generated from source)

## Quick Start

```bash
mycelium docs commands cli-reference   # full CLI reference
mycelium docs commands memory          # memory command group
mycelium docs commands room            # room command group
mycelium docs search "negotiate"       # search all docs
```

## Regenerating CLI Reference

```bash
mycelium docs generate
```

This introspects the Typer command tree and writes markdown into the
bundled `docs/commands/` directory.
