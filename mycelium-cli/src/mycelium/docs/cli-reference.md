# CLI Reference

Auto-generated from CLI source. Run `mycelium docs generate` to regenerate.

## Global Options

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--version`, `-V` | option |  |  | Print version information |
| `--verbose`, `-v` | option |  | `False` | Enable verbose/debug output |
| `--quiet`, `-q` | option |  | `False` | Suppress non-essential output |
| `--json` | option |  | `False` | Output in JSON format |

## Top-Level Commands

### `mycelium catchup`

Get briefed on a room's current state — latest synthesis + recent activity.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--room`, `-r` | option |  |  | Room name |

### `mycelium down`

Stop Mycelium services.

Examples:
    mycelium down             # stop containers, keep volumes
    mycelium down --volumes   # stop and delete all data

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--volumes`, `-v` | option |  | `False` | Also remove volumes (destructive) |

### `mycelium init`

Initialize Mycelium configuration.

Creates ~/.mycelium/config.toml with default settings.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--api-url` | option |  |  | Backend API URL (default: http://localhost:8000) |
| `--force`, `-f` | option |  | `False` | Overwrite existing configuration |

### `mycelium install`

Install an Mycelium instance.

Checks system requirements, prompts for configuration, then brings up
all services via docker compose.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--ascii` | option |  | `False` | Use ASCII rendering |
| `--blocks` | option |  | `False` | Use unicode block rendering |
| `--color` | option |  | `cyan` | Color theme (cyan|amber|magenta|green|white) |
| `--yes`, `-y` | option |  | `False` | Skip confirmations |
| `--non-interactive`, `-n` | option |  | `False` | Skip prompts and animation (use --llm-model etc.) |
| `--llm-model` | option |  | `` | LLM model in litellm format (non-interactive) |
| `--llm-base-url` | option |  | `` | LLM base URL (non-interactive) |
| `--llm-api-key` | option |  | `` | LLM API key (non-interactive) |
| `--ioc` | option |  | `False` | Enable IoC CFN stack (non-interactive) |

### `mycelium logs`

View service logs via docker compose.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `service` | argument |  |  | Service name (e.g. mycelium-backend, ioc-cfn-mgmt-plane-svc) |
| `--follow`, `-f` | option |  | `False` | Follow log output |
| `--tail` | option |  |  | Number of lines to show from the end |

### `mycelium status`

Show service health.

Checks if Mycelium backend is running and accessible.

### `mycelium synthesize`

Trigger CognitiveEngine synthesis for an async/hybrid room.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `room_name` | argument |  |  | Room to synthesize (default: active room) |
| `--room`, `-r` | option |  |  | Room name (alternative to positional arg) |

### `mycelium up`

Start Mycelium services.

Runs docker compose up -d using the bundled compose file and
~/.mycelium/.env for configuration.

Examples:
    mycelium up          # start all services
    mycelium up --build  # rebuild images first

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--build` | option |  | `False` | Rebuild images before starting |

### `mycelium watch`

Stream live messages from a room.

Auto-resolves the active room — no argument needed.
Renders coordination events, agent joins, ticks, and consensus.

Examples:
    mycelium room watch
    mycelium room watch my-room
    mycelium room watch --timeout 120

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `room_name` | argument |  |  | Room to watch (default: active room) |
| `--timeout`, `-t` | option |  | `0` | Timeout in seconds (0=no timeout) |

## Command Groups

- [`mycelium adapter`](commands/adapter.md) — Connect agent frameworks (OpenClaw, Claude Code) to Mycelium. Install hooks, skills, and plugins.
- [`mycelium config`](commands/config.md) — View and update Mycelium settings. Global config lives at ~/.mycelium/config.toml.
- [`mycelium docs`](commands/docs.md) — Browse and search built-in documentation for Mycelium concepts, protocols, and API reference.
- [`mycelium memory`](commands/memory.md) — Read and write persistent memories scoped to rooms. Memories persist across sessions and support semantic vector search.
- [`mycelium message`](commands/message.md) — Respond to CognitiveEngine during sync negotiation. Propose offers, accept/reject, or send raw JSON.
- [`mycelium room`](commands/room.md) — Shared namespaces for agent coordination. Rooms can be sync (real-time negotiation), async (persistent memory), or hybrid.
