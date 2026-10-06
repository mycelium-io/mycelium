---
name: troubleshooting
description: Diagnose and fix common Mycelium installation and runtime issues. Use when encountering errors with mycelium commands, backend connectivity, Docker containers, LLM configuration, or memory operations. Triggers on "not working", "error", "failed", "cannot connect", "troubleshoot", "debug", "fix".
---

# Mycelium Troubleshooting

Diagnose and fix common installation and runtime issues.

## Quick Diagnostics

Run `mycelium status --json` for machine-readable health data, or `mycelium status` for human-readable output. This checks the backend, the LLM, embedding, Docker, disk, and the data directory.

## Common Issues

### 1. Command Not Found

**Symptom**: `mycelium: command not found`

**Fix**: Reinstall via one of these methods:

```bash
# curl (on an Apple silicon Mac this installs Mycelium for Mac and links its CLI;
# add `bash -s -- --client-only` for the CLI alone)
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash

# brew
brew install mycelium-io/tap/mycelium
```

Or via clawhub — tell your agent:
> "install https://clawhub.ai/juliarvalenti/mycelium-io"

Verify: `which mycelium` should show `~/.local/bin/mycelium`

If the binary exists but isn't found, add to PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 2. Backend Not Running

**Symptom**: `Cannot connect to Mycelium API at http://localhost:8000`

**Diagnosis**:
```bash
mycelium status          # quick check
docker ps | grep mycelium   # container status
```

**Fixes**:
- Start services: `mycelium up`
- Check logs: `mycelium logs mycelium-backend --tail 50`
- Rebuild: `mycelium up --build`

If the Mac app runs the hub (`~/.mycelium/desktop.json` exists), there are no
containers: open the app, run `mycelium doctor --mode desktop`, and read
`~/.mycelium/logs/desktop.log`.

### 3. Config Not Found

**Symptom**: `Configuration file not found: ~/.mycelium/config.toml`

**Fix**:
```bash
mycelium init
```

Or with custom API URL:
```bash
mycelium init --api-url http://your-server:8000
```

### 4. Container Name Conflicts

**Symptom**: `container name "mycelium-backend" is already in use`

**Fix**: The CLI handles this automatically, but if it persists:
```bash
docker rm -f mycelium-slim mycelium-backend mycelium-frontend
mycelium up
```

### 5. Port Already in Use

**Symptom**: `bind: address already in use`

**Diagnosis**:
```bash
lsof -i :8000   # backend port
lsof -i :46357  # SLIM node port
```

**Fixes**:
- Kill conflicting process
- Or use alternate ports in `~/.mycelium/.env`:
  ```
  MYCELIUM_BACKEND_PORT=8001
  MYCELIUM_DB_PORT=5433
  ```

### 6. LLM Not Configured

**Symptom**: `LLM unavailable — no API key configured`

**Fix**: Add to `~/.mycelium/.env`:
```bash
LLM_MODEL=anthropic/claude-sonnet-4-6
LLM_API_KEY=sk-ant-...
```

Or for local Ollama:
```bash
LLM_MODEL=ollama/llama3
LLM_BASE_URL=http://localhost:11434
```

Restart backend after changes: `mycelium down && mycelium up`

### 7. Memory Search Returns Nothing

**Symptom**: `mycelium memory search` returns empty despite memories existing

**Diagnosis**:
```bash
mycelium memory ls   # do memories exist?
ls ~/.mycelium/rooms/   # files present?
```

**Fixes**:
- Memories written directly (cat, editor) need reindex:
  ```bash
  mycelium memory reindex
  ```
- Check active room: `mycelium room ls` — wrong room selected?

### 8. No Active Room

**Symptom**: `No active room. Use 'mycelium room use <name>'`

**Fixes**:
```bash
mycelium room ls           # list available rooms
mycelium room use my-project   # set active room
```

Or pass room explicitly:
```bash
mycelium memory ls --room my-project
```

### 9. Docker Not Installed/Running

**Symptom**: `Docker not installed` or `Cannot connect to Docker daemon`

**Fixes**:
- Install Docker: https://docs.docker.com/get-docker/
- Start daemon: `sudo systemctl start docker`
- Add user to docker group: `sudo usermod -aG docker $USER` (logout/login required)

### 10. Image Pull Failures

**Symptom**: `manifest unknown` or `unauthorized`

**Fixes**:
- Login to ghcr: `docker login ghcr.io`
- Pull explicitly: `docker pull ghcr.io/mycelium-io/mycelium-backend:latest`
- Build from source: `mycelium up --build`

### 11. Agent Behaving Strangely / "Why did it do that?"

**Symptom**: An agent took an unexpected action, replied with the wrong context, called the wrong tool, or burned a lot of tokens. `mycelium metrics show` rolls everything up into headline numbers but doesn't show *why* a specific turn behaved that way.

**Fix**: Drill into the actual span tree with `mycelium metrics traces`:

```bash
# 1. Find the recent spans for the agent
mycelium metrics traces list --agent=claire-agent --since=15m

# 2. Pick a trace_id from the output and render it as a tree.
#    Each row shows model, tokens, tool name, exit code, and any
#    error message, so you can see exactly which step went wrong.
mycelium metrics traces show <trace_id>

# 3. Want every attribute the OTel pipeline captured? (system prompt
#    chars, context window size, channel, trigger, etc.)
mycelium metrics traces show-attrs <span_id>
```

Other useful pivots when an agent looks off:

```bash
# What models is it actually calling?
mycelium metrics traces by-model --agent=claire-agent --since=1h

# Which rooms / channels has it been active in?
mycelium metrics traces by-room --agent=claire-agent --since=1h
mycelium metrics traces by-channel --agent=claire-agent --since=1h

# Tool call patterns (which tools, how often, error rate)
mycelium metrics traces by-tool --agent=claire-agent --since=1h

# Slowest turns (e.g. context assembly blowing up)
mycelium metrics traces slow --agent=claire-agent --since=1h

# Just the failures
mycelium metrics traces errors --agent=claire-agent --since=1h
```

If `mycelium metrics traces ...` reports `traces.db not found`, the OTLP
receiver isn't running on the hub — see issue #16.

## Configuration

Mycelium has two config systems: **config.toml** for CLI settings and **.env** for backend/Docker settings.

### CLI Settings (config.toml)

Stored in `~/.mycelium/config.toml` (global) and `./.mycelium/config.toml` (project-local).

| Setting | config.toml path | Env var override |
|---------|------------------|------------------|
| Backend URL | `server.api_url` | `MYCELIUM_API_URL` |
| Workspace ID | `server.workspace_id` | `MYCELIUM_WORKSPACE_ID` |
| MAS ID | `server.mas_id` | `MYCELIUM_MAS_ID` |
| Active room | `rooms.active` | `MYCELIUM_ACTIVE_ROOM` |
| Agent handle | `identity.name` | `MYCELIUM_AGENT_HANDLE` |

**Priority** (highest to lowest): env var → project config.toml → global config.toml → defaults

### Backend Settings (.env)

Stored in `~/.mycelium/.env`. Used by Docker Compose and the backend container.

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_MODEL` | Pi model string (provider/model) | `anthropic/claude-sonnet-4-6` |
| `LLM_API_KEY` | Provider API key | (required for cloud LLMs) |
| `LLM_BASE_URL` | Custom LLM endpoint | (for Ollama, vLLM) |
| `MYCELIUM_DATA_DIR` | Data directory | `~/.mycelium` |
| `MYCELIUM_BACKEND_PORT` | Backend port | `8000` |

### File Locations

| File | Purpose |
|------|---------|
| `~/.mycelium/config.toml` | CLI settings (identity, server URL) |
| `./.mycelium/config.toml` | Project settings (active room) |
| `~/.mycelium/.env` | Backend/Docker settings (LLM, ports), written by `mycelium config apply` |
| `~/.mycelium/rooms/{name}/` | Room memory files |

## Log Locations

```bash
mycelium logs                      # all services
mycelium logs mycelium-backend     # backend only
mycelium logs mycelium-slim        # the SLIM node only
docker logs mycelium-backend       # direct docker access
```

For CLI debug output:
```bash
mycelium --verbose status
```

## Reset Everything

When all else fails:
```bash
mycelium down --volumes   # stop and delete data
rm -rf ~/.mycelium        # remove all config
mycelium init             # fresh start
mycelium up
```

## Getting Help

1. Check `mycelium status` output
2. Review logs: `mycelium logs --tail 100`
3. Verify config: `cat ~/.mycelium/config.toml`
4. Check .env: `cat ~/.mycelium/.env`
