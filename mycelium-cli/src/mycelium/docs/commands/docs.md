# mycelium docs

Browse and search built-in documentation for Mycelium concepts, protocols, and API reference.

## Commands

### `mycelium docs generate`

Auto-generate CLI reference docs from command definitions.

Introspects the Typer command tree and writes markdown files
into the bundled docs/commands/ directory (or a custom path).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--output`, `-o` | option |  |  | Output directory (default: bundled docs) |

### `mycelium docs ls`

List all available documentation.

### `mycelium docs search`

Search documentation for a term.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | argument | Yes |  | Search query |
