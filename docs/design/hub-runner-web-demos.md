# Web-triggered demos via the host runner

## Why this exists

OpenClaw is the org's standard agent runtime, it's disallowed on personal PCs,
and the whole stack already runs on a shared EC2 hub. So the only way a PM can
see a coordination today is to SSH into a box they don't own and drive the
OpenClaw gateway CLI by hand. They won't.

This feature lets them click **"Run a sample coordination"** in the web GUI
instead — it provisions real agents on the hub and routes them straight into
the live room. No terminal, no SSH.

## Architecture

```
browser ──▶ mycelium-frontend (container) ──▶ mycelium-backend (container)
                                                   │  /api/demos  (env-gated proxy)
                                                   ▼
                                       mycelium hub serve  (HOST process)
                                                   │  reuses `mycelium demo`
                                                   ▼
                                       OpenClaw gateway  (HOST process)
```

The executor is a **host process**, not a container, because provisioning an
OpenClaw agent edits `~/.openclaw/openclaw.json` and runs `openclaw gateway
restart` — host-level operations a container can't perform without mounting the
host FS and baking in the CLIs (the coupling we're avoiding). The gateway
itself is a host process too, so the runner sits right next to it.

The backend side is a thin proxy that **404s unless `HUB_RUNNER_URL` is set**,
so end-user local installs get no new surface. The frontend hides every demo
affordance unless `/api/demos/scenarios` answers.

## One-time hub setup

Everything below runs **on the EC2 host** (where the gateway and the mycelium
CLI already live).

### 1. The runner

```bash
# Optional but recommended: a bearer token the backend must present.
export MYCELIUM_HUB_TOKEN="$(openssl rand -hex 16)"
# Lift GitHub's unauthenticated 60/hr API limit for the persona dataset.
export GITHUB_TOKEN="<a PAT with public-repo read>"

mycelium hub serve --port 8765        # binds 127.0.0.1:8765 by default
```

Keep it up with a unit (example systemd, user scope):

```ini
# ~/.config/systemd/user/mycelium-hub.service
[Unit]
Description=Mycelium hub runner
After=network.target

[Service]
Environment=MYCELIUM_HUB_TOKEN=...
Environment=GITHUB_TOKEN=...
ExecStart=%h/.local/bin/mycelium hub serve --port 8765
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now mycelium-hub
```

### 2. Point the backend at it

The backend container reaches the host process over the host gateway. Set in
the shell/`.env` the stack reads, then recreate the backend:

```bash
export HUB_RUNNER_URL="http://host.docker.internal:8765"
export HUB_RUNNER_TOKEN="$MYCELIUM_HUB_TOKEN"   # must match the runner
mycelium up   # or: docker compose ... up -d --force-recreate mycelium-backend
```

`compose.yml` already gives the backend `extra_hosts: host.docker.internal:
host-gateway`, so this resolves on Linux EC2. If you run the backend with host
networking instead, use `http://127.0.0.1:8765`.

### 3. The seed agent (don't skip this)

Fresh OpenClaw agents are created with an **empty `auth-profiles.json`** — no
model token — so their turns hang silently. `mycelium demo` clones credentials
from an already-authenticated agent. The hub needs **one** such agent:

```bash
openclaw models auth        # authenticate a single agent on the gateway
```

After that, every web-spawned demo agent clones it automatically. Without a
seed agent the room comes up but the agents never speak.

## Verify

```bash
curl -s http://127.0.0.1:8765/health                      # on the host
curl -s -H "Authorization: Bearer $HUB_RUNNER_TOKEN" \
     http://127.0.0.1:8765/scenarios                      # lists scenarios
# From a browser: the dashboard now shows "Run a sample coordination".
```

## Security

- **`MYCELIUM_HUB_TOKEN`** gates the runner; **`HUB_RUNNER_TOKEN`** must match
  on the backend. Set both — a runner with no token will provision agents for
  anyone who can reach the port.
- Bind the runner to localhost (default). Never expose `:8765` publicly.
- A web button that spawns LLM agents is spend + RCE surface. The hub GUI must
  sit behind the org's SSO/nginx before it's reachable by PMs. **TODO:** confirm
  the Outshift SSO front door for the hub.
- Per-agent budget caps live on the agent manifest (daemon-enforced for
  cold-spawn adapters); set sane demo defaults before opening this up widely.

## Limitations / next

- One demo provisions at a time (the runner serializes gateway-mutating work).
- Job state is in-memory — a runner restart drops history, not live agents.
- The agents-panel "+add" can become a real **"add an agent on the hub"** action
  on top of the same runner; demos are just the first consumer.
