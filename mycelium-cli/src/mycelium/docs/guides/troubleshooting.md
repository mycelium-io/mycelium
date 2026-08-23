# Troubleshooting

## Quick Diagnostics

```bash
mycelium doctor          # full diagnostic: config, backend, LLM, SLIM, adapters
mycelium doctor --fix    # auto-fix everything it can
mycelium status          # quick service health (backend, LLM, disk)
mycelium logs --tail 50  # recent service logs
```

`mycelium doctor` is the first thing to run for almost any problem. It
auto-detects whether this machine is a **hub** (runs the backend + SLIM node
locally) or a **spoke** (points at a remote hub), and skips the checks that
don't apply. Force it with `--mode hub` or `--mode spoke`.

---

## Common Issues

### 1. Command Not Found

**Symptom**: `mycelium: command not found`

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

The backend is the room moderator; nothing coordinates without it.

```bash
mycelium status                     # quick check
docker ps | grep mycelium-backend   # container status
mycelium up                         # start services
mycelium logs mycelium-backend --tail 50
```

---

### 3. Config Not Found

**Symptom**: `Configuration file not found: ~/.mycelium/config.toml`

```bash
mycelium init
# or point at a remote hub:
mycelium init --api-url http://your-hub:8000
```

---

### 4. Spoke Can't Reach the Hub (or Backend Down)

**Symptom**: `Cannot connect to Mycelium API`; memory/`await`/`respond` fail;
`mycelium doctor` reports backend unreachable.

Spokes talk to the hub over **HTTP** (`server.api_url`, default port **8000**).
They do not need the SLIM node for normal participation.

```bash
mycelium doctor                     # detects hub vs spoke; checks /health
curl http://<hub-ip>:8000/health    # from the spoke
mycelium config get server.api_url    # should point at the hub backend
```

On the **hub**, ensure the backend and SLIM node are running:

```bash
mycelium up
docker ps | grep mycelium
mycelium hub host                   # (re)start the SLIM node if needed
```

If coordination still fails on the hub itself, check the SLIM node (port
**46357**) — the backend moderator needs it. Spokes rarely need `:46357`
unless you use native SLIM tooling (`mycelium slim send`).

Common causes: firewall blocks **8000**, wrong `server.api_url`, VPN not
connected, or auth enabled on the hub without `mycelium login` on the spoke.
See [Security Planes](#security-planes) and [Authentication](#auth).

---

### 5. Port Already in Use

**Symptom**: `bind: address already in use`

```bash
lsof -i :8000    # backend
lsof -i :46357   # SLIM node
```

Remap published host ports through config rather than hand-editing `.env`:

```bash
mycelium config set runtime.backend_port 8001     # MYCELIUM_BACKEND_PORT
mycelium config set runtime.frontend_port 3001    # MYCELIUM_UI_PORT
mycelium config set runtime.collector_port 4319   # MYCELIUM_METRICS_PORT
mycelium config apply
mycelium down && mycelium up                      # restart to pick up new ports
```

---

### 6. LLM Not Configured

**Symptom**: `LLM unavailable, no API key configured`, or `mycelium doctor`
reports the LLM connectivity check as *not configured* / *auth failed*.

The LLM powers the [aligner](#aligner) mediator and memory embedding-adjacent
work. Set it through config, not by hand-editing `.env`:

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "sk-ant-..."
mycelium config apply
mycelium up                         # recreate the backend with the new env
```

For local Ollama:

```bash
mycelium config set llm.model "ollama/llama3"
mycelium config set llm.base_url "http://localhost:11434"
mycelium config apply && mycelium up
```

`mycelium doctor` runs a real completion probe inside the backend, so it
catches missing provider SDKs (e.g. boto3 for Bedrock) and bad model strings,
not just a missing key.

---

### 7. Aligner Negotiation Fails ("pi not found")

**Symptom**: summoning the aligner (`mycelium engine invoke aligner ...`) fails
with `PiBrainError: pi not found`.

The aligner's mediator runs a NEGMAS negotiation whose brain is a **Pi**
coding-agent session. The released backend image already ships Pi, so the
normal `mycelium up` path needs nothing extra, and `mycelium doctor` reports this
check as satisfied when the backend is dockerized.

This only bites when you run the backend **outside Docker** (a contributor
doing `uvicorn app.main:app` on the host). There, put Pi on PATH:

```bash
npm install -g @mariozechner/pi-coding-agent
# or point ALIGNER_PI_BINARY at an existing pi install
```

---

### 8. Memory Search Returns Nothing

**Symptom**: `mycelium memory search` is empty despite memories existing.

Search runs against a **local embedding index** (no external service). Direct
file writes (cat, editor, agent file I/O) don't update it until you reindex.

```bash
mycelium memory ls          # do memories exist?
ls ~/.mycelium/rooms/       # files present?
mycelium reindex            # rebuild the index after direct file writes
mycelium room ls            # wrong active room?
```

---

### 9. No Active Room

**Symptom**: `No active room. Use 'mycelium room use <name>'`

```bash
mycelium room ls
mycelium room use <name>
# or pass room explicitly:
mycelium memory ls --room <name>
```

---

### 10. Config Drift (edited one file, not the other)

**Symptom**: config changes seem to have no effect; `mycelium doctor` flags
*Config file drift* or *Runtime config drift*.

`mycelium config apply` regenerates `~/.mycelium/.env` from `config.toml`, which
is the source of truth. If you hand-edit `.env`, the next `apply` overwrites it.
And if you change config but don't recreate the backend, it keeps running the
old env.

```bash
mycelium config apply       # rewrite .env from config.toml
mycelium up                 # recreate the backend with current env
mycelium doctor             # confirm drift cleared
```

---

### 11. Permission Errors Under ~/.mycelium

**Symptom**: opaque `PermissionError` on memory or agent writes; `mycelium
doctor` flags *~/.mycelium ownership* with root-owned files.

Usually a sudo install paired with a non-sudo agent add (or a containerized
gateway running as root bind-mounting your home). One `chown` fixes it:

```bash
sudo chown -R $USER ~/.mycelium
```

---

### 12. Spoke Cannot Reach Hub Backend

**Symptom**: `mycelium status` / `mycelium room ls` from a spoke returns a
connection error pointing at the hub's URL.

```bash
curl http://<hub-ip>:8000/health      # raw backend reachability
grep api_url ~/.mycelium/config.toml  # what the spoke targets
```

Common causes: firewall blocks port 8000, hub backend isn't running
(`mycelium up` on the hub), VPN/Tailscale not connected, or the wrong URL in
`config.toml`. Re-point if needed:

```bash
mycelium init --api-url http://<correct-hub-ip>:8000
```

Note the spoke must also reach the hub's **SLIM node** on 46357 (see *SLIM Node
Unreachable* above); the backend and the node are separate ports.

---

### 13. Hub Advertises `http://` URLs Behind HTTPS

**Symptom**: the hub is served over `https://`, but an absolute URL it hands out
comes back `http://`. Most visible on the A2A agent card:

```bash
curl -s https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json
# "url": "http://hub.example.com/api/rooms/my-room/a2a"
```

**Cause**: a TLS-terminating reverse proxy forwards plain HTTP to the backend
container, so the backend sees an `http` request. The proxy reports the original
scheme in `X-Forwarded-Proto`, but the backend believes that header only from a
forwarder it trusts, and by default it trusts loopback alone. The proxy connects
from the Docker bridge, so its header is ignored.

**Fix**: name the proxy, then re-render `.env` and recreate the stack.

```bash
mycelium config set runtime.trusted_proxies '*'
mycelium config apply
mycelium up
```

Use `'*'` when the backend port is reachable only through the proxy. If it is
also reachable directly, list the proxy addresses instead
(`'172.18.0.1,10.0.0.5'`) so a direct caller cannot spoof the scheme. Leave it
unset when nothing fronts the backend.

---

## Configuration Reference

### CLI settings: `~/.mycelium/config.toml`

| Setting | Key | Env var override |
|---------|-----|------------------|
| Backend URL | `server.api_url` | `MYCELIUM_API_URL` |
| SLIM node endpoint | `slim.node_endpoint` | (none) |
| Active room | `rooms.active` | `MYCELIUM_ACTIVE_ROOM` |
| Agent handle | `identity.name` | `MYCELIUM_AGENT_HANDLE` |

### Backend settings: `~/.mycelium/.env`

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_MODEL` | `provider/model` string, as Pi takes it | `anthropic/claude-sonnet-4-6` |
| `LLM_API_KEY` | Provider API key | (none) |
| `LLM_BASE_URL` | Custom LLM endpoint (Ollama, vLLM) | (none) |
| `MYCELIUM_DATA_DIR` | Data directory | `~/.mycelium` |
| `MYCELIUM_BACKEND_PORT` | Backend API host port | `8000` |
| `MYCELIUM_UI_PORT` | Frontend host port | `3000` |
| `MYCELIUM_METRICS_PORT` | OTLP collector host port (`--metrics`) | `4318` |
| `FORWARDED_ALLOW_IPS` | Forwarders whose `X-Forwarded-*` headers the backend honours (`runtime.trusted_proxies`) | (unset: loopback only) |

All of these are written by `mycelium config apply` from the matching
`runtime.*` config keys, so don't edit `.env` by hand.

### Agent environment variables

Read by the CLI and adapters at runtime to identify the agent and locate the backend:

| Variable | Description |
|----------|-------------|
| `MYCELIUM_API_URL` | Backend API URL (default: `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE` | This agent's identity handle |
| `MYCELIUM_ROOM` | Active room name |

---

## Log Locations

```bash
mycelium logs                       # all services
mycelium logs mycelium-backend      # backend only
mycelium --verbose status           # CLI debug output
```

---

## Reset Everything

```bash
mycelium down --volumes   # stop and delete all data
rm -rf ~/.mycelium        # remove all config and room files
mycelium install          # fresh install
```

---

## Getting Help

Report issues at **https://github.com/mycelium-io/mycelium/issues**
