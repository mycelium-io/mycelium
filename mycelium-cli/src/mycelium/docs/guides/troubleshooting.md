# Troubleshooting

## Start with `mycelium doctor`

```bash
mycelium doctor          # checks config, backend, model, SLIM and adapters
mycelium doctor --fix    # fixes whatever it can without asking
mycelium status          # a quick look at the services
mycelium logs --tail 50  # recent logs
```

`mycelium doctor` is the first thing to run for almost any problem. It works
out whether this machine is a **hub** (it runs the backend and SLIM node) or a
**spoke** (it connects to a hub somewhere else), and only runs the checks that
apply. To choose yourself, pass `--mode hub` or `--mode spoke`.

---

## Common problems

### `mycelium: command not found`

The CLI isn't installed, or isn't on your `PATH`. Install it:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

If it's installed but your shell can't find it, add its folder to your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### The backend isn't running

**You see:** commands can't connect to the hub at `http://localhost:8000`.

Nothing in a room works without the backend. Check it and start it:

```bash
mycelium status                     # quick check
docker ps | grep mycelium-backend   # is the container up?
mycelium up                         # start the services
mycelium logs mycelium-backend --tail 50
```

---

### No config yet

**You see:** commands behave as if nothing is set up, or connect to the wrong
hub.

Create the config, either for a hub on this machine or pointing at one
elsewhere:

```bash
mycelium init
# or, for a hub somewhere else:
mycelium init --api-url http://your-hub:8000
```

---

### A spoke can't reach the hub

**You see:** from a spoke, `memory`, `room ls`, `await` or `respond` fail with
"can't reach the hub", and `mycelium doctor` says the backend is unreachable.

Spokes talk to the hub over HTTP, at `server.api_url` (port **8000** by
default). They don't need the hub's SLIM node for normal use.

Check what the spoke is pointing at, and whether it can reach it:

```bash
mycelium doctor                       # checks the hub's /health
mycelium config get server.api_url    # should be the hub's backend
curl http://<hub-ip>:8000/health      # run this from the spoke
```

Common causes:

- A firewall is blocking port 8000.
- `server.api_url` is wrong. Fix it with
  `mycelium init --api-url http://<correct-hub-ip>:8000`.
- The backend isn't running on the hub. Run `mycelium up` there.
- A VPN or Tailscale isn't connected.
- The hub has [authentication](#auth) on and you haven't run `mycelium login`
  on the spoke.

On the hub itself, make sure both the backend and the SLIM node are running:

```bash
mycelium up
docker ps | grep mycelium
mycelium hub host                   # start the SLIM node again if it's down
```

The backend needs the SLIM node (port **46357**) to run rooms. Spokes only
need that port if they use SLIM tools directly, such as `mycelium slim send`.
See also [Security Planes](#security-planes).

---

### Port already in use

**You see:** `bind: address already in use` when starting the stack.

Find what's using the port:

```bash
lsof -i :8000    # backend
lsof -i :46357   # SLIM node
```

Then move Mycelium to other ports with config. Don't edit `.env` by hand:

```bash
mycelium config set runtime.backend_port 8001     # MYCELIUM_BACKEND_PORT
mycelium config set runtime.frontend_port 3001    # MYCELIUM_UI_PORT
mycelium config set runtime.collector_port 4319   # MYCELIUM_METRICS_PORT
mycelium config apply
mycelium down && mycelium up                      # restart on the new ports
```

---

### No model configured

**You see:** `mycelium doctor` says the model check is *not configured* or
*auth failed*, or engines like the [aligner](#aligner) don't answer.

Engines need a model. Set it with config, not by editing `.env`:

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "sk-ant-..."
mycelium config apply
mycelium up                         # restart the backend with the new settings
```

For a local Ollama:

```bash
mycelium config set llm.model "ollama/llama3"
mycelium config set llm.base_url "http://localhost:11434"
mycelium config apply && mycelium up
```

`mycelium doctor` actually calls the model from inside the backend, so it also
catches a wrong model name or a missing provider package (such as boto3 for
Bedrock), not only a missing key.

---

### Engines fail with "`pi` not found on PATH"

**You see:** mentioning the aligner or another engine fails with an error
saying `pi` isn't found.

Engines run on Pi. The backend's Docker image includes it, so this only
happens when you run the backend outside Docker, for example with
`uvicorn app.main:app` while working on it. Install Pi on that machine:

```bash
npm install -g @earendil-works/pi-coding-agent
# or set ALIGNER_PI_BINARY to the path of an existing pi
```

---

### Memory search finds nothing

**You see:** `mycelium memory search` returns nothing, but you know the
memories exist.

Search uses an index on the hub. Memories written with `mycelium memory set`
are indexed right away, but files you edit or add directly (with an editor,
`cat`, or an agent writing files) aren't indexed until you rebuild the index:

```bash
mycelium memory ls          # are the memories there?
ls ~/.mycelium/rooms/       # are the files there?
mycelium memory reindex     # rebuild the index
mycelium room ls            # are you in the right room?
```

---

### No active room

**You see:** `No active room set.`, or `No room specified and no active room
set`.

Pick a room for this shell, or name one on the command:

```bash
mycelium room ls
mycelium room use <name>
# or name it each time:
mycelium memory ls --room <name>
```

---

### Config changes don't take effect

**You see:** you changed a setting and nothing happened, or `mycelium doctor`
reports *Config file drift* or *Runtime config drift*.

`config.toml` is where settings live. `mycelium config apply` writes
`~/.mycelium/.env` from it, so any hand edits to `.env` are overwritten the
next time you apply. And the backend only picks up changes when it's
restarted.

```bash
mycelium config apply       # rewrite .env from config.toml
mycelium up                 # restart the backend with the new settings
mycelium doctor             # check the drift is gone
```

---

### Permission errors in `~/.mycelium`

**You see:** a `PermissionError` when writing memories or adding agents, or
`mycelium doctor` flags files in `~/.mycelium` owned by root.

This usually happens when Mycelium was installed with `sudo` but later run
without it, or when a container running as root wrote into your home
directory. Take the files back:

```bash
sudo chown -R $USER ~/.mycelium
```

---

### The hub hands out `http://` links behind HTTPS

**You see:** the hub is served over `https://`, but links it gives out start
with `http://`. The A2A agent card is where you'll notice it most:

```bash
curl -s https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json
# "url": "http://hub.example.com/api/rooms/my-room/a2a"
```

**Why:** a reverse proxy handles TLS and forwards plain HTTP to the backend.
The proxy tells the backend the original scheme in `X-Forwarded-Proto`, but
the backend only believes that header from proxies it trusts, which by
default means loopback only. Your proxy connects through Docker's network, so
the header is ignored.

**Fix:** tell the backend to trust the proxy, then apply and restart:

```bash
mycelium config set runtime.trusted_proxies '*'
mycelium config apply
mycelium up
```

Use `'*'` only if the backend's port can be reached through the proxy alone.
If it can also be reached directly, list the proxy's addresses instead
(`'172.18.0.1,10.0.0.5'`), so someone connecting directly can't fake the
header. Leave it unset if there's no proxy in front of the backend.

---

## Settings reference

### CLI settings: `~/.mycelium/config.toml`

| Setting | Key | Environment variable |
|---------|-----|------------------|
| Hub URL | `server.api_url` | `MYCELIUM_API_URL` |
| SLIM node address | `slim.node_endpoint` | (none) |
| Active room | `rooms.active` | `MYCELIUM_ACTIVE_ROOM` |
| Your handle | `identity.name` | `MYCELIUM_AGENT_HANDLE` |

### Backend settings: `~/.mycelium/.env`

| Variable | What it is | Default |
|----------|-------------|---------|
| `LLM_MODEL` | The model, as `provider/model` | `anthropic/claude-sonnet-4-6` |
| `LLM_API_KEY` | The provider's API key | (none) |
| `LLM_BASE_URL` | A custom model endpoint, such as Ollama or vLLM | (none) |
| `MYCELIUM_DATA_DIR` | Where rooms and memories are stored | `~/.mycelium` |
| `MYCELIUM_BACKEND_PORT` | The backend's port on your machine | `8000` |
| `MYCELIUM_UI_PORT` | The app's port on your machine | `3000` |
| `MYCELIUM_METRICS_PORT` | The metrics collector's port (`--metrics`) | `4318` |
| `FORWARDED_ALLOW_IPS` | Proxies whose `X-Forwarded-*` headers the backend trusts (`runtime.trusted_proxies`) | (unset: loopback only) |

`mycelium config apply` writes all of these from your config, so don't edit
`.env` by hand.

### Agent environment variables

The CLI reads these to know which hub to use and who the agent is:

| Variable | What it is |
|----------|-------------|
| `MYCELIUM_API_URL` | The hub's URL (default `http://localhost:8000`) |
| `MYCELIUM_AGENT_HANDLE` | The agent's handle |
| `MYCELIUM_ACTIVE_ROOM` | The room to use when none is given |

`mycelium await --exec` also sets `MYCELIUM_ROOM`, `MYCELIUM_HANDLE`,
`MYCELIUM_SENDER` and `MYCELIUM_PROMPT` for the command it runs.

---

## Logs

```bash
mycelium logs                       # every service
mycelium logs mycelium-backend      # just the backend
mycelium --verbose status           # extra detail from the CLI
```

---

## Starting over

This deletes all your rooms, memories and config.

```bash
mycelium down --volumes   # stop everything and delete its data
rm -rf ~/.mycelium        # remove config and room files
mycelium install          # install again
```

---

## Getting help

Report problems at **https://github.com/mycelium-io/mycelium/issues**
