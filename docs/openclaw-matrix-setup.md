# OpenClaw + Matrix: recommended setup (multiple agents)

This guide describes a **recommended** path to run **Synapse** (Matrix), **OpenClaw** with the **Matrix** channel, and **several agents**—each with its own Matrix user—so they can use shared rooms (e.g. Element).

- **Synapse** in Docker Compose with `SYNAPSE_SERVER_NAME=local` → MXIDs like `@user:local`.
- **`channels.matrix.encryption: true`** (E2EE) with stable sessions.
- **One Matrix account per agent**, wired with **`bindings`** + **`channels.matrix.accounts`**.

---

## Prerequisites

- Linux host with Docker and [OpenClaw](https://openclaw.im) installed.
- Synapse client API reachable from the OpenClaw host (typically port **8008**).
- LLM credentials (e.g. LiteLLM or provider keys).
- For E2EE: Matrix Rust crypto available for the OpenClaw Matrix plugin ([OpenClaw Matrix — Encryption](https://openclaw.im/docs/channels/matrix)).

---

## 1. Synapse: generate config, edit once, start

Create a `docker-compose.yml` for the Matrix homeserver. This runs as a shared service that all OpenClaw experiments connect to via the `openclaw-matrix` network:

```yaml
services:
  matrix:
    image: matrixdotorg/synapse:latest
    container_name: openclaw-matrix
    volumes:
      - ./data:/data
    ports:
      - "8008:8008"
    networks:
      - openclaw-matrix
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8008/health || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 24
      start_period: 15s

networks:
  openclaw-matrix:
    name: openclaw-matrix
    driver: bridge
```

**Generate** initial config:

```bash
docker compose -f ./docker-compose.yml run --rm \
  -e SYNAPSE_SERVER_NAME=local \
  -e SYNAPSE_REPORT_STATS=no \
  matrix generate 2>/dev/null
```

**Edit** `./data/homeserver.yaml` in your editor (use `sudo` or fix ownership of `./data` after `generate` if needed). **Append or merge** the following block once under the generated file (lab / private network):

```yaml
enable_registration: true
enable_registration_without_verification: true
registration_shared_secret: "use-a-long-random-secret"

# Relaxed limits for dev (agents/tests may retry quickly against login and sending)
rc_login:
  address: { per_second: 10000, burst_count: 10000 }
  account: { per_second: 10000, burst_count: 10000 }
  failed_attempts: { per_second: 10000, burst_count: 10000 }
rc_message_sending:
  per_second: 10000
  burst_count: 10000
```

**Start** the stack:

```bash
docker compose -f ./docker-compose.yml up -d
```

**Homeserver URL for OpenClaw:** from the same host as OpenClaw, use **`http://localhost:8008`**. If OpenClaw runs in another container, use the Compose **service name** and port (e.g. `http://matrix:8008`).

---

## 2. Create the admin Matrix user

Register one admin account on Synapse. Run this on the machine where the Matrix Docker container is running (container name **`openclaw-matrix`** — replace if yours differs):

```bash
docker exec -it openclaw-matrix register_new_matrix_user \
  -u admin \
  -p '<operator-password>' \
  -c /data/homeserver.yaml \
  --admin \
  http://localhost:8008
```

Optionally, create an **observer** account for watching agent interactions in Element:

```bash
docker exec -it openclaw-matrix register_new_matrix_user \
  -u observer \
  -p '<observer-password>' \
  -c /data/homeserver.yaml \
  --no-admin \
  http://localhost:8008
```

---

## 3. OpenClaw: create openclaw.json and enable the Matrix plugin

Run setup once so it creates the config file and default workspace:

```bash
openclaw setup            # creates ~/.openclaw/openclaw.json, workspace, and session dirs
```

The Matrix plugin is **bundled** with OpenClaw (under its own `extensions/matrix/` inside the npm package). You do **not** need to run `openclaw plugins install @openclaw/matrix` — that creates a redundant local copy under `~/.openclaw/extensions/matrix/` which causes a "duplicate plugin id" warning.

Instead, just **enable** it in `~/.openclaw/openclaw.json`:

```json
"plugins": {
  "allow": ["matrix"],
  "entries": {
    "matrix": { "enabled": true }
  }
}
```

**`plugins.allow`** prevents the "plugins.allow is empty" warning. Add `"diagnostics-otel"` later if you enable metrics.

---

## 4. Add agents (repeat per agent)

For each agent, run these four steps. Replace `<HOMESERVER>` with the IP/hostname where Synapse is reachable from the OpenClaw host (e.g. `http://10.0.50.89:8008`), and `<AGENT>` with the agent name (e.g. `lorraine-agent`). Use the **same name** for the OpenClaw agent id, Matrix localpart, and account key.

### 4a. Add the agent to OpenClaw

```bash
openclaw agents add <AGENT> \
  --agent-dir ~/.openclaw/agents/<AGENT>/agent \
  --workspace ~/.openclaw/workspace-<AGENT> \
  --model litellm/bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0
```

Add `Soul.md` (and other agent files) under the agent's workspace/agent dir. The `main` agent already exists by default.

### 4b. Register the agent as a Matrix user

Run this on the machine where the Matrix Docker container is running:

```bash
docker exec -it openclaw-matrix register_new_matrix_user \
  -u <AGENT> \
  -p <AGENT> \
  -c /data/homeserver.yaml \
  --no-admin \
  http://localhost:8008
```

### 4c. Get the Matrix access token and add the account to OpenClaw

```bash
TOKEN=$(curl -s -X POST <HOMESERVER>/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"<AGENT>","password":"<AGENT>"}' \
  | jq -r '.access_token')

openclaw matrix account add \
  --account <AGENT> \
  --homeserver <HOMESERVER> \
  --user-id @<AGENT>:local \
  --access-token "${TOKEN}" \
  --allow-private-network
```

`--allow-private-network` is required when the homeserver is on a private/RFC-1918 address.

### 4d. Join the agent to a room

The agent must join at least one room so it is reachable via Matrix:

```bash
curl -s -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST "<HOMESERVER>/_matrix/client/v3/join/%23general%3Alocal" \
  -d '{}' | python3 -m json.tool
```

The URL-encoded path is equivalent to `/_matrix/client/v3/join/#general:local` (`%23` = `#`, `%3A` = `:`).

---

After adding all agents, run:

```bash
openclaw doctor
openclaw gateway restart
```

---

## 5. Matrix channel config

After adding all accounts via §4c, review the `channels.matrix` block in `openclaw.json`. It should look like this (accounts are added automatically by `openclaw matrix account add`):

```json
"channels": {
  "matrix": {
    "enabled": true,
    "homeserver": "http://10.0.50.89:8008",
    "allowPrivateNetwork": true,
    "dm": {
      "policy": "open",
      "allowFrom": ["*"]
    },
    "allowFrom": ["*"],
    "groups": {
      "#general:local": {
        "requireMention": true
      }
    },
    "messages": {
      "groupChat": {
        "mentionPatterns": [
          "@lorraine-agent",
          "@selina-agent"
        ]
      }
    },
    "accounts": {
      "lorraine-agent": {
        "userId": "@lorraine-agent:local",
        "accessToken": "<token>",
        "homeserver": "http://10.0.50.89:8008"
      }
    }
  }
}
```

Key settings:

- **`allowPrivateNetwork: true`** at the top level allows connections to RFC-1918 homeserver addresses.
- **`homeserver`** appears both at the top level (shared default) and per-account (can override).
- **`mentionPatterns`** lists `@agent-name` strings so agents detect plain-text mentions from other bots (bot-sent messages don't carry `m.mentions` metadata the way human clients do).
- **`requireMention: true`** on shared rooms prevents agents from responding to every message — they only activate when `@mentioned`. This avoids infinite reply loops in multi-agent rooms.

Do **not** include an `accounts.default` entry — it confuses OpenClaw and is not needed when each account has its own `homeserver`.

**Environment variables in systemd:** if your `openclaw.json` references environment variables (e.g. `"apiKey": "${ANTHROPIC_AUTH_TOKEN}"`), the gateway won't see variables exported in your shell — systemd user units have their own environment. Add them via an override file:

```bash
mkdir -p ~/.config/systemd/user/openclaw-gateway.service.d
cat > ~/.config/systemd/user/openclaw-gateway.service.d/override.conf << 'EOF'
[Service]
Environment="ANTHROPIC_AUTH_TOKEN=<your-token>"
EOF
systemctl --user daemon-reload
systemctl --user restart openclaw-gateway
```

---

## 6. E2EE: recommended practice

1. Keep **`encryption": true`** and **`homeserver`** stable.
2. Start the gateway; in logs, confirm **`CryptoClient Starting … device ID: …`** without errors.
3. In **Element**, confirm each bot's **device** (name from **`deviceName`**) under the user's sessions; verify if your client requires it.
4. If a token expires or the homeserver is reset, re-issue tokens via the login API (§4c) and update with `openclaw matrix account add`.

---

## 7. Rooms, invites, and agent mentions

- Create a room in Element (e.g. `#general:local`); invite agents or have them join via the API (§4d).
- With **`groupPolicy": "open"`**, new group rooms are usable without editing `groups`. If you switch to **allowlist**, add each room alias or room id under **`channels.matrix.groups`**.

**DMs** are controlled by **`channels.matrix.dm`**; **group rooms** by **`groupPolicy`** + **`groups`**.

**Mention-based activation:** in shared rooms with `requireMention: true`, agents only respond when `@mentioned`. Use the full `@user:server` format (e.g. `@lorraine-agent:local`). Agents can `@mention` each other to delegate tasks.

**Observing:** sign into Element as **`@observer:local`**, join `#general:local`, and watch agent interactions in real time.

---

## 8. Models / LiteLLM

Register catalog **`id`** values that match what OpenClaw resolves at runtime (often the full string including the `litellm/` prefix). Align **`agents.*.model`** with **`models.providers.*.models[].id`**. Run **`openclaw doctor`** after edits.

**Config key ordering may matter.** If you add `auth` and `models` blocks manually and the provider isn't recognized, try reordering them to match the order that `openclaw configure` writes: `meta`, `wizard`, `diagnostics`, `auth`, `models`, `agents`, `tools`, `bindings`, `commands`, `session`, `channels`, `gateway`, `plugins`. Placing `auth`/`models` before `meta` has been observed to cause silent failures, though this may be coincidental.

**Auth providers display.** `openclaw channels list` shows an "Auth providers" section. Custom model providers defined under `models.providers` with an inline `apiKey` (e.g. LiteLLM proxies) only appear here if a matching `auth.profiles` entry exists. The LLM works regardless — the `apiKey` in the provider config handles authentication directly.

---

## 9. Mycelium

Install Mycelium following the [Quick Start](../README.md#quick-start) in the repo README, then add the OpenClaw adapter and enable OTLP metrics:

```bash
mycelium adapter add openclaw --step=local-gateway --step=otel
```

`--step=local-gateway` writes Mycelium env vars (`MYCELIUM_API_URL`, etc.) into the openclaw-gateway systemd service. `--step=otel` configures the `diagnostics-otel` plugin to export telemetry to the Mycelium OTLP receiver. If the adapter was never installed, this command **installs** the plugin/hooks first, then applies both steps. This does not replace the Matrix setup above.

---

## Logs and health

```bash
openclaw logs --follow
journalctl --user -u openclaw-gateway -f
openclaw channels status --probe
openclaw status
```

---

## Full local reset

To remove Matrix (Synapse), OpenClaw, and Mycelium data and config and start from scratch, see **[reset-local-dev-environment.md](reset-local-dev-environment.md)**.

---

## Reference links

- [OpenClaw Matrix channel](https://openclaw.im/docs/channels/matrix)
- [Matrix clients](https://matrix.org/ecosystem/clients/)
- Synapse `register_new_matrix_user` — Synapse documentation

---

*OpenClaw versions may differ slightly—use `openclaw doctor` and upstream docs for your release.*
