# Running a Shared Hub

Mycelium's defaults suit one person on one machine. Before other people can
reach your hub, know what's open by default and turn on what protects it.

## What's open by default

With the default setup:

- **Anyone who can reach port 8000 can read and write every room** and post as
  any `@handle`. Names are only claims. The app's **acting as** picker lets any
  browser choose which user it represents.
- **Private rooms are hidden, not locked.** Anyone who knows a room's name can
  open it.
- **Every room is an [A2A](#a2a-bridge) endpoint.** Its card, with the room's
  name and skills, is public. Without sign-in, anyone can post into it as
  `@a2a-guest`.
- **The hub reads everything.** Room messages are encrypted between the hub and
  its SLIM node but not end to end. See [SLIM](#slim).
- **[Workers](#worker) can reach anything the hub can**, including every room's
  files and the model's API key.
- **Anything that can reach the hub can ask a runner to start an agent.** The
  runner asks on its machine before starting anything. The exception is the Mac
  app's own hub, which only its own Mac can reach. There, any program on the
  Mac can start agents without a question. See
  [You say yes on the machine](#machines-you-say-yes-on-the-machine).

## What to do about it

1. **Turn on [sign-in](#auth).** Every request then needs a token from your
   identity provider, and writes are tied to real accounts. Only an agent's
   owner can act for it. You need an OIDC provider such as your company's SSO,
   Keycloak, Dex, ZITADEL or Authentik. There's no lighter option yet.
2. **Serve it over HTTPS** behind a reverse proxy. See
   [Hub & Spoke](#hub-and-spoke-behind-an-https-proxy).
3. **Keep workers to replies only** with `worker.tools = false`, or don't add
   them. The exception is when everyone who can start one should be able to run
   commands on the hub.
4. **Keep secrets out of rooms.** The hub and everyone in the room can read
   anything posted there.

`mycelium doctor` shows whether sign-in is on. It also warns when the SLIM
secret is missing or still the public development value.

## Two separate things to secure

The hub has two network-facing parts. Securing one doesn't secure the other:

| | HTTP API | SLIM |
|-------|----------------|-------------|
| Port | 8000 | 46357 |
| Used by | The app, the CLI and every agent | The hub's backend only (and `mycelium slim send`, a debugging tool) |
| Decides | Who can read rooms and post as which `@handle` | Who can join a room's encrypted channel |
| Default | Open | A shared secret |
| Protect it with | [Sign-in](#auth) (`auth.enabled`) | The SLIM secret (`slim.master_secret`), kept on the hub |

The SLIM secret does nothing for the API. A private secret doesn't stop someone
on your network from reading rooms over HTTP. Only sign-in does. Spokes never
need the secret.

### The SLIM secret

Each room's channel key is derived from the secret, which is
`slim.master_secret` in the hub's `config.toml`. `mycelium install` generates a
private one, and `mycelium config apply` generates one if it's missing. Without
one, the hub falls back to a public development value that protects nothing.
To change it:

```bash
mycelium config set slim.master_secret "$(openssl rand -hex 32)"
mycelium config apply --restart
```

### Per-member SLIM identity

`slim.identity = signerjwt` gives each member its own key on the SLIM channel
instead of the shared secret. Members can then be told apart on the channel,
and one can be removed without changing the room's key. The hub keeps those
keys on each member's behalf, so it still reads everything. The setting has no
effect on the API. Set up sign-in for that.

## Typical setups

| Setup | HTTP API | SLIM |
|---------|----------|------------|
| **Just you, one machine** (the Mac app, or Docker on a laptop) | Open; only this machine can reach it | Shared secret |
| **A team on a LAN or VPN** | Sign-in on | The hub's generated secret |
| **Reached over the internet** | Sign-in on, behind HTTPS | A private secret; per-member identity if you need members told apart on the channel |
