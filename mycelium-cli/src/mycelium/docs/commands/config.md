# mycelium config

View and update Mycelium settings. Global config lives at ~/.mycelium/config.toml.

## Commands

### `mycelium config get`

Get a configuration value.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | argument | Yes |  | Config key (e.g., server.api_url) |

### `mycelium config set`

Set a configuration value or switch environment.

Examples:
    mycelium config set server.api_url http://myhost:8000
    mycelium config set --env local

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | argument |  |  | Config key (e.g., server.api_url) |
| `value` | argument |  |  | Config value |
| `--env`, `-e` | option |  |  | Apply environment preset (local) |

### `mycelium config show`

Show current configuration.
