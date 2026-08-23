# Bringing an ephemeral agent into a room

Findings from wiring a **Claude Code cloud session** — an agent working in a
container we don't own, on a repository that isn't this one, reclaimed when the
session ends — into a Mycelium room, with nothing but environment variables and a
CLI download.

The short answer: the client surface already supports it. Three installer defects
and a documentation gap stood in the way. This note records what was verified, on
what, and what the flow still depends on that we don't control.

## The target flow

Someone sets a few variables on their cloud environment. A session starts in some
unrelated repository, does its work, and says so in the room:

```bash
mycelium room send "Migrated the session store to Redis. Tests green, PR #412 up."
```

No `.mycelium/` directory, no `config.toml`, no `mycelium login`, no Docker, and
no state that outlives the container.

## What was verified

Every result below was produced in a live Claude Code cloud session: Linux,
`python3` → 3.11, no Docker daemon, egress through a policy proxy.

### Environment variables reach the container

A variable set on the cloud environment arrives as an ordinary environment
variable, readable by any command the agent runs. `HELLO_FROM_ME` was set in the
environment config and read back as `bizbazlol` from the shell.

### The CLI configures itself entirely from the environment

CLI 3.0.1, installed from the release wheel, with `HOME` pointed at an empty
directory — no config file anywhere on the box — against a stub hub:

```bash
MYCELIUM_API_URL=http://127.0.0.1:8899 \
MYCELIUM_ACTIVE_ROOM=demo \
MYCELIUM_AGENT_HANDLE=claude-web \
MYCELIUM_AGENT_AUTH_TOKEN=tok-abc123 \
mycelium room send "Finished the refactor on branch foo."
```

The hub received exactly:

```
POST /api/rooms/demo/messages
Authorization: Bearer tok-abc123
{"sender_handle":"claude-web","message_type":"broadcast",
 "content":"Finished the refactor on branch foo."}
```

`mycelium respond --handle claude-web "…"` produced the same shape against
`POST /api/rooms/demo/reply`. Both printed a normal success line and exited 0.

Four seams carry that, and all four already existed:

| Variable | Resolved by |
| --- | --- |
| `MYCELIUM_API_URL` | `config.py:_load_from_env` → `server.api_url` |
| `MYCELIUM_ACTIVE_ROOM` / `MYCELIUM_ROOM_ID` | `commands/room.py:_resolve_room` |
| `MYCELIUM_AGENT_HANDLE` | `config.py:get_current_identity` (highest priority) |
| `MYCELIUM_AGENT_AUTH_TOKEN` | `agent_credentials.resolve` → `client.auth_headers` |

The token is attached without naming a handle on the command line, because
`ambient_handle()` reads `MYCELIUM_AGENT_HANDLE`. So one `.env` block configures
identity, destination, and credential together.

### The failure modes are already honest

An unreachable hub reports `Failed to connect to the Mycelium API`; a missing room
context reports `No room context found` and names the variable to set. Neither
silently answers from something stale, which is the thin-client property
holding: there is one store, the hub's.

## What was in the way

### 1. The installer required Docker

`install.sh` checks for a Docker daemon and, on Linux, installs Docker if it is
missing — before it has any idea whether this machine will run a stack. An
ephemeral agent talks to a hub someone else runs; there is nothing local to bring
up. In a cloud session the check simply fails.

**Fixed:** `--client-only` (also `MYCELIUM_CLIENT_ONLY=1`) skips the Docker check
and prints spoke-shaped next steps. Setting `MYCELIUM_API_URL` to a non-local hub
implies it, so an environment already configured to reach a hub needs no flag.

### 2. The installer refused an older system Python

The cloud image's `python3` is 3.11, and the installer exits with
`Python 3.12+ required`. It installs `uv` a few lines later — which can fetch a
managed 3.12 on its own — but never gets there. Base images with an older Python
and no way to add one are the normal case for ephemeral runtimes.

**Fixed:** a missing 3.12+ is no longer fatal. The installer passes
`--python 3.12` to `uv tool install`, which downloads a managed interpreter.
Verified end to end on a PATH containing only Python 3.11.

### 3. The PyPI fallback installed a different project

When the release wheel could not be downloaded, the installer fell back to
`uv tool install mycelium-cli`. That name on PyPI belongs to an unrelated
project:

```
mycelium-cli 0.5.1
summary: Mycelium CLI — init, newwallet, compile, deploy, register
```

It pulls `stellar-sdk`, `mnemonic`, and `pynacl`, and installs a `mycelium`
executable that dies on `ModuleNotFoundError: No module named 'mycelium_sdk'`. A
user following our published one-liner gets someone else's package on their PATH
under our name — and the fallback fires precisely when a wheel download fails,
which is what a restricted-egress container looks like.

**Fixed:** the release wheel is the only source. A failed download is now an error
that names the releases page.

### 4. `doctor` reported a false failure

`mycelium doctor` already auto-detects spoke mode from `server.api_url`, but it
flags missing `~/.mycelium/.env` and `config.toml` as an error and advises
`mycelium install` — which needs Docker. For a client configured from the
environment, absent config files are the design, not a fault.

**Fixed:** with `MYCELIUM_API_URL` set, the check reports
`configured from the environment` instead.

### 5. Nothing documented the flow

**Fixed:** the [Ephemeral Agents](../mycelium-cli/src/mycelium/docs/guides/ephemeral-agents.md)
guide covers the
environment variables, the client-only install, announcing, the difference
between `room send` and `respond`, and the Claude-web specifics (environment
dialog, network allowlist, setup script, session-link back-reference).

## What we don't control

Three constraints belong to the hosting platform, and the guide states them
plainly rather than working around them.

**The hub must be public HTTPS.** Cloud session egress goes through a policy
proxy that speaks `CONNECT` only. A hub on a LAN address, on `localhost`, or on
plain `http://` is unreachable — `mycelium hub host` on a laptop cannot serve a
cloud session. A hub that is up but not on the environment's allowlist fails as a
proxy `502`, which reads like the hub being down.

**There is no secrets store.** Cloud environment variables are readable by anyone
who uses the environment, and the platform documents them as unsuitable for
credentials. So the honest recommendation is an ungated hub on a trusted network,
or a short-lived scoped token accepted as readable — not a long-lived bearer.

**Nothing makes the agent announce.** The environment carries the configuration,
never the instruction. Telling the agent to report belongs in the repository it is
working in (`CLAUDE.md` or a skill), which is also the only place that survives
the container.

## Worth filing

1. **Claim the `mycelium-cli` name on PyPI, or pick a different one.** Removing
   the fallback stops us shipping someone else's package, but the name still
   resolves to it for anyone who types `pip install mycelium-cli`.
2. **A credential shaped like an ephemeral agent.** Today the choice is an ungated
   hub or a full bearer token in a place with no secrets store. A short-lived,
   post-only token would fit the announce case exactly.
3. **A one-shot preflight.** `doctor` is spoke-aware but broad. An ephemeral
   container wants one call answering "can I post to this room as this handle?"
   before it tries.
4. **Announcing is one-way, by construction.** A cloud session can report into a
   room but cannot be woken by one; it exists only while its task does. That is
   the cold-start-on-demand gap (#446), and this flow is the strongest argument
   for it so far: the container that just did the work is exactly the one a
   follow-up question wants to reach.

## Update: a scoped workload credential closes the gap

The recommendation under "There is no secrets store" was written before the
`client_credentials` path was exercised against a gated hub. It works, and it is
the practical answer for an agent that has to write for longer than one
short-lived token lasts. This section revises that advice with what a live run
showed.

### What was verified

A confidential Keycloak client (`claude-web`: service accounts on, standard and
direct-access flows off, `fullScopeAllowed` off) with an audience mapper stamping
`mycelium`. From a real Claude Code cloud session, with only these variables and
no config file, the released CLI minted its own token and posted as `@claude-web`:

```bash
MYCELIUM_API_URL=https://<hub-api-host>
MYCELIUM_ACTIVE_ROOM=<room>
MYCELIUM_AGENT_HANDLE=claude-web
MYCELIUM_AGENT_AUTH_ISSUER=https://<hub-auth-host>/realms/mycelium
MYCELIUM_AGENT_AUTH_CLIENT_ID=claude-web
MYCELIUM_AGENT_AUTH_CLIENT_SECRET=<secret>
```

`agent_credentials.resolve` reads the client id and secret directly; the issuer,
scopes, and audience come from `[agent_auth]`, which `config.py` fills from
`MYCELIUM_AGENT_AUTH_ISSUER` / `_SCOPES` / `_AUDIENCE`. The CLI re-mints from the
secret on every call, so the token's 300s lifespan never surfaces: the value you
keep is the secret, not a token.

### The recommendation, revised

The blocker was framed as "no secrets store, so no long-lived credential." The
honest version is blast-radius management, not avoidance. What lives in the env is
the client secret, and keeping it somewhere readable is fine when the client is:

- least privilege (post to rooms, nothing else),
- revocable per agent (disable the client and that identity is dead, nothing else
  is),
- rotatable (rotate the secret on whatever cadence you accept).

Both this project's guide and the hosting platform's own environment dialog warn
against secrets in env. That caution is right for a shared environment or an
over-scoped credential. For a personal environment and a narrowly scoped client,
the readable secret is a managed risk, and it is what makes the flow possible
rather than impossible.

The genuinely secretless path exists only for runtimes that expose a workload
identity to federate: GitHub Actions can trade its OIDC token for a hub token with
no stored secret. Claude Code cloud exposes none today, so a scoped client secret
is the floor there.

### Three things that bite in practice

1. **Both hosts must be on the network allowlist.** The static-token path only
   reaches the API host. `client_credentials` also reaches the issuer to mint, so
   the auth host has to be allowlisted too, or the mint fails at the proxy before
   the write is ever attempted.

2. **`uv tool install <release-url>` fails behind the egress proxy.** GitHub
   redirects a release asset to a signed `objects.githubusercontent.com` URL, and
   the proxy's injected auth header makes the signed URL answer `401`. Plain
   `curl -fsSL` to the same URL answers `200`. So download first, then install the
   local file, keeping the PEP 427 filename or `uv` rejects it for having no
   version. This is exactly what `install.sh --client-only` does, since it
   downloads with curl, and it is a reason to prefer the installer over the
   url-direct form in a proxied environment.

3. **Service-account attribution needs a mapper.** A `client_credentials` token's
   `preferred_username` defaults to `service-account-<client>`, so the agent posts
   under that name. Removing the `profile` default client scope stops the built-in
   username mapper from firing, and a hardcoded `preferred_username` claim then
   wins, so the agent posts as a clean `@handle`.
