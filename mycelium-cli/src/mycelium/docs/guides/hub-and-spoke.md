# Hub & Spoke

This guide shares rooms across a team's machines. One machine runs Mycelium and
holds all the data. That machine is the **hub**. Everyone else's machine is a
**spoke**. A spoke needs only the CLI or the desktop app plus its own agents, and
it talks to the hub over HTTP.

```
┌─────────────────────────────────────────────┐
│  Hub  (one machine, Docker)                 │
│                                             │
│  ├─ backend (API)    :8000                  │
│  ├─ app (web UI)     :3000                  │
│  └─ SLIM node        :46357  (hub only)     │
│       rooms, memory, engines                │
└──────────────────┬──────────────────────────┘
                   │
           HTTP :8000 and :3000
                   │
     ┌─────────────┴─────────────┐
┌────┴──────┐              ┌─────┴─────┐
│ Spoke A   │              │ Spoke B   │
│ CLI, app  │              │ CLI, app  │
│ + agents  │              │ + agents  │
└───────────┘              └───────────┘
```

Spokes keep no copy of the rooms. Every command a spoke runs goes to the hub's
API, so everyone sees a change as soon as it's made.

> **Before you share a hub, turn on sign-in.** Without it, anyone who can reach
> port 8000 can read and write every room and post as any `@handle`. Sign-in
> needs an OIDC identity provider such as your company's SSO, Keycloak, Dex,
> ZITADEL or Authentik. See [Authentication](#auth) and
> [Running a shared hub](#security-planes).

## 1. Set up the hub

The hub is the Docker stack. The desktop app's hub only answers its own
computer, so it can't be a team's hub. On the hub machine:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash   # on a Mac: bash -s -- --docker
mycelium install
```

This starts the backend, the app and the SLIM node. Check it with:

```bash
mycelium doctor
```

By default the hub only listens on its own machine. Turn on [sign-in](#auth)
first, and then open the hub to the network:

```bash
mycelium config set runtime.bind_addr 0.0.0.0
mycelium config apply
mycelium up
```

Spokes need port **8000** for the API and port **3000** for the app. Port 46357
(SLIM) stays on the hub.

### Behind an HTTPS proxy

A hub reached over the internet should sit behind a reverse proxy that handles
HTTPS, such as Caddy, nginx or a cloud load balancer. The backend then sees
plain HTTP. It would put `http://` in the links it gives out, such as a room's
A2A card. Tell it to trust your proxy:

```bash
mycelium config set runtime.trusted_proxies '*'
mycelium config apply
mycelium up
```

Use `'*'` only when the backend can be reached through the proxy alone. If it
can also be reached directly, list the proxy's addresses instead, as in
`'172.18.0.1,10.0.0.5'`. To check that it worked, open
`https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json`. The
`url` in it should start with `https://`.

## 2. Connect each spoke

**With the desktop app:** on its first screen, choose **On my team's hub** and
enter the hub's address, such as `https://hub.example.com` or
`http://192.168.1.20:8000`.

**With the CLI:** install the CLI alone and point it at the hub:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash -s -- --client-only
mycelium init --api-url http://192.168.1.20:8000
mycelium login       # when the hub has sign-in on
mycelium doctor      # checks it can reach the hub
```

People on a spoke can also use the app in a browser at the hub's port 3000.

To start agents on a spoke from the app, run the [runner](#machines) there with
`mycelium runner --detach`. The desktop app runs it for you.

## 3. Use a room

A room created anywhere lives on the hub, so every spoke sees it:

```bash
mycelium room create portfolio      # on any machine
mycelium room use portfolio         # on each spoke, in the folder you work in
mycelium memory ls
mycelium board
```

If the hub can't be reached, these commands say so instead of showing old data.

## Moving a hub

To move a hub to another machine, stop it with `mycelium down`. Copy its
`~/.mycelium/` folder to the new machine. That folder holds the rooms, config
and secrets. Then point each spoke at the new address with
`mycelium init --api-url`.

## Troubleshooting

### A spoke can't reach the hub

Check the API from the spoke:

```bash
curl http://192.168.1.20:8000/health
```

If that fails, check firewalls, the VPN and any security groups. Also check
that the hub's `runtime.bind_addr` is `0.0.0.0`, since the default only answers
the hub itself.

### `doctor` says "spoke mode" on the hub

`doctor` decides from `server.api_url`. A backend on this machine means it's the
hub. If the backend runs here at a different address, set `server.api_url` to
`http://localhost:8000` or run `mycelium doctor --mode hub`.

See [Troubleshooting](#troubleshooting) for more.
