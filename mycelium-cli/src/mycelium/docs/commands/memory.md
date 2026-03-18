# mycelium memory

Read and write persistent memories scoped to rooms. Memories persist across sessions and support semantic vector search.

## Commands

### `mycelium memory catchup`

Get briefed on a room's current state — latest synthesis + recent activity.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `--room`, `-r` | option |  |  | Room name |

### `mycelium memory get`

Read a memory by key.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | argument | Yes |  | Memory key |
| `--room`, `-r` | option |  |  | Room name |

### `mycelium memory ls`

List memories in a room, optionally filtered by namespace prefix.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `namespace` | argument |  |  | Key prefix to filter by (e.g. 'position/' or 'decisions/') |
| `--room`, `-r` | option |  |  | Room name |
| `--prefix`, `-p` | option |  |  | Key prefix filter (same as positional arg) |
| `--limit`, `-n` | option |  | `20` | Max results |

### `mycelium memory rm`

Delete a memory.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | argument | Yes |  | Memory key to delete |
| `--room`, `-r` | option |  |  | Room name |
| `--force`, `-f` | option |  | `False` | Skip confirmation |

### `mycelium memory search`

Semantic search over memories.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | argument | Yes |  | Natural language search query |
| `--room`, `-r` | option |  |  | Room name |
| `--limit`, `-n` | option |  | `5` | Max results |

### `mycelium memory set`

Write a memory to a room's persistent namespace.

Fails if the key already exists unless --update is passed.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | argument | Yes |  | Memory key (e.g. 'project/status') |
| `value` | argument | Yes |  | Memory value (string or JSON) |
| `--room`, `-r` | option |  |  | Room name (defaults to active room) |
| `--handle`, `-h` | option |  | `cli-user` | Agent handle |
| `--no-embed` | option |  | `False` | Skip vector embedding |
| `--tags`, `-t` | option |  |  | Comma-separated tags |
| `--update`, `-u` | option |  | `False` | Allow overwriting an existing memory |

### `mycelium memory subscribe`

Subscribe to memory change notifications.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | argument | Yes |  | Key glob pattern (e.g. 'project/*') |
| `--room`, `-r` | option |  |  | Room name |
| `--handle`, `-h` | option |  | `cli-user` | Subscriber agent handle |
