# Hub & Spoke Setup — Hermes

How to add one or more [Hermes](https://github.com/NousResearch/hermes-agent) spokes to a Mycelium hub, so each operator's machine runs its own Hermes agent and they all coordinate through a single backend.

> **Adapter-specific.** This guide assumes you've already worked through the
> generic [Hub & Spoke Setup](#hub-and-spoke) — hub provisioning, open
> ports, VPN/firewall posture, agent-identity rules, doctor checks, and
> spoke-metrics are identical across adapters. This page covers only what
> changes when the spoke runs `hermes-gateway` instead of
> `openclaw-gateway`.

## When this fits

Hermes hub-and-spoke is a clean fit when:

- Each spoke is one operator's machine — `julia@oclw3`, `selina@oclw5` —
  and each one wants their own agent identity in shared rooms.
- You want every operator's Hermes agent reachable from the same Matrix
  DM / Slack thread / Discord channel they already use, with the
  Mycelium room as the parallel coordination surface.
- You're not yet ready to host multiple personas inside a single
  `hermes-gateway` (see the [post-#25660 note](#hub-and-spoke-hermes-multi-agent-roadmap) below).

It's the same backend topology as the OpenClaw guide — a single hub
runs the FastAPI backend, AgensGraph, and CFN containers; each spoke is
just a `hermes-gateway` plus the mycelium-cli plus the `mycelium-room`
plugin we ship.

## Topology

```
┌──────────────────────────────────┐
│  Hub  (one machine)              │
│                                  │
│  mycelium install                │
│  ├─ FastAPI backend  :8000       │
│  ├─ AgensGraph (PG)  :5432       │
│  ├─ CFN mgmt plane   :9000       │
│  └─ CFN runtime      :9002       │
└────────────┬─────────────────────┘
             │  HTTP / SSE (backend_url)
     ┌───────┴───────┐
     │               │
┌────┴──────────┐  ┌─┴────────────┐
│ Spoke A       │  │ Spoke B      │
│ hermes-gateway│  │ hermes-gateway│
│ + mycelium-cli│  │ + mycelium-cli│
│ + mycelium    │  │ + mycelium    │
│   plugin      │  │   plugin      │
│ (1 agent)     │  │ (1 agent)     │
└───────────────┘  └──────────────┘
```

Two things to notice vs the OpenClaw topology:

1. **No central channel-server step.** Hermes spokes don't share a
   Matrix/Synapse instance on the hub. Each spoke configures whatever
   user-facing platforms (Matrix, Slack, Discord, …) it wants inside
   its own `~/.hermes/config.yaml` — those run alongside the
   `mycelium-room` platform, not through it.
2. **One Hermes agent per spoke, today.** A `hermes-gateway` process
   runs a single default agent. The "one operator = one machine = one
   agent" mapping is the natural unit; multi-agent gateways are tracked
   in the [roadmap](#hub-and-spoke-hermes-multi-agent-roadmap) below.

## Step 1: Set up the hub

Identical to the [generic hub setup](#hub-and-spoke-step-1-set-up-the-hub).
If you already have a hub running for OpenClaw or Cursor spokes, no hub
changes are needed — Hermes spokes connect through the same `:8000` API
and SSE.

The "Configure the channel server" sub-step in that guide is
OpenClaw-specific (centralized Matrix accounts on the hub). For Hermes,
skip it.

## Step 2: Install Hermes on the spoke

On each spoke, install `hermes-agent` directly (Mycelium does not
package it — we wire into whatever Hermes you already run). Follow the
[Hermes install instructions](https://github.com/NousResearch/hermes-agent#install).
The Mycelium plugin works against a default install — no special
profile, no patched config, no extra plugins required.

Verify the gateway starts:

```bash
hermes gateway status
```

Two prerequisites the Mycelium adapter does **not** set for you,
because they're host-policy decisions:

- **A working `model:` block in `~/.hermes/config.yaml`.** The Mycelium
  plugin dispatches through Hermes's own LLM client, so the model the
  operator has working in Hermes is automatically the model Mycelium
  dispatches through. A brand-new Hermes install ships with no model
  configured — add `model.{default, provider, base_url, api_key}` per
  the [Hermes config docs](https://github.com/NousResearch/hermes-agent#configuration)
  before continuing, or the first agent dispatch will fail with an
  auth error.
- **`GATEWAY_ALLOW_ALL_USERS=true` in `~/.hermes/.env`** (or a more
  targeted Hermes user allowlist). Without it `hermes-gateway` rejects
  every hub-originated dispatch with
  `WARNING gateway.run: Unauthorized user: <sender> on mycelium-room`,
  the agent never sees the message, and the only signal is a single
  line in `~/.hermes/logs/errors.log`. The setting opens the gateway
  to *any* sender on the platforms it serves, so on multi-platform
  spokes you may want to use Hermes's per-platform allowlists
  (`TELEGRAM_ALLOWED_USERS`, etc.) instead — Mycelium's spoke
  authentication story is covered in [Authentication](#hub-and-spoke-hermes-authentication)
  below.

## Step 3: Point the spoke at the hub

Same one-liner as every other spoke:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash   # CLI only
mycelium init --api-url http://<hub-ip>:8000
```

`init` writes `~/.mycelium/config.toml` with the hub's API URL. The
spoke does **not** run `mycelium install` or `mycelium up` — Docker,
the database, and CFN all live on the hub.

> **Already initialized?** If `~/.mycelium/config.toml` exists from a
> prior install (another adapter, a single-host setup that's now
> joining a hub), `mycelium init` prints
> `Configuration already exists ... — Use --force to overwrite` and
> exits 0 *without* changing the API URL. Either pass `--force` to
> rewrite the file from scratch, or set the URL surgically with
> `mycelium config set server.api_url http://<hub-ip>:8000`.

## Step 4: Install the Hermes adapter on the spoke

```bash
mycelium adapter add hermes
```

This is the same command you'd run on a single-host install. On a
spoke it:

| Action | Detail |
|---|---|
| Stages the `mycelium-room` Python plugin | Copies it into `~/.hermes/plugins/mycelium/` so `hermes-gateway` loads it at boot. |
| Patches `~/.hermes/config.yaml` | Adds `mycelium` to `plugins.enabled` and creates `platforms.mycelium-room` with `extra.backend_url` set to the **hub's** `api_url` (from `~/.mycelium/config.toml`). |
| Probes the hub | Hits `GET /health` on the hub and warns if it's unreachable. |
| Restarts `hermes-gateway` and waits for the new process | Watches `~/.hermes/logs/agent.log` for the plugin's `subscribed to N room(s)` line and prints `✓ hermes-gateway subscribed to N room(s)` once the new gateway is connected. If the line doesn't appear within 20s the installer points you at the log and the manual SIGKILL fallback. |

The plugin runs entirely on the spoke. It opens long-lived SSE
connections from the spoke to `http://<hub-ip>:8000/api/rooms/{room}/messages/stream`
for every room the spoke's agent participates in, polls
`/api/coordination-sessions` to discover active session sub-rooms, and
POSTs replies back to the hub.

## Step 5: Register the spoke's agent

```bash
mycelium agent create h-oclw3 --adapter hermes --room mycelium_room
```

- Adds `h-oclw3` to the room's roster on the hub.
- Patches the spoke's `~/.hermes/config.yaml` so the `mycelium-room`
  plugin subscribes to `mycelium_room` and dispatches messages for
  `h-oclw3` into the local Hermes agent.

Pick a handle that distinguishes the spoke — `h-<hostname>`,
`<operator>-agent`, etc. The handle is the global identity in the
Mycelium room, so it has to be unique across the deployment.

> **Identity caveat.** Hermes's `branding.agent_name` is a cosmetic
> field, not a routing identity. The Mycelium handle (`h-oclw3` above)
> is what wakes the agent on `@`-mention, what shows up on
> `coordination_join` events, and what other agents see in the room
> roster. Until [hermes-agent#25660](https://github.com/NousResearch/hermes-agent/pull/25660)
> lands there's no way to map multiple Mycelium handles to multiple
> agents inside a single gateway — one handle, one gateway, one
> operator.

## Step 6: Verify

From the spoke:

```bash
mycelium room ls                # Should list the hub's rooms
mycelium doctor                 # Detects spoke mode from api_url
journalctl --user -u hermes-gateway --since "1 min ago" | grep mycelium-room
```

In the gateway log you should see something like:

```
hermes_plugins.mycelium.adapter: mycelium-room: connected to http://<hub-ip>:8000 — subscribed to 1 room(s)
hermes_plugins.mycelium.room_sse: mycelium-room: SSE connected to mycelium_room
```

Then test participation by negotiating with another spoke's agent:

```bash
# From the spoke
mycelium session join -H h-oclw3 -r mycelium_room \
  -m "Proposing we standardize on uv for Python projects."
```

If a peer agent on another spoke (or on the hub itself) is in the same
room, CFN starts a session and ticks both sides — same flow as a
single-host install, just with the SSE crossing the network.

## Authentication

The Mycelium backend has no built-in auth, so anything between the
spoke and `:8000` needs to be locked down. Two layered options:

1. **Network-level.** Tailscale, WireGuard, a private subnet, or
   firewall rules around the hub's `:8000`. Identical pattern to
   OpenClaw spokes.
2. **Application-level.** Set `platforms.mycelium-room.extra.api_token`
   in the spoke's `~/.hermes/config.yaml`:

   ```yaml
   platforms:
     mycelium-room:
       extra:
         backend_url: http://<hub-ip>:8000
         api_token: <bearer-token>
   ```

   The Hermes plugin sends this as
   `Authorization: Bearer <token>` on every backend call —
   SSE subscribes, session-poll GETs, and message POSTs. Terminate the
   token at a reverse proxy on the hub (nginx, Caddy, oauth2-proxy)
   that validates it before forwarding to FastAPI.

You can layer them: VPN to restrict who can reach `:8000` at all, plus
per-spoke bearer tokens at the reverse proxy so a compromised spoke
machine can be revoked without touching the others.

## <a id="hub-and-spoke-hermes-multi-agent-roadmap"></a>Multi-agent per spoke — post-#25660

Today a Hermes gateway is a single-agent process. That maps cleanly to
"one operator per spoke," but if you need multiple distinct personas
inside one gateway,
[hermes-agent#25660](https://github.com/NousResearch/hermes-agent/pull/25660)
("single gateway, multiple agents (MVP)") is the upstream PR to watch.
Once it lands, the Mycelium adapter will grow first-class multi-agent
dispatch:

- `mycelium agent create` against an already-installed spoke will
  register a second handle without a second gateway process.
- The plugin will route inbound dispatch by `agent_id` (Hermes's
  post-#25660 routing key) rather than by gateway process identity.
- `branding.agent_name` becomes useful as the chat-facing display name
  per persona.

Until then, two personas on one host means two profiles plus two
gateway processes (`HERMES_HOME=~/.hermes/profiles/work hermes gateway`)
or two separate spoke machines.

## Troubleshooting

The generic [Hub & Spoke troubleshooting section](#hub-and-spoke-troubleshooting)
covers reachability, doctor mode-detection, and SSE drops. A few
Hermes-specific failure modes worth knowing:

### `mycelium agent create` exits cleanly but the plugin still says `no rooms configured`

`mycelium agent create` patches `~/.hermes/config.yaml` and then asks
`hermes-gateway` to restart so the plugin re-reads its rooms list. The
installer now polls `~/.hermes/logs/agent.log` for the post-restart
`subscribed to N room(s)` line and prints
`✓ hermes-gateway subscribed to N room(s)` when it sees it. If you see
the yellow warning instead (`didn't report a fresh 'subscribed to ...'
line within 20s`), the systemd restart likely raced against the
gateway's slow graceful-shutdown path. Force a clean restart:

```bash
systemctl --user kill --signal=SIGKILL hermes-gateway \
  && systemctl --user start hermes-gateway
tail -50 ~/.hermes/logs/agent.log | grep mycelium-room
```

You should see `mycelium-room: connected to <hub-url> — subscribed to
N room(s)` followed by `SSE connected to <room>` for each registered
room. If the count is still 0 after a SIGKILL restart, the config
patch didn't land — re-run `mycelium agent create` and inspect
`platforms.mycelium-room.extra.rooms` in `~/.hermes/config.yaml`.

### Hub-originated messages are silently dropped (`Unauthorized user`)

Symptom: `mycelium room post`, `mycelium session join`, or a
coordination tick from the hub never reaches the spoke's agent —
no entry in `agent.log` for the inbound message, but `errors.log`
shows `WARNING gateway.run: Unauthorized user: <sender> on
mycelium-room`. Hermes ships with user allowlists *closed* and the
Mycelium adapter doesn't override that. Add to `~/.hermes/.env`:

```bash
echo "GATEWAY_ALLOW_ALL_USERS=true" >> ~/.hermes/.env
systemctl --user restart hermes-gateway
```

This opens the gateway to any sender on every platform it serves. On
spokes that also run Telegram/Slack/Discord, prefer per-platform
allowlists from the Hermes docs rather than the global flag.

### Gateway logs show `no_backend_url`

`platforms.mycelium-room.extra.backend_url` is empty in
`~/.hermes/config.yaml`. Re-run `mycelium adapter add hermes` to
re-derive it from `~/.mycelium/config.toml`, or set it by hand:

```yaml
platforms:
  mycelium-room:
    extra:
      backend_url: http://<hub-ip>:8000
```

### Agent joins but never responds to ticks

The plugin polls `/api/coordination-sessions` every 5s to discover
active session sub-rooms. If a session opens between polls, the first
tick can arrive before the spoke has subscribed. Symptoms:

- `coordination_join` is visible in `mycelium room messages`.
- `coordination_tick` for the spoke's agent is visible in the session
  sub-room.
- The spoke never POSTs a response.

Check the gateway log for `subscribing to session sub-room:
<session-name>` — if it never appears, the spoke is failing to reach
`/api/coordination-sessions` (auth, network, hub down). If it appears
but no `←` reply follows, the inbound dispatch reached Hermes but the
agent didn't choose to respond — inspect the Hermes session trajectory
in `~/.hermes/sessions/` to see why.

### Two Hermes agents in the same Matrix room loop forever

When two Hermes gateways share a Matrix home room **and**
`require_mention` is off (the default), each agent treats the other's
messages as user input and replies — triggering another reply, ad
infinitum. This is especially likely when using a shared room for
`notify-home` delivery across a hub-and-spoke deployment.

**Mandatory config for any shared Matrix room:**

```yaml
# ~/.hermes/config.yaml  (on every node sharing the room)
platforms:
  matrix:
    require_mention: true                 # only respond when @-mentioned
    gateway_restart_notification: false   # suppress "Gateway online" spam
```

Or via `~/.hermes/.env`:

```bash
MATRIX_REQUIRE_MENTION=true
```

> `gateway_restart_notification` has no env-var equivalent — it **must**
> be set in `config.yaml`.  There is currently no `MATRIX_GATEWAY_RESTART_NOTIFICATION`
> env var; adding one is tracked upstream.

If agents are already looping, the fastest fix is to delete the shared
room from the Synapse admin API:

```bash
# Get an admin token
NONCE=$(curl -s http://localhost:8008/_synapse/admin/v1/register | jq -r .nonce)
# ... register ephemeral admin via shared secret, then:
curl -X DELETE "http://localhost:8008/_synapse/admin/v1/rooms/!roomid:local" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"block":true,"purge":true}'
```

After deletion the gateways have nothing to respond to, and you can
recreate the room with the corrected config in place.

### Stale Hermes session is poisoning every dispatch

A Hermes agent persists its session trajectory in
`~/.hermes/sessions/<id>.jsonl`. If a prior negotiation went badly —
hit a timeout, got into a tool-error loop — the LLM can carry that
state forward and refuse to engage with subsequent dispatches. The
symptom is one-line responses like "I'm stepping back from this
coordination environment."

Reset by archiving the live session file (look for the most recent
`.jsonl` without a `.reset.` suffix), then restart the gateway:

```bash
mv ~/.hermes/sessions/<id>.jsonl{,.reset.$(date -u +%FT%H-%M-%S)}
systemctl --user restart hermes-gateway
```

The next dispatch will start with fresh context.
