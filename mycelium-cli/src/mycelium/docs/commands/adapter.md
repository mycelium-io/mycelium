# mycelium adapter

Connect agent frameworks (OpenClaw, Claude Code) to Mycelium. Install hooks, skills, and plugins.

## Commands

### `mycelium adapter add`

Register and install an agent framework adapter, then optionally wire it into your environment.

Examples:
    mycelium adapter add openclaw
    mycelium adapter add openclaw --reinstall
    mycelium adapter add openclaw --step=local-gateway
    mycelium adapter add openclaw --step=docker-env

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `adapter_type` | argument | Yes |  | Adapter type: openclaw, cursor, claude-code |
| `--dry-run` | option |  | `False` | Show what would be installed without doing it |
| `--step` | option |  |  | Run a follow-up setup step: local-gateway, docker-env |
| `--reinstall` | option |  | `False` | Reinstall assets even if adapter is already registered |
| `--scaffold-only` | option |  |  | Copy adapter assets to a directory without running install commands (for Docker/experiment setups) |
| `--force`, `-f` | option |  | `False` | Overwrite existing assets when using --scaffold-only |

### `mycelium adapter ls`

List registered adapters.

### `mycelium adapter remove`

Unregister and uninstall an adapter.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `adapter_type` | argument | Yes |  | Adapter type to remove |
| `--force`, `-f` | option |  | `False` | Skip confirmation |

### `mycelium adapter status`

Check adapter health.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `adapter_type` | argument |  |  | Adapter type to check (all if omitted) |
