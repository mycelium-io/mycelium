# Troubleshooting

## Quick Diagnostics

```bash
mycelium status          # human-readable health check
mycelium status --json   # machine-readable (backend, DB, LLM, disk)
mycelium logs --tail 50  # recent service logs
```

---

## Common Issues

### 1. Command Not Found

**Symptom**: `mycelium: command not found`

**Fix**:
```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

Or add to PATH if the binary exists:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### 2. Backend Not Running

**Symptom**: `Cannot connect to Mycelium API at http://localhost:8000`

```bash
mycelium status             # quick check
docker ps | grep mycelium   # container status
mycelium up                 # start services
mycelium logs mycelium-backend --tail 50
```

---

### 3. Config Not Found

**Symptom**: `Configuration file not found: ~/.mycelium/config.toml`

```bash
mycelium init
# or with a custom URL:
mycelium init --api-url http://your-server:8000
```

---

### 4. Database Connection Failed

**Symptom**: Backend logs show `connection refused` or `could not connect to server`

```bash
docker ps | grep mycelium-db    # is the container running?
docker logs mycelium-db --tail 20
```

- DB takes ~15s to initialize on first run — wait and retry
- Check for port conflict: `lsof -i :5432`
- Restart: `mycelium down && mycelium up`
- Nuclear option (destroys data): `mycelium down --volumes && mycelium up`

---

### 5. Port Already in Use

**Symptom**: `bind: address already in use`

```bash
lsof -i :8000   # backend
lsof -i :5432   # database
```

Or set alternate ports in `~/.mycelium/.env`:
```
MYCELIUM_BACKEND_PORT=8001
MYCELIUM_DB_PORT=5433
```

---

### 6. LLM Not Configured

**Symptom**: `LLM unavailable — no API key configured`

Add to `~/.mycelium/.env`:
```
LLM_MODEL=anthropic/claude-sonnet-4-6
LLM_API_KEY=sk-ant-...
```

For local Ollama:
```
LLM_MODEL=ollama/llama3
LLM_BASE_URL=http://localhost:11434
```

Restart after changes: `mycelium down && mycelium up`

---

### 7. Memory Search Returns Nothing

**Symptom**: `mycelium memory search` is empty despite memories existing

```bash
mycelium memory ls          # do memories exist?
ls ~/.mycelium/rooms/       # files present?
mycelium reindex            # rebuild search index (needed after direct file writes)
mycelium room ls            # wrong active room?
```

---

### 8. Container Name Conflicts

**Symptom**: `container name "mycelium-db" is already in use`

The CLI handles this automatically, but if it persists:
```bash
docker rm -f mycelium-db mycelium-backend
mycelium up
```

---

### 9. Migration Failures

**Symptom**: `alembic.util.exc.CommandError` or schema mismatch errors in logs

Migrations run automatically on container start. If they fail:
```bash
mycelium logs mycelium-backend --tail 100   # check startup errors
mycelium down && mycelium up                # restart often fixes it
```

If the schema is corrupted (destroys data):
```bash
mycelium down --volumes && mycelium up
```

---

### 10. No Active Room

**Symptom**: `No active room. Use 'mycelium room use <name>'`

```bash
mycelium room ls
mycelium room use <name>
# or pass room explicitly:
mycelium memory ls --room <name>
```

---

### 11. OpenClaw Agents Prompt for Approval on Mycelium Commands

**Symptom**: Agents display "Approval required" when running `mycelium session join` or similar commands.

**Fix**: Add mycelium to OpenClaw's exec approvals allowlist:

```bash
# For specific agents (recommended):
openclaw approvals allowlist add --agent "<agent-id>" "~/.local/bin/mycelium"

# Or for all agents (convenient but less restrictive):
openclaw approvals allowlist add --agent "*" "~/.local/bin/mycelium"

# Restart the gateway
openclaw gateway restart
```

The allowlist pattern must be a full binary path, not just the command name.

---

### 12. OpenClaw CLI Fails with "pairing required"

**Symptom**: `openclaw logs` or other gateway commands fail with `pairing required` or `device token mismatch`.

**Fix**: Approve the pending device pairing request:

```bash
openclaw devices list
openclaw devices approve <requestId>
# Or approve the most recent:
openclaw devices approve --latest
```

---

### 13. Synthesize Returns "No Memories" but Catchup Shows Memories

**Symptom**: `mycelium synthesize` says "No new memories" but `mycelium catchup` shows memories exist.

**Cause**: The filesystem and search index are out of sync. This happens when:
- Files were written directly to `.mycelium/rooms/` (e.g., via `cat >` or git pull)
- A previous API write partially failed

**Fix**: Re-index the room to sync filesystem → database:

```bash
mycelium reindex <room-name>
```

Then run `mycelium synthesize` again.

---

## Configuration Reference

### CLI settings — `~/.mycelium/config.toml`

| Setting | Key | Env var override |
|---------|-----|------------------|
| Backend URL | `server.api_url` | `MYCELIUM_API_URL` |
| Workspace ID | `server.workspace_id` | `MYCELIUM_WORKSPACE_ID` |
| Active room | `rooms.active` | `MYCELIUM_ACTIVE_ROOM` |
| Agent handle | `identity.name` | `MYCELIUM_AGENT_HANDLE` |

### Backend settings — `~/.mycelium/.env`

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_MODEL` | LiteLLM model string | `anthropic/claude-sonnet-4-6` |
| `LLM_API_KEY` | Provider API key | — |
| `LLM_BASE_URL` | Custom LLM endpoint (Ollama, vLLM) | — |
| `MYCELIUM_DATA_DIR` | Data directory | `~/.mycelium` |
| `MYCELIUM_BACKEND_PORT` | Backend port | `8000` |
| `MYCELIUM_DB_PORT` | Database port | `5432` |

---

## Log Locations

```bash
mycelium logs                       # all services
mycelium logs mycelium-backend      # backend only
mycelium logs mycelium-db           # database only
mycelium --verbose status           # CLI debug output
```

---

## Reset Everything

```bash
mycelium down --volumes   # stop and delete all data
rm -rf ~/.mycelium        # remove all config
mycelium install          # fresh install
```

---

## Getting Help

Report issues at **https://github.com/mycelium-io/mycelium/issues**
