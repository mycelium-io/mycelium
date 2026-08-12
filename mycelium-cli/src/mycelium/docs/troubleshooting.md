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

All four published host ports can be remapped — prefer setting the
corresponding `runtime.*` config key and re-running `mycelium config
apply` (which materialises `~/.mycelium/.env`) rather than hand-editing
the env file:

```bash
mycelium config set runtime.backend_port 8001     # MYCELIUM_BACKEND_PORT
mycelium config set runtime.frontend_port 3001    # MYCELIUM_UI_PORT
mycelium config set runtime.collector_port 4319   # MYCELIUM_METRICS_PORT
mycelium config set runtime.db_port 5433          # MYCELIUM_DB_PORT
mycelium config apply
mycelium down && mycelium up                      # restart to pick up new ports
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

### 7b. Agents Join a Session but Never Reach Consensus

**Symptom**: `session join` works and agents appear in the session, but
negotiation never produces a plan, or `session join` reports
`CFN: not configured`.

Negotiation has two prerequisites that memory/rooms don't:

```bash
mycelium status            # is an LLM key configured? (CE needs one to propose)
grep -i ioc ~/.mycelium/.env   # was the stack installed with IoC/CFN enabled?
```

- **No LLM key** → the CognitiveEngine can't generate proposals. Add one (see
  *LLM Not Configured* above) and restart: `mycelium down && mycelium up`.
- **IoC/CFN disabled** → re-run `mycelium install` (interactive enables IoC by
  default), or reinstall without `--no-ioc`.

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

### 13. OpenClaw Adapter Fails on Containerized Gateway

**Symptom**: `mycelium adapter add openclaw --openclaw-container <name>` fails with
`No running container matched "<name>" under podman or docker`, even though
`docker exec <name> openclaw status` works fine.

**Cause**: Mycelium routes install commands through `docker exec` to avoid OpenClaw's
`--container` flag, which uses `docker inspect` for container-name resolution. If you
see this error, you may be running an older version of the CLI that still uses
`openclaw --container`.

**Fix**: Upgrade to the latest Mycelium CLI:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

Verify the container is reachable:

```bash
# Get the exact container name
docker ps --format "{{.Names}}" | grep -i openclaw

# Verify connectivity
docker exec <container-name> openclaw status

# Install with container flag
mycelium adapter add openclaw --openclaw-container <container-name>
```

You can also set `OPENCLAW_CONTAINER` as an environment variable instead of passing
`--openclaw-container` every time.

---

### 14. Agents Join Sessions but Never Respond (Expired Channel Tokens)

**Symptom**: An agent appears in `mycelium room ls` as a session
participant, but never responds to coordination ticks. No error in
`mycelium logs`.

**Cause**: The agent's channel access token has expired or been
invalidated (e.g., after a server restart). The OpenClaw gateway
silently drops the channel sync connection without surfacing an error to
Mycelium.

**Diagnosis**:

```bash
# Check gateway logs for channel sync errors
journalctl --user -u openclaw-gateway --since "10 min ago" | grep -i "sync\|401\|unauthorized"

# Or on the hub
openclaw logs | grep -i "sync\|401\|unauthorized"
```

**Fix**: Re-authenticate the agent with the channel server and update
the token in `~/.openclaw/openclaw.json` under the corresponding
`channels.<channel>.accounts.<agent>` section. Then restart the gateway:

```bash
openclaw gateway restart
```

In a hub-and-spoke setup, update tokens on every node that runs agents.

---

### 15. Orphaned Local Room Directories

**Symptom**: `mycelium doctor` reports `Orphaned rooms — X local room
directories not registered in the backend`, or the spoke daemon logs:

```
room 'my-room' not registered in the backend — orphaned local directory
at ~/.mycelium/rooms/my-room/ (run 'mycelium room gc' ...)
```

**Cause**: The room was deleted from the backend while the spoke daemon was
offline and missed the `room_deleted` SSE tombstone.  The local directory and
daemon subscription remain.

**Diagnosis**:

```bash
mycelium doctor          # shows the Orphaned rooms check result
mycelium room gc         # list orphans without removing anything
```

**Fix**:

```bash
# Remove orphaned directories and unregister adapter configs:
mycelium room gc --prune-orphans

# Or enable automatic cleanup on every daemon startup:
mycelium config set daemon.auto_gc_orphaned_rooms true
mycelium config apply
mycelium daemon restart
```

The daemon reconciles on every startup: if it can reach the backend it will
detect orphans and either warn or auto-remove them (depending on the
`auto_gc_orphaned_rooms` setting).  No manual intervention needed once that
setting is enabled.

---

### 16. Spoke Cannot Reach Hub Backend

**Symptom**: `mycelium status` or `mycelium room ls` from a spoke returns
a connection error pointing at the hub's URL.

**Diagnosis**:

```bash
# Test raw connectivity
curl http://<hub-ip>:8000/health

# Check what the spoke is configured to use
grep api_url ~/.mycelium/config.toml
```

**Common causes**:

- Firewall or security group blocks port 8000
- Hub backend isn't running (`mycelium up` on the hub)
- VPN/Tailscale not connected
- Wrong IP or port in `config.toml`

**Fix**: Ensure the hub is running and the spoke can reach it, then
re-initialise if the URL is wrong:

```bash
mycelium init --api-url http://<correct-hub-ip>:8000
```

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
| `MYCELIUM_BACKEND_PORT` | Backend API host port | `8000` |
| `MYCELIUM_UI_PORT` | Frontend host port (`--ui`) | `3000` |
| `MYCELIUM_METRICS_PORT` | OTLP collector host port (`--metrics`) | `4318` |
| `MYCELIUM_DB_PORT` | Database host port | `5432` |

All of these are written by `mycelium config apply` from the matching
`runtime.*` config keys — don't edit `.env` by hand.

### Agent environment variables

Read by the CLI and adapters at runtime to identify the agent and locate the backend:

| Variable | Description |
|----------|-------------|
| `MYCELIUM_API_URL` | Backend API URL (default: `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE` | This agent's identity handle |
| `MYCELIUM_ROOM` | Active room name |
| `MYCELIUM_WORKSPACE_ID` | CFN workspace UUID, required for knowledge ingest |
| `MYCELIUM_MAS_ID` | CFN MAS UUID, required for knowledge ingest |

### Knowledge-ingest cost controls

Overrides for `[knowledge_ingest]` in `~/.mycelium/config.toml`. Every key below
has a matching env var for ephemeral changes (no config edit needed). Forwarding
to the CFN graph is off by default.

| Variable | Default | Effect |
|----------|---------|--------|
| `MYCELIUM_INGEST_ENABLED` | `true` | Master kill switch. `0`/`false` short-circuits every ingest at the backend gate (no concept extraction, no CFN spend) and the endpoint returns 200 with a disabled marker. |
| `MYCELIUM_INGEST_MIN_CONTENT_CHARS` | `32` | Skip ingest for trivially short content ("ack", emoji-only). `0` disables the gate. |
| `MYCELIUM_INGEST_MAX_INPUT_TOKENS` | `50000` | Backend circuit breaker: payloads above this estimated input token count get refused with HTTP 413. `0` disables. |
| `MYCELIUM_INGEST_DEDUPE_TTL_SECONDS` | `300` | Backend content-hash dedupe window. Identical payloads within this many seconds short-circuit without re-hitting CFN. `0` disables dedupe. |

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
